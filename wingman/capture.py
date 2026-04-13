"""Screen capture with change detection.

Grabs a configurable region of the screen at ~1 FPS, detects whether the
content actually changed, and yields only the new frames.
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from dataclasses import dataclass, field

import mss
import numpy as np
import PIL.Image

from wingman.config import (
    CAPTURE_FPS,
    CAPTURE_MAX_WIDTH,
    FRAME_CHANGE_THRESHOLD,
)


@dataclass
class CaptureRegion:
    """Screen region to capture.  None values mean 'full screen'."""
    left: int | None = None
    top: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class Frame:
    """A single captured frame with metadata."""
    image: PIL.Image.Image
    jpeg_bytes: bytes
    jpeg_b64: str
    timestamp: float
    width: int
    height: int


class ScreenCapture:
    """Captures a screen region and emits frames only when the content changes."""

    def __init__(self, region: CaptureRegion | None = None):
        self.region = region or CaptureRegion()
        self._prev_gray: np.ndarray | None = None
        self._running = False
        self._monitor_dirty = True  # rebuild monitor dict on next frame

    def set_region(self, region: CaptureRegion):
        """Update the capture region at runtime."""
        self.region = region
        self._monitor_dirty = True
        self._prev_gray = None  # force change detection on next frame

    def _build_monitor(self, sct: mss.mss) -> dict:
        base = sct.monitors[0]  # full virtual screen
        return {
            "left": self.region.left if self.region.left is not None else base["left"],
            "top": self.region.top if self.region.top is not None else base["top"],
            "width": self.region.width if self.region.width is not None else base["width"],
            "height": self.region.height if self.region.height is not None else base["height"],
        }

    def _grab_frame(self, sct: mss.mss, monitor: dict) -> Frame:
        raw = sct.grab(monitor)
        img = PIL.Image.frombytes("RGB", raw.size, raw.rgb)

        # Resize to keep token cost sane
        if img.width > CAPTURE_MAX_WIDTH:
            ratio = CAPTURE_MAX_WIDTH / img.width
            img = img.resize(
                (CAPTURE_MAX_WIDTH, int(img.height * ratio)),
                PIL.Image.LANCZOS,
            )

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        jpeg_bytes = buf.getvalue()

        return Frame(
            image=img,
            jpeg_bytes=jpeg_bytes,
            jpeg_b64=base64.b64encode(jpeg_bytes).decode(),
            timestamp=time.time(),
            width=img.width,
            height=img.height,
        )

    def _has_changed(self, frame: Frame) -> bool:
        gray = np.array(frame.image.convert("L"), dtype=np.float32)

        if self._prev_gray is None:
            self._prev_gray = gray
            return True  # first frame always counts

        if gray.shape != self._prev_gray.shape:
            self._prev_gray = gray
            return True

        diff = np.abs(gray - self._prev_gray)
        changed_pixels = np.count_nonzero(diff > 25)  # tolerance per-pixel
        fraction = changed_pixels / gray.size

        self._prev_gray = gray
        return fraction > FRAME_CHANGE_THRESHOLD

    async def stream(self):
        """Async generator yielding Frame objects when screen content changes."""
        self._running = True
        interval = 1.0 / CAPTURE_FPS

        sct = mss.mss()
        monitor = self._build_monitor(sct)

        try:
            while self._running:
                if self._monitor_dirty:
                    monitor = self._build_monitor(sct)
                    self._monitor_dirty = False
                frame = await asyncio.to_thread(self._grab_frame, sct, monitor)
                if self._has_changed(frame):
                    yield frame
                await asyncio.sleep(interval)
        finally:
            sct.close()

    def stop(self):
        self._running = False
