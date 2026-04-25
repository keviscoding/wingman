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
import uuid

from wingman.transcript import ConversationState
from wingman.reply_generator import ReplyGenerator
from wingman.chat_store import ChatStore
from wingman.training import TrainingCache
from wingman.training_rag import TrainingRAG
from wingman.conversation_summary import summarize_if_needed
from wingman.presets import PresetStore
from wingman.chat_reader import ChatReader
from wingman.rapid_fire import RapidFireSession
from wingman.case_studies import (
    CaseStudyStore,
    build_case_study,
    retrieve_case_studies_for_live_chat,
)
from wingman.examples_library import (
    ExampleStore,
    retrieve_examples_for_live_chat,
)
from wingman.training_corpus import TrainingCorpus

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
        from wingman.config import PRO_MODEL, FLASH_MODEL
        self.training = TrainingCache(model=PRO_MODEL, label="pro")
        self.training_flash = TrainingCache(model=FLASH_MODEL, label="flash")
        self.training_rag = TrainingRAG()
        self.presets = PresetStore()
        from wingman.global_settings import GlobalSettings
        self.global_settings = GlobalSettings()
        self.active_preset: int = -1
        self.default_preset: int = -1
        self.reply_model: str = "pro"
        self.use_training: bool = True
        # When True and reply_model == "pro", route Pro generations through
        # KIE (https://kie.ai). Flash always stays direct. Off by default.
        self.use_kie: bool = False
        # When True and reply_model == "pro", route Pro generations through
        # xAI Grok 4.20 instead of Google. ``grok_mode`` picks which
        # Grok flavor: "multi-agent" (Lucas + team, default — best
        # creative quality), "reasoning" (single-agent, faster), or
        # "non-reasoning" (fastest). Off by default; user toggles
        # via UI for A/B quality comparison.
        self.use_grok: bool = False
        self.grok_mode: str = os.getenv("GROK_MODE", "multi-agent").strip() or "multi-agent"
        # DeepSeek V4 Pro via Atlas Cloud — optional alternative to Pro.
        # Two modes: "normal" (playbook + chat, same as Pro) or "full"
        # (full 620k-token training corpus as stable cached prefix).
        self.use_deepseek: bool = False
        self.deepseek_mode: str = (os.getenv("DEEPSEEK_MODE", "normal").strip().lower()
                                     or "normal")
        # Variant: "pro" (stronger reasoning) vs "flash" (faster). Both
        # accept the same payload shape; only the model-id changes.
        self.deepseek_variant: str = (os.getenv("DEEPSEEK_VARIANT", "pro").strip().lower()
                                        or "pro")
        # When True AND use_grok is on, inject the FULL 121-transcript
        # training corpus (~610k tokens) into every reply generation's
        # system instruction. First Grok call pays $1.22 uncached; every
        # call after that hits xAI's prompt cache at $0.12 (10x cheaper)
        # thanks to the stable prompt_cache_key. Massive quality uplift
        # over the 9k-char Master Playbook alone. Default ON because
        # Grok's whole point over Gemini is the 2M context + cache.
        default_full = os.getenv("GROK_FULL_TRAINING", "1").strip().lower() in ("1", "true", "yes", "on")
        self.grok_full_training: bool = default_full
        self.training_corpus = TrainingCorpus()
        # Case Study Library — learned lessons from chats the user
        # flagged as bad outcomes. Injected into the system instruction
        # when ``use_lessons`` is on and retrieval finds similar cases.
        # Toggle is ON by default; no retrieval cost when the store is
        # empty so zero overhead until the first chat is flagged.
        self.case_studies = CaseStudyStore()
        self.use_lessons: bool = True
        # Tracks which bad-outcome builds are in flight so the UI can
        # show a "analyzing..." state and so we don't double-build.
        self._building_case_studies: set[str] = set()
        # Good-reply examples library — auto-bootstrapped from all
        # non-flagged chats. Complements case_studies (bad examples)
        # with concrete positive style anchors retrieved per-call.
        # Toggle ON by default once the library has entries.
        self.examples_library = ExampleStore()
        self.use_examples: bool = True

        if headless:
            self.capture = _DummyCapture()
            self.live = _DummyLive()
            print("[wingman] Running in HEADLESS mode (no screen capture / mic)")
        else:
            from wingman.capture import CaptureRegion, ScreenCapture
            self.capture = ScreenCapture(region=capture_region)
            # Voice ('read this' / 'done' hotwords) is OFF by default —
            # Flash Live mis-hearing background audio as a command would
            # randomly flip the app into 'collecting' mode. Re-enable by
            # setting WINGMAN_VOICE=on in .env when you actually want
            # hands-free voice control.
            voice_on = os.getenv("WINGMAN_VOICE", "off").lower() in ("1", "on", "true", "yes")
            if voice_on:
                from wingman.live_session import LiveSession
                self.live = LiveSession(on_command=self._on_voice_command)
                print("[wingman] Voice commands: ENABLED (WINGMAN_VOICE=on)")
            else:
                self.live = _DummyLive()
                print("[wingman] Voice commands: disabled (set WINGMAN_VOICE=on to enable)")

        self.latest_replies: list[dict] = []
        self.latest_read: str = ""
        self.latest_advice: str = ""
        self.latest_frame_b64: str = ""
        self.latest_screenshots: list[bytes] = []
        self.current_contact: str = ""
        self.saved_contacts: list[str] = self.store.list_contacts()
        self.status: str = "idle"
        self.collecting_count: int = 0
        self.status_version: int = 0
        self.transcript_version: int = 0
        self.replies_version: int = 0
        self.server_session_id: str = str(uuid.uuid4())

        self._pending_regen: int | None = None
        self._regen_extra_context: str = ""
        self._frame_collecting: bool = False
        self._collecting_context: str = ""
        self._pending_done: bool = False
        self.on_reply_chunk = None
        self.unread_replies: set[str] = set()
        self._reply_history: list[dict] = []
        self._reply_history_index: int = 0
        self.rapid_fire = RapidFireSession()
        self._generating_for_contact: str = ""

        from wingman.hotkey import HotkeyListener
        self.hotkey = HotkeyListener(self)

    def _bump(self):
        self.status_version += 1

    async def _on_reply_chunk(self, accumulated_text: str):
        """Called by ReplyGenerator as tokens stream in; forwards to server broadcast."""
        if self.on_reply_chunk:
            await self.on_reply_chunk(accumulated_text, self._generating_for_contact)
        else:
            print("[wingman] WARNING: on_reply_chunk not set, chunks not being broadcast")

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
        """Grab screen frames. Always update preview; read when collecting or rapid fire."""
        print("[wingman] Screen capture started")
        import mss, asyncio as _aio
        from wingman.capture import Frame
        sct = mss.mss()
        monitor = self.capture._build_monitor(sct)
        while True:
            frame = await asyncio.to_thread(self.capture._grab_frame, sct, monitor)
            self.latest_frame_b64 = frame.jpeg_b64

            if self.rapid_fire.is_active:
                asyncio.create_task(self.rapid_fire.process_frame(frame.jpeg_bytes))
                await asyncio.sleep(1.0)
                continue

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
                    self.latest_screenshots = [jpeg_bytes]
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

        # ── SNAPSHOT everything that can change mid-flight ───────────────
        # ``_generate_replies`` has several ``await`` points. During those,
        # a websocket handler can call ``self.load_contact(other)`` which
        # clears + refills ``self.conversation.messages`` IN PLACE. Without
        # snapshots, the summarizer / time_context / meta-lookup would read
        # the SWITCHED chat's data, producing replies for chat B that get
        # saved under chat A's name. Copy into locals up-front so the
        # whole call runs on a coherent snapshot.
        _gen_for_contact = self.current_contact
        self._generating_for_contact = _gen_for_contact
        _gen_messages = list(self.conversation.messages)
        _gen_screenshots = list(self.latest_screenshots[:3])
        _had_new_context = self.conversation.new_since_last_generation > 0
        # Build a detached ConversationState for time_context so that
        # swapping the live conversation doesn't poison our reading.
        from wingman.transcript import ConversationState as _Conv
        _gen_conv_view = _Conv()
        _gen_conv_view.messages = _gen_messages

        idx = preset_idx if preset_idx is not None else self.active_preset
        preset_goal = self.presets.get(idx) if idx >= 0 else ""
        goal = preset_goal or context or ""

        # Sticky extra-context layers, always merged with any one-shot
        # context the user typed for this call:
        #   • global_extra_context — user-locked across ALL chats
        #   • locked_extra_context — this chat's own sticky lock
        #   • context (one-shot)   — typed just now
        # Joined with blank lines so Pro sees them as distinct directives.
        _global_ctx = ""
        try:
            _global_ctx = (self.global_settings.global_extra_context or "").strip()
        except Exception:
            _global_ctx = ""
        _locked_ctx = ""
        if _gen_for_contact:
            try:
                _locked_ctx = (self.store.load_meta(_gen_for_contact).get("locked_extra_context") or "").strip()
            except Exception:
                _locked_ctx = ""
        _one_shot = (context or "").strip()
        _pieces = [p for p in (_global_ctx, _locked_ctx, _one_shot) if p]
        context = "\n\n".join(_pieces)

        if goal:
            print(f"[wingman] Generating replies for {_gen_for_contact} (goal: {goal[:60]})...")
        else:
            print(f"[wingman] Generating replies for {_gen_for_contact} (default)...")
        if _global_ctx:
            print(f"[wingman]   + global context: {_global_ctx[:80]}...")
        if _locked_ctx:
            print(f"[wingman]   + locked context: {_locked_ctx[:80]}...")

        msg_count = len(_gen_messages)
        summary, recent_json = await asyncio.to_thread(
            summarize_if_needed, _gen_messages, _gen_for_contact or "unknown",
        )
        if summary:
            import json as _json
            recent_count = len(_json.loads(recent_json))
            summarized_count = msg_count - recent_count
            transcript_json = f"[CONVERSATION SUMMARY ({summarized_count} older messages)]\n{summary}\n\n[RECENT MESSAGES ({recent_count} messages)]\n{recent_json}"
            print(f"[wingman] {summarized_count} summarized + {recent_count} recent ({len(summary)} + {len(recent_json)} chars)")
        else:
            transcript_json = recent_json
            print(f"[wingman] Full transcript: {msg_count} messages ({len(recent_json)} chars)")

        use_flash = self.reply_model == "flash"
        use_tuned = self.reply_model == "tuned"
        tag = "Tuned" if use_tuned else ("Flash" if use_flash else "Pro")

        knowledge_summary = ""
        if self.use_training and self.training_rag.status == "loaded":
            knowledge_summary = self.training_rag.knowledge_summary
            train_tag = "+training"
        else:
            train_tag = ""

        # Examples Library retrieval — positive counterpart to case
        # studies. Pulls 3-4 of the user's own past replies from
        # similar situations as few-shot style anchors. Zero cost when
        # library empty. Embed call + cosine scan — fast.
        examples_block = ""
        ex_tag = ""
        applied_examples: list[dict] = []
        if (
            getattr(self, "use_examples", True)
            and not self.examples_library.is_empty
        ):
            try:
                ex_hits, examples_block = await retrieve_examples_for_live_chat(
                    self.examples_library,
                    _gen_messages,
                    exclude_contact=_gen_for_contact or "",
                    top_k=4,
                    min_similarity=0.60,
                )
                if ex_hits:
                    applied_examples = [
                        {
                            "contact": e.contact,
                            "similarity": round(float(s), 3),
                            "reply": e.reply,
                        }
                        for s, e in ex_hits
                    ]
                    top = ex_hits[0][0]
                    ex_tag = f" +examples({len(ex_hits)}:{top:.2f})"
                    print(f"[wingman] Examples retrieved: "
                          f"{', '.join(e.contact for _, e in ex_hits)} "
                          f"(top sim {top:.2f})")
                else:
                    print("[wingman] Examples: no similar past situations above threshold")
            except Exception as exc:
                import traceback
                print(f"[wingman] Examples retrieval failed (non-fatal): {exc}")
                traceback.print_exc()

        # Case Study Library retrieval. Runs once per generation (single
        # embed call + cosine scan over N flagged chats — N is tiny in
        # practice). Off-switch: use_lessons toggle for A/B testing.
        # Empty store = no API call, no latency.
        case_studies_block = ""
        cs_lesson_tag = ""
        applied_case_studies: list[dict] = []
        if (
            getattr(self, "use_lessons", True)
            and not self.case_studies.is_empty()
        ):
            try:
                hits, case_studies_block = await retrieve_case_studies_for_live_chat(
                    self.case_studies,
                    _gen_messages,
                    exclude_contact=_gen_for_contact or "",
                    top_k=3,
                    min_similarity=0.55,
                )
                if hits:
                    applied_case_studies = [
                        {"contact": entry.contact, "similarity": round(float(sim), 3)}
                        for sim, entry in hits
                    ]
                    names = ", ".join(e.contact for _, e in hits)
                    top = hits[0][0]
                    cs_lesson_tag = f" +lessons({len(hits)}:{top:.2f})"
                    print(f"[wingman] Case studies retrieved: {names} (top sim {top:.2f})")
                else:
                    print("[wingman] Case studies: no similar past bad chats")
            except Exception as exc:
                import traceback
                print(f"[wingman] Case study retrieval failed (non-fatal): {exc}")
                traceback.print_exc()

        time_ctx = _gen_conv_view.time_context()
        receptiveness = 5
        if _gen_for_contact:
            meta = self.store.load_meta(_gen_for_contact)
            receptiveness = meta.get("receptiveness", 5)

        screenshots = _gen_screenshots
        if screenshots:
            print(f"[wingman] Including {len(screenshots)} screenshot(s) for visual context")

        use_deepseek = bool(getattr(self, "use_deepseek", False)) and not use_flash
        deepseek_tag = ""
        deepseek_corpus_text = ""
        if use_deepseek:
            ds_mode = getattr(self, "deepseek_mode", "normal")
            ds_variant = getattr(self, "deepseek_variant", "pro")
            if ds_mode == "full" and not self.training_corpus.is_empty:
                deepseek_corpus_text = self.training_corpus.text
                deepseek_tag = f" +ds[{ds_variant},full:{self.training_corpus.char_count//1000}kc]"
            else:
                deepseek_tag = f" +ds[{ds_variant},{ds_mode}]"

        use_grok = bool(getattr(self, "use_grok", False)) and not use_flash
        grok_tag = ""
        grok_corpus_text = ""
        if use_grok:
            grok_mode = getattr(self, "grok_mode", "multi-agent")
            # Full-training mode: only include the 610k-token corpus when
            # the toggle is on AND we actually have files loaded. Cache
            # does the heavy lifting so this is cheap after call #1.
            if getattr(self, "grok_full_training", False) and not self.training_corpus.is_empty:
                grok_corpus_text = self.training_corpus.text
                grok_tag = f" +grok[{grok_mode},FULL:{self.training_corpus.char_count//1000}kc]"
            else:
                grok_tag = f" +grok[{grok_mode}]"
        # User-customized baseline prompt (edited via the UI gear).
        # Empty = use the hardcoded REPLY_SYSTEM_PROMPT from config.py.
        # Non-empty = override everywhere (Regenerate, hotkey, safe retry).
        custom_sys_prompt = ""
        try:
            custom_sys_prompt = (self.global_settings.custom_reply_system_prompt or "").strip()
        except Exception:
            custom_sys_prompt = ""
        if custom_sys_prompt:
            print(f"[wingman] Using CUSTOM baseline prompt ({len(custom_sys_prompt)} chars)")

        print(f"[wingman] Using {tag}{train_tag}{cs_lesson_tag}{ex_tag}{grok_tag}{deepseek_tag} for reply generation (streaming)")
        result = await self.generator.generate_stream(
            transcript_json, extra_context=context, goal=goal,
            use_flash=use_flash, on_chunk=self._on_reply_chunk,
            use_training=False, rag_context="",
            knowledge_summary=knowledge_summary,
            case_studies_block=case_studies_block,
            examples_block=examples_block,
            time_context=time_ctx, receptiveness=receptiveness,
            image_parts=screenshots,
            use_kie=getattr(self, "use_kie", False),
            use_grok=use_grok,
            grok_mode=getattr(self, "grok_mode", "multi-agent"),
            grok_full_corpus=grok_corpus_text,
            use_deepseek=use_deepseek,
            deepseek_mode=getattr(self, "deepseek_mode", "normal"),
            deepseek_full_corpus=deepseek_corpus_text,
            deepseek_variant=getattr(self, "deepseek_variant", "pro"),
            use_tuned=use_tuned,
            # Tuned model needs raw messages + goal/context in its own
            # training-shape prompt (it was trained on a specific
            # format, not our 13k-char system-prompt + JSON request).
            tuned_messages=_gen_messages if use_tuned else None,
            tuned_goal=goal if use_tuned else "",
            tuned_extra_context=context if use_tuned else "",
            system_prompt_override=custom_sys_prompt or None,
        )
        if result.skipped_duplicate:
            print("[wingman] Skipping duplicate reply generation (already in progress)")
            return
        had_new_context = _had_new_context
        # Only reset the live conversation's counter if we're STILL on the
        # same chat we generated for — otherwise we'd zero out a different
        # chat's 'new since last gen' counter.
        if _gen_for_contact == self.current_contact:
            self.conversation.mark_generation_done()

        # Save replies to the contact we started generating for, not the current one
        reply_dicts = [o.to_dict() for o in result.replies]

        # Only overwrite + bump version when we actually GOT new replies.
        # Otherwise (safety block, parse failure, rate limit) we'd wipe the
        # user's existing visible replies with an empty list and the UI
        # would go blank — making a failed regen look like "it cancelled".
        # On empty results we leave the previous replies intact and let
        # the server log / retry fallbacks explain what happened.
        if reply_dicts and _gen_for_contact == self.current_contact:
            self.latest_replies = reply_dicts
            self.latest_read = result.read
            self.latest_advice = result.advice
            self.replies_version += 1

        if result.replies and _gen_for_contact:
            import time as _time
            meta = self.store.load_meta(_gen_for_contact)
            meta["last_replies"] = reply_dicts
            meta["last_read"] = result.read
            meta["last_advice"] = result.advice
            meta["last_generated_at"] = _time.time()

            lessons_applied = bool(case_studies_block)
            examples_applied = bool(examples_block)
            entry = {
                "replies": reply_dicts,
                "read": result.read,
                "advice": result.advice,
                "mode": "lessons_on" if lessons_applied else "lessons_off",
                "lessons_applied": lessons_applied,
                "applied_case_studies": applied_case_studies,
                "examples_applied": examples_applied,
                "applied_examples": applied_examples,
            }
            history = meta.get("reply_history", [])
            if had_new_context:
                history = [entry]
            else:
                history.append(entry)
                if len(history) > 5:
                    history = history[-5:]
            meta["reply_history"] = history
            meta["reply_history_index"] = len(history) - 1

            self.store.save_meta(_gen_for_contact, meta)
            if _gen_for_contact == self.current_contact:
                self._reply_history = history
                self._reply_history_index = len(history) - 1

        if result.replies:
            print(f"[wingman] Got {len(result.replies)} reply options:")
            for opt in result.replies:
                why = f" — {opt.why}" if opt.why else ""
                print(f"  [{opt.label}] {opt.text[:60]}{why}")
        if result.read:
            print(f"[wingman] Read: {result.read[:120]}")
        if result.advice:
            print(f"[wingman] Advice: {result.advice[:120]}")

        if _gen_for_contact and _gen_for_contact != self.current_contact and result.replies:
            self.unread_replies.add(_gen_for_contact)
            print(f"[wingman] Replies queued for {_gen_for_contact} (switched away)")

        # Native macOS notification on completion.
        #   WINGMAN_NOTIFY=always      -> every generation
        #   WINGMAN_NOTIFY=background  -> only when we drifted off that chat (default)
        #   WINGMAN_NOTIFY=never       -> disabled (also honoured inside notify.notify)
        if result.replies:
            mode = os.getenv("WINGMAN_NOTIFY", "background")
            is_background = bool(_gen_for_contact) and _gen_for_contact != self.current_contact
            if mode == "always" or (mode == "background" and is_background):
                try:
                    from wingman.notify import notify as _notify
                    import urllib.parse as _ul
                    first = reply_dicts[0] if reply_dicts else {}
                    body = first.get("text", "")[:140]
                    # Clicking the banner opens the chat directly via URL hash.
                    port = os.getenv("WINGMAN_PORT", "8000")
                    deep = (
                        f"http://127.0.0.1:{port}/#contact="
                        f"{_ul.quote(_gen_for_contact or '', safe='')}"
                        if _gen_for_contact else ""
                    )
                    _notify(
                        title=_gen_for_contact or "Wingman",
                        body=body or "Replies ready",
                        subtitle="Click to open",
                        open_url=deep,
                    )
                except Exception:
                    pass

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
        self.latest_screenshots = [data for data, mime in media_items if mime.startswith("image/")]
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

    def clear_unread(self, contact: str):
        self.unread_replies.discard(contact)
        self._bump()

    # ── Case Study Library ───────────────────────────────────────────

    async def _build_case_study_for(self, contact: str):
        """Background task: run Flash post-mortem + embed + persist."""
        if not contact:
            return
        if contact in self._building_case_studies:
            return
        self._building_case_studies.add(contact)
        try:
            self._bump()  # surface "analyzing" state to the UI
            messages = self.store.load(contact)
            if not messages:
                print(f"[wingman] Can't build case study for {contact}: "
                      f"no messages on disk")
                return
            note = ""
            meta = self.store.load_meta(contact)
            bad = meta.get("bad_outcome") or {}
            if isinstance(bad, dict):
                note = bad.get("note", "") or ""
            record = await build_case_study(contact, messages, note=note)
            if not record:
                print(f"[wingman] Case study build returned nothing for {contact}")
                return
            await asyncio.to_thread(self.case_studies.save_entry, contact, record)
            # Reflect in chat meta so sidebar badges can show "analyzed".
            m2 = self.store.load_meta(contact)
            b2 = m2.get("bad_outcome") or {}
            if isinstance(b2, dict):
                b2["built_at"] = record.get("built_at")
                m2["bad_outcome"] = b2
                self.store.save_meta(contact, m2)
            print(f"[wingman] Case study ready for {contact}")
        except Exception as exc:
            print(f"[wingman] Case study build failed for {contact}: {exc}")
        finally:
            self._building_case_studies.discard(contact)
            self._bump()

    def flag_bad_outcome(self, contact: str, note: str = ""):
        """Mark a chat as a bad outcome and kick off the post-mortem build."""
        if not contact:
            return
        import time as _time
        meta = self.store.load_meta(contact)
        meta["bad_outcome"] = {"flagged_at": _time.time(), "note": note or ""}
        self.store.save_meta(contact, meta)
        print(f"[wingman] Flagged {contact} as bad outcome (note: {note[:60] if note else 'none'})")
        self._bump()
        try:
            asyncio.create_task(self._build_case_study_for(contact))
        except RuntimeError:
            # Called from outside an event loop (rare). Caller can
            # invoke _build_case_study_for(contact) manually.
            print("[wingman] No running loop — case study build skipped")

    # ── Examples Library ─────────────────────────────────────────────

    async def _bootstrap_examples_background(self):
        """Kick off bootstrap as background task. Chat flags that are
        already loaded into case_studies are excluded automatically."""
        try:
            self._bump()  # surface "building..." to UI
            count = await self.examples_library.bootstrap_from_chats(
                self.store,
                case_studies_store=self.case_studies,
                force=False,
            )
            print(f"[wingman] Examples library bootstrap done: {count} pairs")
        except Exception as exc:
            print(f"[wingman] Examples bootstrap failed: {exc}")
        finally:
            self._bump()

    def rebuild_examples_library(self):
        """WS action wrapper — user requested rebuild."""
        if self.examples_library.is_building:
            print("[wingman] Examples build already in progress — ignored")
            return
        try:
            asyncio.create_task(self._bootstrap_examples_background_force())
        except RuntimeError:
            print("[wingman] No running loop — rebuild skipped")

    async def _bootstrap_examples_background_force(self):
        """Same as bootstrap but with force=True so hash check is
        bypassed — user explicitly asked for a full rebuild."""
        try:
            self._bump()
            count = await self.examples_library.bootstrap_from_chats(
                self.store,
                case_studies_store=self.case_studies,
                force=True,
            )
            print(f"[wingman] Examples library rebuilt: {count} pairs")
        except Exception as exc:
            print(f"[wingman] Examples rebuild failed: {exc}")
        finally:
            self._bump()

    def unflag_bad_outcome(self, contact: str):
        """Remove a bad-outcome flag and its case study from the index."""
        if not contact:
            return
        meta = self.store.load_meta(contact)
        if "bad_outcome" in meta:
            meta.pop("bad_outcome", None)
            self.store.save_meta(contact, meta)
        try:
            self.case_studies.delete(contact)
        except Exception as exc:
            print(f"[wingman] case_studies.delete failed: {exc}")
        print(f"[wingman] Unflagged {contact}")
        self._bump()

    def set_reply_history_index(self, index: int):
        """Switch to a different generation in the reply history."""
        if not self._reply_history:
            return
        index = max(0, min(index, len(self._reply_history) - 1))
        self._reply_history_index = index
        entry = self._reply_history[index]
        self.latest_replies = entry.get("replies", [])
        self.latest_read = entry.get("read", "")
        self.latest_advice = entry.get("advice", "")
        self.replies_version += 1
        if self.current_contact:
            meta = self.store.load_meta(self.current_contact)
            meta["reply_history_index"] = index
            meta["last_replies"] = self.latest_replies
            meta["last_read"] = self.latest_read
            meta["last_advice"] = self.latest_advice
            self.store.save_meta(self.current_contact, meta)
        self._bump()

    # ── Contact management ───────────────────────────────────────────

    def load_contact(self, contact: str):
        existing = self.store.load(contact)
        self.conversation.messages.clear()
        self.conversation.new_since_last_generation = 0
        if existing:
            self.conversation.ingest_parsed_messages(existing)
        self.current_contact = contact

        meta = self.store.load_meta(contact)
        self.latest_replies = meta.get("last_replies", [])
        self.latest_read = meta.get("last_read", "")
        self.latest_advice = meta.get("last_advice", "")
        self._reply_history = meta.get("reply_history", [])
        self._reply_history_index = meta.get("reply_history_index", max(0, len(self._reply_history) - 1))
        self.active_preset = meta.get("active_preset", self.default_preset)

        self.unread_replies.discard(contact)
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

        # RAG (fast retrieval) — always loads first, used by default
        rag_loaded = await asyncio.to_thread(self.training_rag.load)
        if rag_loaded:
            print(f"[wingman] Training RAG ready: {self.training_rag.file_count} files embedded")
        else:
            print("[wingman] No training data — add .txt files to training/ folder")

        # Case Study Library: pull any existing flagged-chat lessons from
        # disk into the in-memory index. Cheap — just JSON reads. When
        # the user hasn't flagged anything yet, this is a no-op.
        try:
            await asyncio.to_thread(self.case_studies.load)
        except Exception as exc:
            print(f"[wingman] case_studies.load failed (non-fatal): {exc}")

        # Training corpus: big concatenated string of all 121 files.
        # Loaded once into memory; used only when Grok's full-training
        # mode is on. Cheap one-time read + hash check.
        try:
            await asyncio.to_thread(self.training_corpus.load)
        except Exception as exc:
            print(f"[wingman] training_corpus.load failed (non-fatal): {exc}")

        # Good-examples library: load from disk if already built. If
        # empty (first run / fresh install), kick off a background
        # bootstrap that walks all chats and batch-embeds reply pairs.
        # Doesn't block startup — UI will show "building..." state.
        try:
            await asyncio.to_thread(self.examples_library.load)
            if self.examples_library.is_empty and self.saved_contacts:
                print("[wingman] Examples library empty — bootstrapping in background...")
                asyncio.create_task(self._bootstrap_examples_background())
            else:
                print(f"[wingman] Examples library ready: "
                      f"{self.examples_library.count} pairs")
        except Exception as exc:
            print(f"[wingman] examples_library.load failed (non-fatal): {exc}")

        # Full caches disabled — RAG provides training context much faster

        if self.headless:
            print("[wingman] Ready — upload screenshots from the web UI")
            await self._command_loop()
        else:
            print("[wingman] Ready — say 'read this' or click Start Reading")
            # Non-blocking: hotkey runs in its own daemon thread.
            try:
                self.hotkey.start()
            except Exception as exc:
                print(f"[wingman] hotkey init failed (non-fatal): {exc}")
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
