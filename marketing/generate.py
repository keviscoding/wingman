"""Viral-script generator — Phase 1 CLI.

Usage (from repo root):

    python -m marketing.generate \\
        --mode playful_goofball \\
        --opener-bias balanced \\
        --length medium \\
        --variants 3 \\
        --out /tmp/scripts

Output: one JSON file per variant, plus a pretty-printed text preview
for eyeballing.

The generator calls Gemini 3.1 Pro through the existing wingman client
so it re-uses the Vertex vs AI-Studio routing set up elsewhere. No new
credentials needed.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

from google.genai import types as gtypes

from .client import PRO_MODEL, make_genai_client, rotate_api_key

from .corpus import load_raw_corpus
from .prompts import (
    OpenerBias,
    TonalMode,
    build_system_prompt,
    build_user_prompt,
)


VARIANT_HINTS: tuple[str, ...] = (
    "start with a gimmick, not a compliment",
    "open with a fake complaint or accusation",
    "use a callback joke that returns in the final 3 messages",
    "make the pushback longer than usual — 4 exchanges before she softens",
    "end with a plot twist that reframes the whole conversation",
    "use a customer-service / review / rating structure throughout",
    "make him ask a weird out-of-pocket question as the opener",
    "use a theme-word that appears in both the opener and the closer",
)


def generate_one(
    *,
    mode: TonalMode,
    opener_bias: OpenerBias,
    length: str,
    twist: str,
    hook_image_note: str | None,
    hook_image_path: Path | None,
    variant_hint: str | None,
    corpus: str,
) -> dict[str, Any]:
    """Single call into Gemini. Returns the parsed JSON script.

    If ``hook_image_path`` is given we attach it as an inline image
    so Gemini 3.1 Pro's vision can look at it directly. That lets
    the model write an opener that riffs on what's actually in the
    image (pose, outfit, vibe, location) when opener_bias permits —
    or confidently IGNORE the image and drop a spontaneous banger
    when opener_bias=spontaneous.

    Retries up to 3 times with key rotation on transient errors."""
    system_prompt = build_system_prompt(
        mode=mode,
        opener_bias=opener_bias,
        corpus=corpus,
        length=length,  # type: ignore[arg-type]
        twist=twist,  # type: ignore[arg-type]
    )
    user_prompt = build_user_prompt(
        hook_image_note=hook_image_note,
        variant_hint=variant_hint,
        has_image=hook_image_path is not None,
    )

    # Build the multimodal payload. The image (if any) goes first so
    # it's the first thing the model conditions on.
    parts: list[Any] = []
    if hook_image_path is not None:
        img_bytes = hook_image_path.read_bytes()
        mime = mimetypes.guess_type(hook_image_path.name)[0] or "image/jpeg"
        parts.append(gtypes.Part.from_bytes(data=img_bytes, mime_type=mime))
    parts.append(user_prompt)

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            client = make_genai_client()
            resp = client.models.generate_content(
                model=PRO_MODEL,
                contents=parts,
                config=gtypes.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=1.0,  # higher = more spontaneity
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
            text = resp.text or ""
            return _parse_json_strict(text)
        except Exception as exc:
            last_err = exc
            rotate_api_key()
            time.sleep(0.5)
    raise RuntimeError(f"generation failed after retries: {last_err}")


def _parse_json_strict(text: str) -> dict[str, Any]:
    """Strip any markdown fences, trim whitespace, then json.loads.

    Gemini occasionally wraps JSON output in ```json ... ``` even when
    response_mime_type is set. Defensive strip handles both shapes.
    If JSON parses clean, return it. Otherwise try light repair for
    the most common truncation patterns (mid-string, unclosed array)
    and fail loudly if repair doesn't help.
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"```\s*$", "", t)
    t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        repaired = _attempt_json_repair(t)
        return json.loads(repaired)


def _attempt_json_repair(text: str) -> str:
    """Heuristic recovery for the most common model-truncation cases.

    We look for the last complete message object (matched by the
    closing brace before a quote or comma) and then synthesise a
    clean tail that closes the messages array + the outer object.

    Conservative — if we can't find a safe truncation point we
    return the original text so json.loads surfaces the real error.
    """
    # Find the last complete ``}`` that looks like a message closer
    # (i.e., "speaker": ... "pause_ms": N }). We cut right after it.
    last_close = text.rfind("}")
    if last_close == -1:
        return text
    # If there's an open quote with no matching close between the
    # last "}," and end, we're mid-string; walk back to a safe spot.
    head = text[: last_close + 1]
    # Strip any trailing comma so the synthesised closer is valid.
    head = head.rstrip().rstrip(",")
    # Synthesise the remainder. We assume the messages array and the
    # outer object are both unclosed (standard truncation shape).
    tail_candidates = [
        "\n]}",                                    # close array + obj
        '\n]\n,\n"reveal_after_index": 0\n}',      # add missing field
        "\n]}" + "\n",
    ]
    for tail in tail_candidates:
        candidate = head + tail
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return text


def pretty_print_script(script: dict[str, Any]) -> str:
    """Human-readable preview for eyeballing."""
    out: list[str] = []
    hook = script.get("hook_caption") or "(no hook caption)"
    mode = script.get("mode", "?")
    bias = script.get("opener_bias_used", "?")
    dur = script.get("estimated_duration_s", "?")
    reveal = script.get("reveal_after_index", "?")
    twist = script.get("twist_summary") or "—"
    cta = script.get("suggested_cta") or "—"

    out.append(f"┌─ [{mode} · {bias} · {dur}s · reveal@{reveal}]")
    out.append(f"│  {hook}")
    out.append(f"│")
    for i, m in enumerate(script.get("messages", [])):
        speaker = m.get("speaker", "?")
        text = m.get("text", "")
        pause = m.get("pause_ms", "?")
        arrow = "►" if speaker == "him" else "◄"
        marker = "  ⟵ REVEAL HERE" if i == reveal else ""
        out.append(f"│  {arrow} {text}  ({pause}ms){marker}")
    out.append(f"│")
    out.append(f"│  Twist: {twist}")
    out.append(f"│  CTA:   {cta}")
    out.append(f"└─")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=[
            "playful_goofball", "cocky_critic", "dark_taboo",
            "forward_direct", "smooth_recovery",
        ],
        required=True,
        help="Tonal mode for the script.",
    )
    parser.add_argument(
        "--opener-bias",
        choices=["spontaneous", "image_tied", "balanced"],
        default="balanced",
        help="How much the opener should lean on the image.",
    )
    parser.add_argument(
        "--length",
        choices=["short", "medium", "long"],
        default="medium",
    )
    parser.add_argument(
        "--twist",
        choices=["none", "optional", "required"],
        default="optional",
    )
    parser.add_argument(
        "--hook-note",
        type=str,
        default=None,
        help="Optional one-line description of the hook image. "
             "If --hook-image is also given, Gemini sees both.",
    )
    parser.add_argument(
        "--hook-image",
        type=str,
        default=None,
        help="Path to a hook image file (e.g. hook_images_v2/hook_042.jpg). "
             "Passed to Gemini 3.1 Pro as a vision input so the opener "
             "can riff on what's actually in the picture — or ignore "
             "it entirely when --opener-bias=spontaneous.",
    )
    parser.add_argument(
        "--random-hook",
        action="store_true",
        help="Pick a random image from hook_images_v2/ instead of "
             "specifying one with --hook-image. Useful for batch testing.",
    )
    parser.add_argument(
        "--variants",
        type=int,
        default=1,
        help="Number of independent scripts to generate.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Directory to save JSON + preview files. If omitted, "
             "scripts are printed to stdout only.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for variant-hint sampling. Reproducible "
             "variety if set.",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    corpus = load_raw_corpus()
    if not corpus:
        print("[marketing] Training corpus is empty — check MARKETING TRAINING CHATS/ folder.", file=sys.stderr)
        return 2

    out_dir: Path | None = None
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)

    hints = list(VARIANT_HINTS)
    random.shuffle(hints)

    hook_pool: list[Path] = []
    if args.random_hook:
        hook_dir = Path(__file__).resolve().parent.parent / "hook_images_v2"
        hook_pool = sorted(hook_dir.glob("*.jpg"))
        if not hook_pool:
            print(f"[marketing] No images in {hook_dir}", file=sys.stderr)
            return 2

    for i in range(args.variants):
        variant_hint = hints[i % len(hints)]
        image_path: Path | None = None
        if args.hook_image:
            image_path = Path(args.hook_image)
            if not image_path.exists():
                print(f"[marketing] Hook image not found: {image_path}", file=sys.stderr)
                return 2
        elif args.random_hook:
            image_path = random.choice(hook_pool)

        image_note = f"(using image {image_path.name})" if image_path else "(no image)"
        print(f"\n[{i+1}/{args.variants}] mode={args.mode} bias={args.opener_bias} {image_note} hint='{variant_hint}'", file=sys.stderr)
        t0 = time.time()
        try:
            script = generate_one(
                mode=args.mode,
                opener_bias=args.opener_bias,
                length=args.length,
                twist=args.twist,
                hook_image_note=args.hook_note,
                hook_image_path=image_path,
                variant_hint=variant_hint,
                corpus=corpus,
            )
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            continue
        dt = time.time() - t0
        # Occasionally Gemini returns a list with one script inside it
        # instead of a bare object. Unwrap gracefully so we don't crash.
        if isinstance(script, list):
            if not script:
                print("  FAILED: empty list returned", file=sys.stderr)
                continue
            script = script[0]
        if not isinstance(script, dict):
            print(f"  FAILED: unexpected response type: {type(script).__name__}", file=sys.stderr)
            continue
        # Tag the script with which image was used so editors can pair.
        if image_path is not None:
            script["_hook_image"] = image_path.name
        print(f"  ok — {dt:.1f}s — {len(script.get('messages', []))} messages", file=sys.stderr)

        preview = pretty_print_script(script)
        print()
        print(preview)

        if out_dir:
            stamp = int(time.time())
            base = out_dir / f"script_{args.mode}_{stamp}_{i}"
            base.with_suffix(".json").write_text(
                json.dumps(script, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            base.with_suffix(".txt").write_text(preview, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
