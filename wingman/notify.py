"""macOS notification helper.

Tries the following in order, falls through silently on any failure:
  1. ``terminal-notifier`` (preferred) — banners come from a dedicated
     app called "terminal-notifier" that has its own Notification
     permission row in System Settings, so the user can reliably
     enable it.
  2. ``osascript`` — built-in but posts as "Script Editor" which is
     hidden in modern macOS versions.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def _sanitize(s: str) -> str:
    return s.replace('"', "'").replace("\n", " ").replace("\r", " ")[:400]


def _via_terminal_notifier(title: str, body: str, subtitle: str, open_url: str) -> bool:
    bin_path = shutil.which("terminal-notifier") or "/opt/homebrew/bin/terminal-notifier"
    if not os.path.exists(bin_path):
        return False
    cmd = [bin_path, "-title", title, "-message", body or " "]
    if subtitle:
        cmd += ["-subtitle", subtitle]
    # Group by title so repeat notifications from the same contact update in place
    cmd += ["-group", title]
    if open_url:
        cmd += ["-open", open_url]
    try:
        subprocess.run(
            cmd, check=False, timeout=3,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _via_osascript(title: str, body: str, subtitle: str) -> bool:
    parts = [f'display notification "{body}" with title "{title}"']
    if subtitle:
        parts.append(f'subtitle "{subtitle}"')
    script = " ".join(parts)
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False, timeout=3,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def notify(title: str, body: str = "", subtitle: str = "", open_url: str = "") -> None:
    """Post a macOS notification.

    ``open_url`` (terminal-notifier only): URL to open when the user clicks
    the banner. Use this to deep-link back to a chat:
        notify("Sarah", "hey", open_url="http://127.0.0.1:8000/#Sarah")
    """
    if os.getenv("WINGMAN_NOTIFY", "background") == "never":
        return
    title = _sanitize(title or "Wingman")
    body = _sanitize(body)
    subtitle = _sanitize(subtitle)
    if _via_terminal_notifier(title, body, subtitle, open_url):
        return
    _via_osascript(title, body, subtitle)
