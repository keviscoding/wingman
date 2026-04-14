"""Wingman orchestrator.

Flash Live handles voice commands ("read this" / "done") and speaks back.
ChatReader (Flash-Lite) reads each screen frame during collection for
reliable message extraction. Pro generates reply options.

In headless mode (server without screen/mic), screenshot uploads drive
the same pipeline.
"""

from __future__ import annotations

import asyncio
import os
import sys

from wingman.transcript import ConversationState
from wingman.reply_generator import ReplyGenerator
from wingman.chat_store import ChatStore
from wingman.training import TrainingCache
from wingman.presets import PresetStore
from wingman.chat_reader import ChatReader

HEADLESS = os.getenv("WINGMAN_HEADLESS", "").lower() in ("1", "true", "yes")

if sys.version_info < (3, 11, 0):
    import taskgroup, exceptiongroup  # noqa: F401
    asyncio.TaskGroup = taskgroup.TaskGroup
    asyncio.ExceptionGroup = exceptiongroup.ExceptionGroup


class _DummyLive:
    mic_muted = False
    def stop(self): pass
    async def run(self): await asyncio.Event().wait()
    async def send_frame(self, data: bytes): pass


class _DummyCapture:
    def stop(self): pass
    async def stream(self):
        await asyncio.Event().wait()
        return
        yield


class Wingman:
    def __init__(self, capture_region=None, headless: bool = HEADLESS):
        self.headless = headless
        self.conversation = ConversationState()
        self.generator = ReplyGenerator()
        self.reader = ChatReader()
        self.store = ChatStore()
        self.training = TrainingCache()
        self.presets = PresetStore()
        self.active_preset: int = -1

        if headless:
            self.capture = _DummyCapture()
            self.live = _DummyLive()
            print("[wingman] Running in HEADLESS mode (no screen capture / mic)")
        else:
            from wingman.capture import CaptureRegion, ScreenCapture
            from wingman.live_session import LiveSession
            self.capture = ScreenCapture(region=capture_region)
            self.live = LiveSession(on_command=self._on_voice_command)

        self.latest_replies: list[dict] = []
        self.latest_read: str = ""
        self.latest_advice: str = ""
        self.latest_frame_b64: str = ""
        self.current_contact: str = ""
        self.saved_contacts: list[str] = self.store.list_contacts()
        self.status: str = "idle"
        self.collecting_count: int = 0
        self.status_version: int = 0
        self.transcript_version: int = 0
        self.replies_version: int = 0

        self._pending_regen: int | None = None
        self._regen_extra_context: str = ""
        self._frame_collecting: bool = False
        self._collecting_context: str = ""
        self._pending_done: bool = False

    def _bump(self):
        self.status_version += 1

    # ── Voice command callback (from Flash Live) ─────────────────────

    def _on_voice_command(self, command: str, contact: str, context: str):
        """Called by LiveSession when it detects a voice command."""
        if command == "start_reading":
            self.start_collecting(contact, context)
        elif command == "done":
            if context:
                self._collecting_context = (
                    (self._collecting_context + " " + context)
                    if self._collecting_context else context
                )
            asyncio.create_task(self.stop_collecting())
        else:
            print(f"[wingman] Unknown voice command: {command}")

    # ── Start / Stop collection (called from voice or UI buttons) ────

    def start_collecting(self, contact: str, context: str = ""):
        """Begin frame-by-frame collection. Each new frame is read by ChatReader."""
        new_contact = contact.strip() or self.current_contact or "Unknown"

        same_contact = (
            self.current_contact
            and self.current_contact.lower() == new_contact.lower()
        )

        if same_contact:
            print(f"[wingman] Continue collecting for {self.current_contact} "
                  f"({len(self.conversation.messages)} existing messages — will append)")
        else:
            print(f"[wingman] Start collecting: {new_contact} (new contact)")
            self.current_contact = new_contact
            self.conversation.messages.clear()
            self.conversation.new_since_last_generation = 0
            existing = self.store.load(self.current_contact)
            if existing:
                self.conversation.ingest_parsed_messages(existing)
                print(f"[wingman]   loaded {len(self.conversation.messages)} saved messages")

        self._collecting_context = context
        self._frame_collecting = True
        self.status = "collecting"
        self.collecting_count = len(self.conversation.messages)
        self._bump()

    async def stop_collecting(self):
        """Stop frame collection, wait for in-flight reads, then trigger replies."""
        self._frame_collecting = False
        if self.reader.is_busy:
            print("[wingman] Waiting for reader to finish...")
            while self.reader.is_busy:
                await asyncio.sleep(0.3)
        print(f"[wingman] Stop collecting — {len(self.conversation.messages)} total messages")
        self._pending_done = True
        self._bump()

    # ── Frame loop (screen capture → Live + ChatReader) ──────────────

    async def _frame_loop(self):
        """Grab screen frames. Always update preview; only read when collecting."""
        print("[wingman] Screen capture started")
        import mss, asyncio as _aio
        from wingman.capture import Frame
        sct = mss.mss()
        monitor = self.capture._build_monitor(sct)
        while True:
            frame = await asyncio.to_thread(self.capture._grab_frame, sct, monitor)
            self.latest_frame_b64 = frame.jpeg_b64

            if self._frame_collecting and not self.reader.is_busy:
                print("[wingman] Sending frame to reader...")
                asyncio.create_task(self._read_frame(frame.jpeg_bytes))

            await asyncio.sleep(0.5 if self._frame_collecting else 2.0)

    async def _read_frame(self, jpeg_bytes: bytes):
        """Send a single frame to ChatReader and ingest the results."""
        try:
            result = await self.reader.read(jpeg_bytes)
            if result.messages:
                added = self.conversation.ingest_parsed_messages(result.messages)
                if added:
                    self.transcript_version += 1
                    self.collecting_count = len(self.conversation.messages)
                    self.store.save(self.current_contact, self.conversation.messages)
                    self.saved_contacts = self.store.list_contacts()
                    print(f"[wingman]   +{added} msgs from frame (total {len(self.conversation.messages)})")
                    self._bump()
        except Exception as exc:
            print(f"[wingman] Frame read error: {exc}")

    # ── Command loop (handles pending generation / regen) ────────────

    async def _command_loop(self):
        while True:
            await asyncio.sleep(0.3)

            if self._pending_done:
                self._pending_done = False
                self.live.mic_muted = True
                self.status = "generating"
                self._bump()
                print(f"[wingman] Generating replies for {self.current_contact} "
                      f"({len(self.conversation.messages)} messages)...")
                await self._generate_replies(context=self._collecting_context)
                self._collecting_context = ""

            if self._pending_regen is not None:
                preset_idx = self._pending_regen
                extra = self._regen_extra_context
                self._pending_regen = None
                self._regen_extra_context = ""
                if self.conversation.messages:
                    self.live.mic_muted = True
                    self.status = "generating"
                    self._bump()
                    await self._generate_replies(
                        context=extra, preset_idx=preset_idx,
                    )

    # ── Reply generation ─────────────────────────────────────────────

    async def _generate_replies(self, context: str = "", preset_idx: int | None = None):
        if not self.conversation.messages:
            self.status = "idle"
            self._bump()
            return

        idx = preset_idx if preset_idx is not None else self.active_preset
        preset_goal = self.presets.get(idx) if idx >= 0 else ""
        goal = preset_goal or context or ""

        transcript_json = self.conversation.to_json()
        if goal:
            print(f"[wingman] Generating replies (goal: {goal[:60]})...")
        else:
            print("[wingman] Generating replies (default)...")

        result = await self.generator.generate(
            transcript_json, extra_context=context, goal=goal,
        )
        self.conversation.mark_generation_done()
        self.latest_replies = [o.to_dict() for o in result.replies]
        self.latest_read = result.read
        self.latest_advice = result.advice
        self.replies_version += 1

        if result.replies:
            print(f"[wingman] Got {len(result.replies)} reply options:")
            for opt in result.replies:
                why = f" — {opt.why}" if opt.why else ""
                print(f"  [{opt.label}] {opt.text[:60]}{why}")
        if result.read:
            print(f"[wingman] Read: {result.read[:120]}")
        if result.advice:
            print(f"[wingman] Advice: {result.advice[:120]}")

        self.live.mic_muted = False
        self.status = "done"
        self._bump()

    # ── Screenshot upload (headless / mobile) ────────────────────────

    async def process_media(
        self,
        contact: str,
        media_items: list[tuple[bytes, str]],
        extra_context: str = "",
    ):
        """Process uploaded screenshots/videos in a SINGLE batch call."""
        self.status = "processing"
        self._bump()

        new_contact = contact.strip() or self.current_contact or "Unknown"
        if not self.current_contact or self.current_contact.lower() != new_contact.lower():
            self.current_contact = new_contact
            self.conversation.messages.clear()
            self.conversation.new_since_last_generation = 0
            existing = self.store.load(self.current_contact)
            if existing:
                self.conversation.ingest_parsed_messages(existing)
                print(f"[wingman] Loaded {len(self.conversation.messages)} saved messages for {self.current_contact}")

        print(f"[wingman] Processing {len(media_items)} file(s) in single batch...")
        result = await self.reader.read_batch(media_items)

        if result.messages:
            added = self.conversation.ingest_parsed_messages(result.messages)
            print(f"[wingman] +{added} new messages (total {len(self.conversation.messages)})")
            self.transcript_version += 1
            self.store.save(self.current_contact, self.conversation.messages)
            self.saved_contacts = self.store.list_contacts()

        if not self.conversation.messages:
            self.status = "idle"
            self._bump()
            return

        self.status = "generating"
        self._bump()
        await self._generate_replies(context=extra_context)

    # ── Contact management ───────────────────────────────────────────

    def load_contact(self, contact: str):
        existing = self.store.load(contact)
        self.conversation.messages.clear()
        self.conversation.new_since_last_generation = 0
        if existing:
            self.conversation.ingest_parsed_messages(existing)
        self.current_contact = contact
        self.latest_replies = []
        self.transcript_version += 1
        self.replies_version += 1
        self.status = "done" if self.conversation.messages else "idle"
        self._bump()
        print(f"[wingman] Loaded chat with {contact}: {len(self.conversation.messages)} messages")

    # ── Live session wrapper with auto-reconnect ─────────────────────

    async def _live_wrapper(self):
        while True:
            try:
                await self.live.run()
            except Exception as exc:
                print(f"[wingman] Voice error: {exc}")
                print("[wingman] Reconnecting in 3 seconds...")
                await asyncio.sleep(3)

    # ── Main run ─────────────────────────────────────────────────────

    async def run(self):
        mode = "HEADLESS" if self.headless else "DESKTOP"
        print(f"[wingman] Starting Wingman ({mode})...")

        if self.training.load():
            self.generator.set_cache(self.training.cache_name, training_cache=self.training)
            print(f"[wingman] Training loaded: {self.training.file_count} files, "
                  f"{self.training.token_count:,} tokens cached")
        else:
            print("[wingman] No training data — add .txt files to training/ folder")

        if self.headless:
            print("[wingman] Ready — upload screenshots from the web UI")
            await self._command_loop()
        else:
            print("[wingman] Ready — say 'read this' or click Start Reading")
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._live_wrapper())
                tg.create_task(self._frame_loop())
                tg.create_task(self._command_loop())


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wingman")
    parser.add_argument("--left", type=int, default=None)
    parser.add_argument("--top", type=int, default=None)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--headless", action="store_true",
                        help="Run without screen capture / mic (server mode)")
    args = parser.parse_args()

    if args.headless:
        asyncio.run(Wingman(headless=True).run())
    else:
        from wingman.capture import CaptureRegion
        region = CaptureRegion(left=args.left, top=args.top, width=args.width, height=args.height)
        asyncio.run(Wingman(capture_region=region).run())

if __name__ == "__main__":
    main()
