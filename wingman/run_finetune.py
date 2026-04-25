"""Run the Vertex AI supervised fine-tuning job on Gemini 2.5 Flash
using the Pro-distilled pairs.

Steps:
  1. Convert pro_distillation_pairs.jsonl -> Vertex JSONL (train + val)
  2. Upload both JSONLs to GCS
  3. Create a Vertex AI supervised-tuning job
  4. Poll until done
  5. Print the tuned model endpoint name so the app can use it

Defaults are aligned with Google's guidance:
  - 3 epochs
  - Learning rate multiplier 1.0
  - Adapter size: auto (Vertex picks 4 by default for Flash)
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


DATA_DIR = Path(__file__).parent.parent / "training_dataset"
PAIRS_FILE = DATA_DIR / "pro_distillation_pairs.jsonl"
MINED_FILE = DATA_DIR / "mined_situations.jsonl"
TRAIN_JSONL = DATA_DIR / "vertex_train.jsonl"
VAL_JSONL = DATA_DIR / "vertex_val.jsonl"
CONFIG_FILE = DATA_DIR / "vertex_job.json"

BUCKET = "wingman-training-nicheflix-cd240"
PROJECT = "nicheflix-cd240"
LOCATION = "us-central1"
BASE_MODEL = "gemini-2.5-flash"

# System instruction baked into every training row. Kept LEAN on
# purpose — the whole point of fine-tuning is to compress the Alex
# persona into weights so we don't have to ship 10k chars of playbook
# to the tuned model at inference time.
SYSTEM_INSTRUCTION = (
    "You are Alex, a high-value dating text-game coach in the voice of "
    "Playing With Fire. Read the conversation and respond with ONE short "
    "natural SMS reply — witty, specific, punchy, emotionally aware, "
    "never generic. Output ONLY the reply text."
)


def _vertex_row(situation: str, reply: str) -> dict:
    user_text = (
        "Conversation so far:\n"
        f"{situation}\n\n"
        "Write the next reply I should send."
    )
    return {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": SYSTEM_INSTRUCTION}],
        },
        "contents": [
            {"role": "user",  "parts": [{"text": user_text}]},
            {"role": "model", "parts": [{"text": reply}]},
        ],
    }


def build_vertex_jsonl(split: float = 0.05, seed: int = 42,
                        include_mined: bool = True) -> dict:
    """Build Vertex JSONL from both sources:
      • Pro-distilled pairs (user's chats → Pro labels)
      • Mined transcript pairs (PWF transcripts → Alex's own replies)

    Together these give the tuned model BOTH user-situational coverage
    (from actual chats) AND broader scenario diversity + authentic
    Alex voice (from transcripts).
    """
    if not PAIRS_FILE.exists():
        raise FileNotFoundError(
            f"{PAIRS_FILE} not found — run `python -m wingman.distill_from_pro` first"
        )

    rows: list[dict] = []
    source_counts = {"pro_distilled": 0, "transcript_mined": 0}

    # Source 1: Pro-distilled pairs from user's chats
    with PAIRS_FILE.open() as f:
        for line in f:
            d = json.loads(line)
            reply = (d.get("pro_reply") or "").strip()
            sit = (d.get("situation") or "").strip()
            if not reply or not sit:
                continue
            if len(reply) < 3 or len(reply) > 500:
                continue
            rows.append(_vertex_row(sit, reply))
            source_counts["pro_distilled"] += 1

    # Source 2: Alex's authentic replies mined from transcripts
    if include_mined and MINED_FILE.exists():
        with MINED_FILE.open() as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                reply = (d.get("alex_suggested_reply") or "").strip()
                sit = (d.get("situation") or "").strip()
                if not reply or not sit:
                    continue
                if len(reply) < 3 or len(reply) > 500:
                    continue
                rows.append(_vertex_row(sit, reply))
                source_counts["transcript_mined"] += 1

    print(f"[finetune] Sources: "
          f"{source_counts['pro_distilled']} Pro-distilled + "
          f"{source_counts['transcript_mined']} transcript-mined = "
          f"{len(rows)} total rows")

    rng = random.Random(seed)
    rng.shuffle(rows)
    n_val = max(10, int(len(rows) * split))
    val_rows = rows[:n_val]
    train_rows = rows[n_val:]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRAIN_JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in train_rows))
    VAL_JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in val_rows))

    print(f"[finetune] Wrote {TRAIN_JSONL.name}: {len(train_rows)} rows")
    print(f"[finetune] Wrote {VAL_JSONL.name}:   {len(val_rows)} rows")
    return {"train": len(train_rows), "val": len(val_rows)}


def upload_to_gcs() -> tuple[str, str]:
    """Upload train + val JSONL to the project's GCS bucket. Returns
    (train_uri, val_uri)."""
    from google.cloud import storage

    client = storage.Client(project=PROJECT)
    bucket = client.bucket(BUCKET)

    ts = time.strftime("%Y%m%d-%H%M%S")
    train_blob = bucket.blob(f"tuning-datasets/wingman-{ts}/train.jsonl")
    val_blob = bucket.blob(f"tuning-datasets/wingman-{ts}/val.jsonl")
    print(f"[finetune] Uploading train.jsonl ({TRAIN_JSONL.stat().st_size // 1024} KB)...")
    train_blob.upload_from_filename(str(TRAIN_JSONL))
    print(f"[finetune] Uploading val.jsonl   ({VAL_JSONL.stat().st_size // 1024} KB)...")
    val_blob.upload_from_filename(str(VAL_JSONL))

    train_uri = f"gs://{BUCKET}/{train_blob.name}"
    val_uri = f"gs://{BUCKET}/{val_blob.name}"
    print(f"[finetune] train_uri = {train_uri}")
    print(f"[finetune] val_uri   = {val_uri}")
    return train_uri, val_uri


def kickoff_tuning_job(train_uri: str, val_uri: str, epochs: int = 3) -> str:
    """Create a supervised-tuning job on Vertex via the Gen AI SDK.
    Returns the job resource name."""
    from google import genai
    from google.genai import types as gtypes

    # vertexai=True routes the client at the Vertex API instead of
    # AI Studio. Required for tuning.
    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)

    print(f"[finetune] Creating tuning job on {BASE_MODEL}...")
    ts = time.strftime("%Y%m%d-%H%M%S")
    display_name = f"wingman-{ts}"

    tuning_dataset = gtypes.TuningDataset(gcs_uri=train_uri)
    validation_dataset = gtypes.TuningValidationDataset(gcs_uri=val_uri)
    config = gtypes.CreateTuningJobConfig(
        tuned_model_display_name=display_name,
        validation_dataset=validation_dataset,
        epoch_count=epochs,
    )

    job = client.tunings.tune(
        base_model=BASE_MODEL,
        training_dataset=tuning_dataset,
        config=config,
    )
    # Save job details so we can resume polling after a restart
    job_info = {
        "name": job.name,
        "display_name": display_name,
        "base_model": BASE_MODEL,
        "train_uri": train_uri,
        "val_uri": val_uri,
        "epochs": epochs,
        "created_at": ts,
    }
    CONFIG_FILE.write_text(json.dumps(job_info, indent=2))
    print(f"[finetune] Job created: {job.name}")
    print(f"[finetune] Display name: {display_name}")
    print(f"[finetune] Saved job info to {CONFIG_FILE}")
    return job.name


def poll_job(job_name: str | None = None, poll_interval: float = 30.0):
    """Poll a tuning job until it's done. Prints progress every
    ``poll_interval`` seconds. Returns the final tuned model name."""
    from google import genai

    if job_name is None:
        if not CONFIG_FILE.exists():
            raise RuntimeError("No job_name provided and no saved config")
        job_name = json.loads(CONFIG_FILE.read_text())["name"]

    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
    started = time.time()
    while True:
        # Network resilience — transient DNS/TCP errors shouldn't
        # abort a 60-90 minute poll. Retry up to 5 times with backoff.
        job = None
        for retry in range(5):
            try:
                job = client.tunings.get(name=job_name)
                break
            except Exception as exc:
                wait = 2 ** retry
                print(f"[finetune] poll error ({exc.__class__.__name__}: "
                      f"{str(exc)[:100]}), retrying in {wait}s")
                time.sleep(wait)
        if job is None:
            print("[finetune] Poll exhausted retries — waiting 60s and retrying")
            time.sleep(60)
            continue
        state = str(getattr(job, "state", "") or "")
        elapsed = time.time() - started
        print(f"[finetune] {elapsed/60:.1f}min  state={state}  "
              f"model={getattr(job.tuned_model, 'endpoint', None) if getattr(job, 'tuned_model', None) else 'pending'}")

        # Terminal states: SUCCEEDED / FAILED / CANCELLED
        if "SUCCEEDED" in state:
            tuned = job.tuned_model
            endpoint = getattr(tuned, "endpoint", None)
            model = getattr(tuned, "model", None)
            print()
            print("=" * 60)
            print(f"TUNING COMPLETE")
            print(f"  Endpoint: {endpoint}")
            print(f"  Model:    {model}")
            print("=" * 60)
            # Persist final result
            d = json.loads(CONFIG_FILE.read_text())
            d["tuned_model_endpoint"] = endpoint
            d["tuned_model_name"] = model
            d["final_state"] = state
            CONFIG_FILE.write_text(json.dumps(d, indent=2))
            return endpoint
        if "FAILED" in state or "CANCELLED" in state:
            err = getattr(job, "error", None)
            print(f"[finetune] TERMINAL: {state}, error={err}")
            return None
        time.sleep(poll_interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", choices=["prep", "upload", "kickoff", "poll", "all"],
                    default="all", help="Which step to run (default: all)")
    ap.add_argument("--epochs", type=int, default=3)
    args = ap.parse_args()

    if args.step in ("prep", "all"):
        build_vertex_jsonl()
    if args.step in ("upload", "all"):
        upload_to_gcs()
    if args.step == "kickoff":
        info = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
        train_uri = info.get("train_uri")
        val_uri = info.get("val_uri")
        if not train_uri or not val_uri:
            raise RuntimeError("Run --step upload first")
        kickoff_tuning_job(train_uri, val_uri, epochs=args.epochs)
    if args.step in ("all",):
        train_uri, val_uri = upload_to_gcs() if args.step == "all" else (None, None)
        # The above already uploaded; re-read URIs from what we just created
        train_uri = train_uri or f"gs://{BUCKET}/tuning-datasets/latest/train.jsonl"
        val_uri = val_uri or f"gs://{BUCKET}/tuning-datasets/latest/val.jsonl"
        job_name = kickoff_tuning_job(train_uri, val_uri, epochs=args.epochs)
        poll_job(job_name)
    if args.step == "poll":
        poll_job()


if __name__ == "__main__":
    main()
