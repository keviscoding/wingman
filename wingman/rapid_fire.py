"""Rapid Fire mode: record screen, send video to Flash, extract all chats at once.

Records the screen as a video while the user clicks through their chat app.
After recording stops, the video is sent to Flash in ONE API call to extract
all distinct conversations with contact names and messages.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import threading
from pathlib import Path

# Desktop-only deps. Made optional so this module loads cleanly on
# headless Linux boxes (e.g. the SaaS server on DigitalOcean) where
# OpenCV / mss aren't installed. The code paths that actually USE
# these only run from the desktop entry point.
try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

import numpy as np

try:
    import mss  # type: ignore
except Exception:  # pragma: no cover
    mss = None  # type: ignore

from google.genai import types

from wingman.config import FLASH_MODEL, make_genai_client

RAPID_VIDEO_PROMPT = (
    "This video shows someone clicking through multiple chat conversations on a dating/messaging app.\n\n"
    "Your job: identify EVERY distinct conversation that appears in the video.\n"
    "Watch for when the screen changes to a different chat (different contact name at the top).\n\n"
    "For EACH distinct conversation you see, extract:\n"
    "- The contact name (shown at the top of the chat screen)\n"
    "- The platform (tinder/hinge/whatsapp/instagram/imessage/other)\n"
    "- ALL messages visible in that chat\n\n"
    "Return a JSON array of all conversations:\n"
    "[{\"contact\": \"Name\", \"platform\": \"whatsapp\", "
    "\"messages\": [{\"speaker\": \"me\", \"text\": \"...\", \"time\": \"...\"}, "
    "{\"speaker\": \"them\", \"text\": \"...\", \"time\": \"...\"}]}]\n\n"
    "speaker = \"me\" for messages I sent (right side / colored bubbles)\n"
    "speaker = \"them\" for messages they sent (left side / plain bubbles)\n"
    "time = timestamp if visible, omit if not.\n\n"
    "Even if a chat has zero messages (just opened), include it with an empty messages array.\n"
    "IMPORTANT: Extract EVERY conversation you see, even briefly."
)


class RapidFireSession:
    """Manages a rapid fire capture session using video recording."""

    def __init__(self):
        self._client = None
        self.detected: list[dict] = []
        self.is_active: bool = False
        self.is_analyzing: bool = False
        self._recording: bool = False
        self._video_path: str = ""
        self._record_thread: threading.Thread | None = None
        self._capture_region: dict | None = None
        self._platform_hint: str = ""
        self._start_time: float = 0

    def _get_client(self):
        if self._client is None:
            self._client = make_genai_client()
        return self._client

    def start(self, platform: str = "", capture_region: dict | None = None):
        self.detected = []
        self.is_active = True
        self.is_analyzing = False
        self._platform_hint = platform
        self._capture_region = capture_region
        self._start_time = time.time()

        tf = tempfile.NamedTemporaryFile(suffix=".avi", delete=False)
        self._video_path = tf.name
        tf.close()

        self._recording = True
        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()
        print(f"[rapid] Recording started -> {self._video_path}")

    def _record_loop(self):
        """Record screen to video file in a background thread."""
        fps = 3
        try:
            with mss.mss() as sct:
                if self._capture_region:
                    monitor = self._capture_region
                else:
                    monitor = sct.monitors[0]

                width = monitor["width"]
                height = monitor["height"]
                max_w = 1024
                if width > max_w:
                    scale = max_w / width
                    width = max_w
                    height = int(height * scale)
                else:
                    scale = 1.0

                fourcc = cv2.VideoWriter_fourcc(*"MJPG")
                writer = cv2.VideoWriter(self._video_path, fourcc, fps, (width, height))
                if not writer.isOpened():
                    print("[rapid] ERROR: VideoWriter failed to open")
                    return

                while self._recording:
                    raw = sct.grab(monitor)
                    frame = np.array(raw)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    if scale != 1.0:
                        frame = cv2.resize(frame, (width, height))
                    writer.write(frame)
                    time.sleep(1.0 / fps)

                writer.release()
                elapsed = time.time() - self._start_time
                print(f"[rapid] Recording saved: {elapsed:.1f}s")
        except Exception as exc:
            print(f"[rapid] Recording error: {exc}")

    def stop(self):
        self._recording = False
        if self._record_thread:
            self._record_thread.join(timeout=3)
        self.is_active = False
        elapsed = time.time() - self._start_time
        print(f"[rapid] Recording stopped after {elapsed:.1f}s")

    async def analyze(self) -> list[dict]:
        """Upload video via Files API, then send to Flash for extraction."""
        self.is_analyzing = True
        print("[rapid] Uploading video for analysis...")

        try:
            client = self._get_client()

            video_file = await asyncio.to_thread(
                client.files.upload, file=self._video_path,
            )
            print(f"[rapid] Video uploaded: {video_file.name}")

            # Wait for processing
            import time as _time
            for _ in range(30):
                status = await asyncio.to_thread(client.files.get, name=video_file.name)
                if status.state.name == "ACTIVE":
                    break
                await asyncio.sleep(2)

            print("[rapid] Analyzing video with Flash...")
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=FLASH_MODEL,
                contents=[RAPID_VIDEO_PROMPT, video_file],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=32768,
                ),
            )

            import re
            text = (response.text or "").strip()
            fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if fence:
                text = fence.group(1).strip()

            data = json.loads(text)
            if isinstance(data, list):
                self.detected = data
            elif isinstance(data, dict) and "conversations" in data:
                self.detected = data["conversations"]
            else:
                self.detected = [data] if isinstance(data, dict) else []

            for chat in self.detected:
                if self._platform_hint and not chat.get("platform"):
                    chat["platform"] = self._platform_hint

            print(f"[rapid] Detected {len(self.detected)} conversations from video")

            try:
                await asyncio.to_thread(client.files.delete, name=video_file.name)
            except Exception:
                pass

        except Exception as exc:
            print(f"[rapid] Video analysis failed: {exc}")
            self.detected = []
        finally:
            self.is_analyzing = False
            try:
                Path(self._video_path).unlink(missing_ok=True)
            except Exception:
                pass

        return self.detected

    def get_results(self) -> list[dict]:
        results = []
        for i, chat in enumerate(self.detected):
            contact = chat.get("contact", f"Unknown {i+1}")
            platform = chat.get("platform", "other")
            msgs = chat.get("messages", [])
            key = f"{platform} - {contact}" if self._platform_hint else contact
            results.append({
                "key": key, "contact": contact, "platform": platform,
                "message_count": len(msgs),
            })
        return results
