"""Wingman orchestrator.

The Live voice model sees the screen, hears the user, reads the chat,
and sends structured data to Pro for reply generation.
Conversations are saved per contact and build up over time.

In headless mode (server without screen/mic), the screenshot upload
endpoint drives the same pipeline.
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
    """Stub for LiveSession when running headless (no mic/screen)."""
    mic_muted = False
    def stop(self): pass
    async def run(self): await asyncio.Event().wait()
    async def send_frame(self, data: bytes): pass


class _DummyCapture:
    """Stub for ScreenCapture when running headless."""
    def stop(self): pass
    async def stream(self):
        await asyncio.Event().wait()
        return
        yield  # make it an async generator


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
            self.live = LiveSession(on_analyze_chat=self._on_analyze_chat)

        self.latest_replies: list[dict] = []
        self.latest_read: str = ""
        self.latest_advice: str = ""
        self.latest_frame_b64: str = ""
        self.current_contact: str = ""
        self.saved_contacts: list[str] = self.store.list_contacts()
        self.status: str = "idle"
        self.status_version: int = 0
        self.transcript_version: int = 0
        self.replies_version: int = 0

        self._pending_analysis: tuple[str, list[dict], str, str] | None = None
        self._pending_regen: int | None = None
        self._regen_extra_context: str = ""

    def _bump(self):
        self.status_version += 1

    def _on_analyze_chat(self, contact: str, messages: list[dict], style: str, context: str):
        print(f"[wingman] Got {len(messages)} msgs from Live model (contact={contact}, style={style})")
        self._pending_analysis = (contact, messages, style, context)

    async def _process_analysis(self, contact: str, messages: list[dict], style: str, context: str):
        self.live.mic_muted = True
        new_contact = contact.strip() or "Unknown"
        self.status = "processing"
        self._bump()

        # Check if this is the same contact already loaded
        same_contact = (
            self.current_contact
            and new_contact.lower() == self.current_contact.lower()
        )

        if same_contact:
            # Same person — just append new messages on top of existing history
            before = len(self.conversation.messages)
            added = self.conversation.ingest_parsed_messages(messages)
            print(f"[wingman] Updated {self.current_contact}: +{added} new "
                  f"(was {before}, now {len(self.conversation.messages)})")
        else:
            # Different person — load their saved history, then add new
            self.current_contact = new_contact
            self.conversation.messages.clear()
            self.conversation.new_since_last_generation = 0

            existing = self.store.load(self.current_contact)
            if existing:
                self.conversation.ingest_parsed_messages(existing)
                print(f"[wingman] Loaded {len(self.conversation.messages)} "
                      f"saved messages for {self.current_contact}")

            added = self.conversation.ingest_parsed_messages(messages)
            print(f"[wingman] +{added} new messages "
                  f"(total {len(self.conversation.messages)})")

        self.transcript_version += 1

        # Save updated history
        self.store.save(self.current_contact, self.conversation.messages)
        self.saved_contacts = self.store.list_contacts()

        if not self.conversation.messages:
            self.live.mic_muted = False
            self.status = "idle"
            self._bump()
            return

        # Generate replies
        self.generator.style = style
        self.status = "generating"
        self._bump()
        await self._generate_replies(context)

    async def _generate_replies(self, context: str = "", preset_idx: int | None = None):
        if not self.conversation.messages:
            return

        # Build goal from active preset (or override)
        idx = preset_idx if preset_idx is not None else self.active_preset
        preset_goal = self.presets.get(idx) if idx >= 0 else ""
        goal = preset_goal or context or ""

        transcript_json = self.conversation.to_json(last_n=50)
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

    async def process_screenshots(
        self,
        contact: str,
        jpeg_images: list[bytes],
        extra_context: str = "",
    ):
        """Process uploaded screenshots: extract chat via ChatReader, generate replies."""
        self.live.mic_muted = True
        self.status = "processing"
        self._bump()

        new_contact = contact.strip() or "Unknown"
        same_contact = (
            self.current_contact
            and new_contact.lower() == self.current_contact.lower()
        )

        if not same_contact:
            self.current_contact = new_contact
            self.conversation.messages.clear()
            self.conversation.new_since_last_generation = 0
            existing = self.store.load(self.current_contact)
            if existing:
                self.conversation.ingest_parsed_messages(existing)
                print(f"[wingman] Loaded {len(self.conversation.messages)} saved messages for {self.current_contact}")

        all_messages: list[dict] = []
        for i, jpeg in enumerate(jpeg_images):
            print(f"[wingman] Reading screenshot {i+1}/{len(jpeg_images)}...")
            result = await self.reader.read(jpeg)
            if result.messages:
                all_messages.extend(result.messages)
                print(f"[wingman]   -> {len(result.messages)} messages extracted")
            else:
                print(f"[wingman]   -> no chat found in screenshot {i+1}")

        if all_messages:
            added = self.conversation.ingest_parsed_messages(all_messages)
            print(f"[wingman] +{added} new messages (total {len(self.conversation.messages)})")
            self.transcript_version += 1
            self.store.save(self.current_contact, self.conversation.messages)
            self.saved_contacts = self.store.list_contacts()

        if not self.conversation.messages:
            self.live.mic_muted = False
            self.status = "idle"
            self._bump()
            return

        self.status = "generating"
        self._bump()
        await self._generate_replies(context=extra_context)

    def load_contact(self, contact: str):
        """Switch to a saved contact's chat history."""
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

    async def _frame_loop(self):
        print("[wingman] Screen capture started")
        async for frame in self.capture.stream():
            self.latest_frame_b64 = frame.jpeg_b64
            await self.live.send_frame(frame.jpeg_bytes)

    async def _command_loop(self):
        while True:
            await asyncio.sleep(0.3)
            if self._pending_analysis:
                contact, msgs, style, ctx = self._pending_analysis
                self._pending_analysis = None
                await self._process_analysis(contact, msgs, style, ctx)
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

    async def _live_wrapper(self):
        try:
            await self.live.run()
        except Exception as exc:
            print(f"[wingman] Voice error: {exc}")
            print("[wingman] Voice disabled — use buttons instead")

    async def run(self):
        mode = "HEADLESS" if self.headless else "DESKTOP"
        print(f"[wingman] Starting Wingman ({mode})...")

        if self.training.load():
            self.generator.set_cache(self.training.cache_name)
            print(f"[wingman] Training loaded: {self.training.file_count} files, "
                  f"{self.training.token_count:,} tokens cached")
        else:
            print("[wingman] No training data — add .txt files to training/ folder")

        if self.headless:
            print("[wingman] Ready — upload screenshots from the web UI")
            await self._command_loop()
        else:
            print("[wingman] Just talk: 'Read this chat', 'Do the chat with X', etc.")
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
