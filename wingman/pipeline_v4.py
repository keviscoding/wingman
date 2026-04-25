"""End-to-end v4 orchestration that runs after Pro distillation finishes.

Waits for v4_pro_pairs.jsonl to stabilize, then:
  1. Builds v4 training JSONL (playbook in training system instruction)
  2. Uploads train + val to GCS
  3. Kicks off Vertex tuning job
  4. Polls until complete
  5. Writes v4 endpoint to .env
  6. Logs SUCCESS / FAILURE clearly

Run with nohup and it'll sit waiting for distillation, then do the
rest automatically. The final endpoint ID is written to both
training_dataset/vertex_job.json AND /tmp/v4_endpoint.txt for easy
retrieval.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()


DATA_DIR = Path(__file__).parent.parent / "training_dataset"
PAIRS_FILE = DATA_DIR / "v4_pro_pairs.jsonl"
TRAIN_JSONL = DATA_DIR / "v4_train.jsonl"
VAL_JSONL = DATA_DIR / "v4_val.jsonl"
ENV_FILE = Path(__file__).parent.parent / ".env"
MARKER_FILE = Path("/tmp/v4_endpoint.txt")

BUCKET = "wingman-training-nicheflix-cd240"
PROJECT = "nicheflix-cd240"
LOCATION = "us-central1"
BASE_MODEL = "gemini-2.5-flash"


async def wait_for_distillation(target_count: int, stable_seconds: int = 120):
    """Block until v4_pro_pairs.jsonl stops growing for ``stable_seconds``
    consecutively AND has at least 90% of target_count. Handles cases
    where distillation finishes naturally vs is cut off by failures."""
    print(f"[pipeline] Waiting for distillation "
          f"(target={target_count}, stable_window={stable_seconds}s)...")
    last_count = -1
    stable_since = time.time()
    while True:
        await asyncio.sleep(30)
        count = 0
        if PAIRS_FILE.exists():
            with PAIRS_FILE.open() as f:
                count = sum(1 for _ in f)
        if count != last_count:
            last_count = count
            stable_since = time.time()
            print(f"[pipeline] v4 pairs: {count}/{target_count}")
            continue
        # Count didn't change
        idle = time.time() - stable_since
        if idle >= stable_seconds and count >= int(target_count * 0.85):
            print(f"[pipeline] Distillation stable at {count} pairs "
                  f"({idle:.0f}s idle) — proceeding")
            return count
        if idle >= stable_seconds * 4:
            # Very stuck — proceed anyway if we have any meaningful data
            if count >= 500:
                print(f"[pipeline] Distillation stuck ({idle:.0f}s), "
                      f"proceeding with {count} pairs")
                return count


def build_jsonl():
    from wingman.build_v4_training import build
    stats = build()
    return stats


def upload_to_gcs() -> tuple[str, str]:
    from google.cloud import storage
    client = storage.Client(project=PROJECT)
    bucket = client.bucket(BUCKET)
    ts = time.strftime("%Y%m%d-%H%M%S")
    paths = {}
    for name, src in (("train", TRAIN_JSONL), ("val", VAL_JSONL)):
        blob = bucket.blob(f"tuning-datasets/wingman-v4-{ts}/{name}.jsonl")
        print(f"[pipeline] Uploading {name}: {src.stat().st_size // 1024} KB")
        blob.upload_from_filename(str(src))
        paths[name] = f"gs://{BUCKET}/{blob.name}"
    print(f"[pipeline] train_uri = {paths['train']}")
    print(f"[pipeline] val_uri   = {paths['val']}")
    return paths["train"], paths["val"]


def kickoff_job(train_uri: str, val_uri: str) -> str:
    from wingman.run_finetune import kickoff_tuning_job
    return kickoff_tuning_job(train_uri, val_uri, epochs=3)


def poll_until_done(job_name: str) -> str:
    from wingman.run_finetune import poll_job
    return poll_job(job_name)


def append_v4_to_env(endpoint: str):
    """Add TUNED_V4_ENDPOINT + update TUNED_VERSION=v4 in .env without
    clobbering other env vars. Keeps v1/v2/v3 for A/B comparison."""
    if not endpoint:
        print("[pipeline] No endpoint to persist — skipping .env update")
        return
    lines = ENV_FILE.read_text().splitlines(keepends=False) if ENV_FILE.exists() else []
    keep: list[str] = []
    found_v4 = False
    found_version = False
    for line in lines:
        if line.startswith("TUNED_V4_ENDPOINT="):
            keep.append(f"TUNED_V4_ENDPOINT={endpoint}")
            found_v4 = True
        elif line.startswith("TUNED_VERSION="):
            keep.append("TUNED_VERSION=v4")
            found_version = True
        else:
            keep.append(line)
    if not found_v4:
        keep.append(f"TUNED_V4_ENDPOINT={endpoint}")
    if not found_version:
        keep.append("TUNED_VERSION=v4")
    ENV_FILE.write_text("\n".join(keep) + "\n")
    MARKER_FILE.write_text(endpoint + "\n")
    print(f"[pipeline] .env updated with TUNED_V4_ENDPOINT")
    print(f"[pipeline] Marker file: {MARKER_FILE}")


async def main(target_count: int = 2934):
    try:
        got = await wait_for_distillation(target_count)
        print(f"[pipeline] Distillation complete at {got} pairs")

        print("[pipeline] Building v4 training JSONL...")
        stats = build_jsonl()
        print(f"[pipeline] Estimated training cost: ${stats['estimated_cost_usd']}")

        print("[pipeline] Uploading to GCS...")
        train_uri, val_uri = upload_to_gcs()

        print("[pipeline] Kicking off Vertex tuning job...")
        job_name = kickoff_job(train_uri, val_uri)
        print(f"[pipeline] Job: {job_name}")

        print("[pipeline] Polling until complete (30s ticks)...")
        endpoint = poll_until_done(job_name)
        if not endpoint:
            print("[pipeline] ERROR: tuning failed — no endpoint produced")
            sys.exit(1)

        append_v4_to_env(endpoint)
        print()
        print("=" * 60)
        print("V4 PIPELINE COMPLETE")
        print(f"  Endpoint: {endpoint}")
        print(f"  .env updated — restart the server to activate")
        print("=" * 60)
    except Exception as exc:
        import traceback
        print(f"[pipeline] FATAL: {exc}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
