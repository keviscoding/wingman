"""Global hotkey listener for instant screen capture.

Runs in a background daemon thread. When the hotkey fires, takes a
full-screen JPEG, injects it into ``wingman.latest_frame_b64`` and POSTs
to the existing ``/api/quick-capture`` endpoint. No other app state is
touched — hotkey stays isolated from the generation pipeline.

Optional dependency: ``pynput``. If it is not installed (or the OS denies
accessibility permission) the listener silently disables itself and
logs a single line.
"""

from __future__ import annotations

import base64
import io
import os
import threading
import time
import urllib.parse
import urllib.request
import urllib.error

from wingman.notify import notify

DEFAULT_HOTKEY = "<cmd>+<shift>+<space>"
MIN_INTERVAL = 0.8  # debounce re-fires within this many seconds


class HotkeyListener:
    def __init__(
        self,
        wingman,
        server_url: str = "http://127.0.0.1:8000",
        hotkey: str | None = None,
    ):
        self._wingman = wingman
        self._server_url = server_url.rstrip("/")
        self._hotkey_str = hotkey or os.getenv("WINGMAN_HOTKEY", DEFAULT_HOTKEY)
        self._listener = None
        self._last_fire = 0.0
        self.enabled = bool(self._hotkey_str)

    def start(self) -> bool:
        if not self.enabled:
            print("[hotkey] disabled (WINGMAN_HOTKEY empty)")
            return False
        try:
            from pynput import keyboard  # type: ignore
            import mss  # noqa: F401
        except ImportError as exc:
            print(f"[hotkey] pynput/mss missing ({exc}) — install with `pip install pynput`")
            self.enabled = False
            return False

        # ── pynput 1.8.x / Python 3.14 compatibility shim ──
        # In this combo, pynput's internal callback wrapper invokes
        # ``f(*args)`` on the bound method without forwarding the
        # ``injected`` flag that GlobalHotKeys._on_press now requires.
        # The listener then dies on the first keypress with:
        #   TypeError: _on_press() missing 1 required positional argument: 'injected'
        # Subclassing and defaulting the arg absorbs the mismatch safely.
        class _SafeHotKeys(keyboard.GlobalHotKeys):  # type: ignore[misc]
            def _on_press(self, key, injected=False):  # type: ignore[override]
                return super()._on_press(key, injected)

            def _on_release(self, key, injected=False):  # type: ignore[override]
                return super()._on_release(key, injected)

        try:
            self._listener = _SafeHotKeys({self._hotkey_str: self._on_fire})
            self._listener.daemon = True
            self._listener.start()
            print(f"[hotkey] Global hotkey active: {self._hotkey_str}")
            return True
        except Exception as exc:
            # Usually means macOS Accessibility permission isn't granted.
            print(f"[hotkey] failed to start ({exc}) — grant Accessibility perm for your terminal/IDE")
            self.enabled = False
            return False

    def stop(self):
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass

    # ── internals ──────────────────────────────────────────────────

    def _on_fire(self):
        if not self.enabled:
            return
        now = time.time()
        if now - self._last_fire < MIN_INTERVAL:
            return
        self._last_fire = now
        threading.Thread(target=self._capture_and_send, daemon=True).start()

    def _capture_and_send(self):
        try:
            jpeg = self._snap_full_screen()
            # Pixels are now frozen in memory — safe to scroll away. Banner
            # confirms that explicitly so the user isn't guessing whether
            # the shot landed.
            notify("Wingman", "Captured — generating…", subtitle="Screenshot saved, safe to scroll")
            # Send the JPEG bytes directly so rapid-fire presses don't
            # stomp each other's frames through the shared buffer.
            self._post_quick_capture(jpeg)
        except Exception as exc:
            print(f"[hotkey] capture failed: {exc}")
            notify("Wingman", f"Capture failed: {exc}")

    def _frontmost_window_bounds(self) -> "dict | None":
        """Return the rect of the frontmost on-screen window via Quartz.
        Returns a dict {left, top, width, height} or None on any failure.
        Used to crop the capture so ONLY the focused chat window makes
        it to Flash — no Cursor/IDE/sidebar text leaking in as 'messages'.
        """
        try:
            from Quartz import (  # type: ignore
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGWindowListExcludeDesktopElements,
                kCGNullWindowID,
            )
        except Exception:
            return None
        try:
            infos = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
                kCGNullWindowID,
            ) or []
        except Exception:
            return None

        # The first non-trivial on-screen, normal-layer window is the frontmost.
        for info in infos:
            try:
                layer = int(info.get("kCGWindowLayer", 1))
                if layer != 0:
                    continue  # system UI / menubar / dock etc.
                # Skip our own Wingman window if visible.
                owner = (info.get("kCGWindowOwnerName") or "").lower()
                if owner in ("wingman", "python", "python3"):
                    continue
                bounds = info.get("kCGWindowBounds")
                if not bounds:
                    continue
                w = int(bounds.get("Width", 0))
                h = int(bounds.get("Height", 0))
                if w < 300 or h < 200:  # probably a toolbar/popover, skip
                    continue
                return {
                    "left": int(bounds.get("X", 0)),
                    "top": int(bounds.get("Y", 0)),
                    "width": w,
                    "height": h,
                }
            except Exception:
                continue
        return None

    def _snap_full_screen(self) -> bytes:
        """Grab the focused window when possible (so stray Cursor/IDE/
        sidebar text can't leak into Flash's extraction). Falls back to
        the full virtual screen if the focused-window query fails.
        """
        import mss
        import PIL.Image
        from wingman.config import CAPTURE_MAX_WIDTH

        bounds = self._frontmost_window_bounds()
        with mss.mss() as sct:
            if bounds:
                # Clamp to the full virtual desktop so off-screen coords
                # can't crash mss.
                vs = sct.monitors[0]
                left = max(bounds["left"], vs["left"])
                top = max(bounds["top"], vs["top"])
                right = min(bounds["left"] + bounds["width"], vs["left"] + vs["width"])
                bot = min(bounds["top"] + bounds["height"], vs["top"] + vs["height"])
                region = {"left": left, "top": top,
                          "width": max(1, right - left),
                          "height": max(1, bot - top)}
                raw = sct.grab(region)
                print(f"[hotkey] Captured focused window {region['width']}x{region['height']}")
            else:
                raw = sct.grab(sct.monitors[0])
                print("[hotkey] Captured full screen (no focused-window bounds)")
        img = PIL.Image.frombytes("RGB", raw.size, raw.rgb)
        if img.width > CAPTURE_MAX_WIDTH:
            ratio = CAPTURE_MAX_WIDTH / img.width
            img = img.resize(
                (CAPTURE_MAX_WIDTH, int(img.height * ratio)),
                PIL.Image.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()

    def _post_quick_capture(self, jpeg_bytes: bytes):
        # auto_detect=1 tells the server to ignore the currently-viewed
        # chat and extract the contact name from the screenshot itself.
        # image_b64 carries this specific JPEG so concurrent hotkey presses
        # never read each other's screens.
        fields = {
            "contact": "",
            "extra_context": "",
            "auto_detect": "1",
            "image_b64": base64.b64encode(jpeg_bytes).decode(),
        }
        body = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(
            f"{self._server_url}/api/quick-capture",
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                _ = resp.read()
        except urllib.error.HTTPError as exc:
            print(f"[hotkey] server returned HTTP {exc.code}")
        except Exception as exc:
            print(f"[hotkey] POST failed: {exc}")
