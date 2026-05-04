"""Visual renderer — Phase 2.

Takes a JSON script produced by ``marketing.generate`` and spits out
pixel-perfect 1080×1920 Instagram DM frames. One PNG per bubble-state,
plus a manifest.json that tells the video editor how long to show
each frame.

Editor workflow:

  1. ``python -m marketing.generate ... --out ./scripts``
  2. ``python -m marketing.render ./scripts/<script>.json --out ./frames``
  3. Drag ./frames/* into CapCut as an image sequence.
  4. Each frame's duration comes from manifest.json (auto-imported by
     some editors; otherwise the editor reads the manifest and sets
     durations manually).
  5. Layer over B-roll → export → post.

Renderer uses Playwright (headless Chromium) so the output is actual
browser-rendered HTML/CSS — same pixels viewers would see if they
visited the HTML template at 1080×1920. This gives us Instagram-
accurate gradients, fonts, rounded corners, and emoji support.

Setup (one-time):
    pip install playwright
    python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

TEMPLATE_HTML = Path(__file__).resolve().parent / "templates" / "dm.html"


def _encode_image_to_data_uri(path: Path) -> str:
    """Turn a local image into a data: URI so the HTML can embed it
    without needing a file-server. Keeps the renderer fully self-
    contained."""
    suffix = path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _resolve_hook_image(script: dict[str, Any]) -> Path | None:
    """If the script was generated with --hook-image, the path lives
    in `_hook_image` on the script dict. Match it back to the real
    file in hook_images_v2/."""
    name = script.get("_hook_image")
    if not name:
        return None
    p = Path(__file__).resolve().parent.parent / "hook_images_v2" / name
    return p if p.exists() else None


def render_script(
    script: dict[str, Any],
    out_dir: Path,
    *,
    contact_name: str = "mystery.girl",
    include_typing_at_reveal: bool = True,
) -> dict[str, Any]:
    """Render every bubble-state frame for the given script.

    Returns the manifest dict (also written to out_dir/manifest.json).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Playwright isn't installed. Run:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        ) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    messages = script.get("messages") or []
    if not messages:
        raise ValueError("script has no messages")

    hook_caption = script.get("hook_caption") or "You replied to their story"
    reveal_after = script.get("reveal_after_index")
    if isinstance(reveal_after, str):
        try:
            reveal_after = int(reveal_after)
        except ValueError:
            reveal_after = None

    hook_path = _resolve_hook_image(script)
    avatar_uri = _encode_image_to_data_uri(hook_path) if hook_path else ""

    template_url = TEMPLATE_HTML.resolve().as_uri()

    frames: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            device_scale_factor=1,
        )
        page = ctx.new_page()
        page.goto(template_url)
        # Wait for the __RENDER__ hook to exist.
        page.wait_for_function("window.__RENDER__ !== undefined")
        page.evaluate(
            "cfg => window.__RENDER__.setup(cfg)",
            {
                "avatar_url": avatar_uri,
                "contact_name": contact_name,
                "hook_caption": hook_caption,
                "story_sub": "tap to view",
                "hide_story_reply": False,
            },
        )

        def snapshot(upto: int, *, typing: bool, label: str) -> Path:
            # Playwright page.evaluate takes ONE arg after the expr.
            # Pack everything into a single dict and destructure JS-side.
            page.evaluate(
                "payload => window.__RENDER__.setMessages("
                "  payload.messages, payload.upto, { typing: payload.typing })",
                {"messages": messages, "upto": upto, "typing": typing},
            )
            # Give the browser one frame to lay out (prevents partial renders).
            page.wait_for_timeout(30)
            frame_path = out_dir / f"frame_{label}.png"
            page.screenshot(path=str(frame_path), full_page=False, type="png")
            return frame_path

        # Frame 0 — empty thread (just the story-reply banner). Useful
        # as an intro beat before the first bubble appears.
        f = snapshot(0, typing=False, label="000_intro")
        frames.append({"file": f.name, "upto": 0, "duration_ms": 500, "kind": "intro"})

        # One frame per bubble reveal.
        for i in range(1, len(messages) + 1):
            pause = messages[i - 1].get("pause_ms", 800)
            # Insert a "typing indicator" frame right before the reveal
            # message (drama beat that matches real texting).
            if include_typing_at_reveal and reveal_after is not None and i - 1 == (reveal_after + 1):
                t = snapshot(i - 1, typing=True, label=f"{i-1:03d}_typing")
                frames.append({"file": t.name, "upto": i - 1, "duration_ms": 1200, "kind": "typing"})
            f = snapshot(i, typing=False, label=f"{i:03d}_msg")
            kind = "message"
            if reveal_after is not None and i - 1 == reveal_after + 1:
                kind = "muzo_reveal"
            frames.append({
                "file": f.name,
                "upto": i,
                "duration_ms": int(pause),
                "kind": kind,
                "speaker": messages[i - 1].get("speaker"),
                "text": messages[i - 1].get("text"),
            })

        browser.close()

    manifest = {
        "script_hook_caption": hook_caption,
        "script_cta": script.get("suggested_cta"),
        "reveal_after_index": reveal_after,
        "frames": frames,
        "total_duration_ms": sum(f["duration_ms"] for f in frames),
        "viewport": {"width": 1080, "height": 1920},
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    (out_dir / "script.json").write_text(
        json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", help="Path to a script JSON produced by marketing.generate")
    parser.add_argument(
        "--out", required=True,
        help="Output directory for frames + manifest.",
    )
    parser.add_argument(
        "--contact-name", default="mystery.girl",
        help="Name shown in the chat header.",
    )
    parser.add_argument(
        "--no-typing-reveal", action="store_true",
        help="Skip the extra typing-indicator frame before the reveal "
             "message. Default: include it (matches viral pacing).",
    )
    args = parser.parse_args()

    script_path = Path(args.script)
    if not script_path.exists():
        print(f"Script not found: {script_path}", file=sys.stderr)
        return 2

    script = json.loads(script_path.read_text(encoding="utf-8"))

    print(f"[render] rendering {script_path.name} → {args.out}", file=sys.stderr)
    t0 = time.time()
    manifest = render_script(
        script, Path(args.out),
        contact_name=args.contact_name,
        include_typing_at_reveal=not args.no_typing_reveal,
    )
    dt = time.time() - t0
    total_s = manifest["total_duration_ms"] / 1000
    print(
        f"[render] ok — {len(manifest['frames'])} frames in {dt:.1f}s "
        f"(video length: ~{total_s:.1f}s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
