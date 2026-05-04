"""One-shot pipeline: generate a script AND render it to PNG frames.

Wraps ``marketing.generate`` + ``marketing.render`` into a single
command so operators / editors can run one line and see output.

Usage:
    python -m marketing.pipeline \\
        --mode playful_goofball \\
        --opener-bias balanced \\
        --random-hook \\
        --out ./out/video_001

Produces ``./out/video_001/frames/`` with ~15-25 PNG frames plus
a manifest.json that tells the editor how long each frame should
appear in the final video.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

from .corpus import load_raw_corpus
from .generate import generate_one, pretty_print_script, VARIANT_HINTS
from .render import render_script


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=[
            "playful_goofball", "cocky_critic", "dark_taboo",
            "forward_direct", "smooth_recovery",
        ],
        required=True,
    )
    parser.add_argument(
        "--opener-bias",
        choices=["spontaneous", "image_tied", "balanced"],
        default="balanced",
    )
    parser.add_argument(
        "--length",
        choices=["short", "medium", "long"],
        default="short",
        help="Short (~12s) is the default since short-form video retention "
             "drops past 15s. Bump to medium for longer narrative arcs.",
    )
    parser.add_argument(
        "--twist",
        choices=["none", "optional", "required"],
        default="optional",
    )
    parser.add_argument(
        "--hook-image",
        type=str,
        default=None,
        help="Path to a specific hook image. Otherwise uses --random-hook.",
    )
    parser.add_argument(
        "--random-hook",
        action="store_true",
        help="Pick a random image from hook_images_v2/.",
    )
    parser.add_argument(
        "--contact-name",
        default="mystery.girl",
        help="Name shown in the chat header.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output directory. Will contain script.json, manifest.json, "
             "and all PNG frames.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the output folder in Finder when done (macOS).",
    )
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    hook_path: Path | None = None
    if args.hook_image:
        hook_path = Path(args.hook_image)
        if not hook_path.exists():
            print(f"hook image not found: {hook_path}", file=sys.stderr)
            return 2
    elif args.random_hook:
        hook_dir = Path(__file__).resolve().parent.parent / "hook_images_v2"
        pool = sorted(hook_dir.glob("*.jpg"))
        if not pool:
            print(f"no hook images in {hook_dir}", file=sys.stderr)
            return 2
        hook_path = random.choice(pool)

    corpus = load_raw_corpus()
    if not corpus:
        print("training corpus empty — check MARKETING TRAINING CHATS/", file=sys.stderr)
        return 2

    hint = random.choice(VARIANT_HINTS)
    note = f"(image: {hook_path.name})" if hook_path else "(no image)"
    print(f"\n[1/2] generating script — mode={args.mode} {note}", file=sys.stderr)
    t0 = time.time()
    script = generate_one(
        mode=args.mode,
        opener_bias=args.opener_bias,
        length=args.length,
        twist=args.twist,
        hook_image_note=None,
        hook_image_path=hook_path,
        variant_hint=hint,
        corpus=corpus,
    )
    if isinstance(script, list):
        script = script[0]
    if hook_path is not None:
        script["_hook_image"] = hook_path.name
    print(f"      ok — {time.time() - t0:.1f}s — {len(script.get('messages', []))} messages", file=sys.stderr)
    print()
    print(pretty_print_script(script))
    print()

    print(f"[2/2] rendering frames → {out_dir}/frames", file=sys.stderr)
    t0 = time.time()
    manifest = render_script(
        script, out_dir / "frames",
        contact_name=args.contact_name,
        include_typing_at_reveal=True,
    )
    frames = manifest["frames"]
    dt = time.time() - t0
    total_s = manifest["total_duration_ms"] / 1000
    print(
        f"      ok — {len(frames)} frames in {dt:.1f}s "
        f"(estimated video length: {total_s:.1f}s)",
        file=sys.stderr,
    )

    # Drop the raw script alongside the frames for archival.
    (out_dir / "script.json").write_text(
        json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    print(f"\nDONE — {out_dir}", file=sys.stderr)
    print(f"   {len(frames)} frames + manifest.json ready for your editor", file=sys.stderr)

    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(out_dir / "frames")], check=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
