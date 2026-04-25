"""Gemini 3.1 Pro reply generation with training context cache.

Uses the cached training transcripts (if loaded) so every reply is
informed by the text game knowledge. Also includes the user's spoken
goal/intent for the specific chat.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from google import genai
from google.genai import types

from wingman.config import (
    PRO_MODEL,
    FLASH_MODEL,
    REPLY_SYSTEM_PROMPT,
    DEFAULT_STYLE,
    make_genai_client,
)


@dataclass
class ReplyOption:
    label: str
    text: str
    why: str = ""

    def to_dict(self) -> dict:
        d = {"label": self.label, "text": self.text}
        if self.why:
            d["why"] = self.why
        return d


@dataclass
class GenerationResult:
    replies: list[ReplyOption]
    read: str = ""
    advice: str = ""
    skipped_duplicate: bool = False


class ReplyGenerator:
    def __init__(self):
        self._client: genai.Client | None = None
        self._style: str = DEFAULT_STYLE
        self._generating = False
        self._cache_name: str | None = None
        self._flash_cache_name: str | None = None
        self._training_cache = None
        self._flash_training_cache = None

    def set_cache(self, cache_name: str | None, training_cache=None):
        self._cache_name = cache_name
        if training_cache is not None:
            self._training_cache = training_cache

    def set_flash_cache(self, cache_name: str | None, training_cache=None):
        self._flash_cache_name = cache_name
        if training_cache is not None:
            self._flash_training_cache = training_cache

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = make_genai_client()
        return self._client

    @property
    def style(self) -> str:
        return self._style

    @style.setter
    def style(self, value: str):
        self._style = value or DEFAULT_STYLE

    @property
    def is_busy(self) -> bool:
        return self._generating

    def _build_prompt_and_config(self, transcript_json: str, extra_context: str, goal: str,
                                  use_flash: bool = False, use_training: bool = True,
                                  rag_context: str = "", knowledge_summary: str = "",
                                  case_studies_block: str = "",
                                  examples_block: str = "",
                                  time_context: str = "", receptiveness: int = 5,
                                  image_parts: list[bytes] | None = None,
                                  system_prompt_override: str | None = None,
                                  system_prompt_extra: str = "",
                                  drop_images: bool = False):

        # System instruction: coaching persona + knowledge (override lets
        # callers swap in a safer-framed prompt on retry for gateway-blocked
        # chats without duplicating all the rest of the setup).
        base_sys_prompt = system_prompt_override or REPLY_SYSTEM_PROMPT
        system_parts = [base_sys_prompt.split("Conversation:\n{transcript}")[0].rstrip()]
        if system_prompt_extra:
            system_parts.append(system_prompt_extra)
        if knowledge_summary:
            system_parts.append(knowledge_summary)
        # Examples (positive style anchors) go BEFORE case studies
        # (negative warnings) so the model first sees "here's what good
        # looks like" then the "watch out for these failures" layer.
        if examples_block:
            system_parts.append(examples_block)
        if case_studies_block:
            system_parts.append(case_studies_block)
        system_instruction = "\n\n".join(system_parts)

        # User message: the actual conversation + situational context
        user_parts = []
        if time_context:
            user_parts.append(time_context)
        if receptiveness != 5:
            r = receptiveness
            if r <= 2:
                desc = "very hard to get / cold personality — needs slow investment building, banter, frame control. Do NOT escalate or go direct."
            elif r <= 4:
                desc = "somewhat guarded — build rapport and investment first, light teasing, no rushing."
            elif r <= 6:
                desc = "neutral / moderate interest — standard game, read her energy and match it."
            elif r <= 8:
                desc = "clearly interested / warm — she's investing. Push-pull, escalate, go for the close."
            else:
                desc = "very receptive / DTF — she's clearly down. Be direct, escalate confidently, close fast."
            user_parts.append(f"Her receptiveness level: {r}/10 — {desc}")
        user_parts.append(f"Conversation:\n{transcript_json}")
        if goal:
            user_parts.append(f"My goal for this chat: {goal}")
        if extra_context:
            user_parts.append(f"Additional context: {extra_context}")
        if rag_context:
            user_parts.append(rag_context)
        user_parts.append(
            "Format as JSON:\n"
            "{\"read\": \"...\", \"advice\": \"...\", \"replies\": ["
            "{\"label\": \"...\", \"text\": \"...\", \"why\": \"...\"}]}"
        )
        text_prompt = "\n\n".join(user_parts)

        # If screenshots are available, build multimodal contents list.
        # ``drop_images`` lets the redaction retry skip images (vision
        # classifier can re-trigger the same policy block).
        if image_parts and not drop_images:
            contents: list = [text_prompt]
            for img_bytes in image_parts[:3]:
                contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
            contents.append("The screenshots above show the actual chat. Use them for visual context (profile photos, read receipts, timestamps, UI cues).")
        else:
            contents = text_prompt

        # Gemini 3.1 Pro spends a significant chunk of output tokens on
        # internal "thinking" before emitting the JSON. When the input
        # grows (long goal + playbook + case-study lessons + screenshot),
        # the thinking tokens grow too and can exhaust a 16k budget,
        # leaving only a freeform opener and no JSON ("No JSON in
        # response" in logs). 32k gives thinking plenty of room while
        # still being well under Pro's hard ceiling.
        max_tokens = 32768 if not use_flash else 4096

        from wingman.config import permissive_safety_settings
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.9,
            max_output_tokens=max_tokens,
            safety_settings=permissive_safety_settings(),
        )

        return contents, config

    async def generate(
        self,
        transcript_json: str,
        extra_context: str = "",
        goal: str = "",
        use_flash: bool = False,
        use_training: bool = True,
        rag_context: str = "",
        knowledge_summary: str = "",
        time_context: str = "",
        receptiveness: int = 5,
        image_parts: list[bytes] | None = None,
    ) -> GenerationResult:
        if self._generating:
            return GenerationResult(replies=[], skipped_duplicate=True)

        model = FLASH_MODEL if use_flash else PRO_MODEL
        tag = "flash" if use_flash else "pro"

        self._generating = True
        try:
            contents, config = self._build_prompt_and_config(
                transcript_json, extra_context, goal, use_flash=use_flash,
                use_training=use_training, rag_context=rag_context,
                knowledge_summary=knowledge_summary, time_context=time_context,
                receptiveness=receptiveness, image_parts=image_parts,
            )

            tc = self._flash_training_cache if use_flash else self._training_cache

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    client = self._get_client()
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model,
                        contents=contents,
                        config=config,
                    )
                    return self._parse_response(response.text)

                except Exception as exc:
                    err_str = str(exc)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    is_cache_gone = "403" in err_str or "CachedContent not found" in err_str

                    if is_cache_gone and tc:
                        print(f"[{tag}] Cache expired, refreshing... (attempt {attempt+1})")
                        tc._file_hash = None
                        tc.load()
                        if use_flash:
                            self._flash_cache_name = tc.cache_name
                        else:
                            self._cache_name = tc.cache_name
                        prompt, config = self._build_prompt_and_config(
                            transcript_json, extra_context, goal, use_flash=use_flash,
                        )
                        continue

                    if is_rate_limit and attempt < max_retries - 1:
                        from wingman.config import rotate_api_key
                        rotate_api_key()
                        self._client = None
                        print(f"[{tag}] Rate limited, rotated key (attempt {attempt+1})")
                        await asyncio.sleep(2)
                        continue

                    print(f"[{tag}] Reply generation failed: {exc}")
                    return GenerationResult(replies=[])

            return GenerationResult(replies=[])
        finally:
            self._generating = False

    async def generate_stream(
        self,
        transcript_json: str,
        extra_context: str = "",
        goal: str = "",
        on_chunk=None,
        use_flash: bool = False,
        use_training: bool = True,
        rag_context: str = "",
        knowledge_summary: str = "",
        case_studies_block: str = "",
        examples_block: str = "",
        time_context: str = "",
        receptiveness: int = 5,
        image_parts: list[bytes] | None = None,
        use_kie: bool = False,
        use_grok: bool = False,
        grok_mode: str = "multi-agent",
        grok_full_corpus: str = "",
        use_deepseek: bool = False,
        deepseek_mode: str = "normal",
        deepseek_full_corpus: str = "",
        deepseek_variant: str = "pro",
        use_tuned: bool = False,
        tuned_messages=None,
        tuned_goal: str = "",
        tuned_extra_context: str = "",
        system_prompt_override: str | None = None,
    ) -> GenerationResult:
        """Stream reply generation using the async API; calls on_chunk(accumulated_text) as tokens arrive."""
        if self._generating:
            return GenerationResult(replies=[], skipped_duplicate=True)

        model = FLASH_MODEL if use_flash else PRO_MODEL
        tag = "flash" if use_flash else "pro"

        self._generating = True
        try:
            contents, config = self._build_prompt_and_config(
                transcript_json, extra_context, goal, use_flash=use_flash,
                use_training=use_training, rag_context=rag_context,
                knowledge_summary=knowledge_summary,
                case_studies_block=case_studies_block,
                examples_block=examples_block,
                time_context=time_context,
                receptiveness=receptiveness, image_parts=image_parts,
                system_prompt_override=system_prompt_override,
            )
            # Log prompt size so "No JSON in response" truncation
            # regressions are instantly diagnosable + so you can SEE
            # that the Master Playbook ("training") is actually being
            # passed through on every model (Google, KIE, Grok). Counts
            # chars (rough 4:1 to tokens). Images aren't counted here
            # — they're fixed cost per image.
            try:
                sys_chars = len(config.system_instruction or "")
                if isinstance(contents, str):
                    user_chars = len(contents)
                else:
                    user_chars = sum(len(c) for c in contents if isinstance(c, str))
                cs_chars = len(case_studies_block or "")
                kb_chars = len(knowledge_summary or "")
                ex_chars = len(examples_block or "")
                img_count = len(image_parts) if image_parts else 0
                print(f"[{tag}] Prompt size: system={sys_chars}c "
                      f"(playbook={kb_chars}c, examples={ex_chars}c, "
                      f"lessons={cs_chars}c) "
                      f"user={user_chars}c images={img_count}")
            except Exception:
                pass
            client = self._get_client()
            accumulated = ""
            chunk_count = 0

            # Opt-in Grok 4.20 routing for Pro. Runs through xAI's API
            # with the multi-agent model by default (Lucas, Harper,
            # Benjamin + Grok collaborate for best creative quality).
            # Translates our Gemini-native prompt shape into either
            # /v1/chat/completions (single-agent) or /v1/responses
            # (multi-agent). Falls back to Google direct on any error
            # so flipping the toggle on is always safe. Flash stays
            # on Google (Grok 4.20 is Pro-tier only in our UI).
            # Tuned Flash routing — distillation target. Runs FIRST
            # so it takes priority over Grok/KIE/direct when the user
            # explicitly picks the Tuned model. Separate from use_flash
            # (which is the base Flash model). Falls back to Google
            # direct on any error so one bad deployment can't brick
            # regens entirely.
            if use_tuned and not use_flash:
                try:
                    from wingman.tuned_flash_client import (
                        generate_tuned_replies_json, is_tuned_configured,
                    )
                    if is_tuned_configured():
                        if not tuned_messages:
                            print(f"[{tag}] use_tuned=on but tuned_messages "
                                  f"not passed — falling back")
                        else:
                            print(f"[{tag}] Routing via Tuned Flash (5 parallel calls)")
                            accumulated = await generate_tuned_replies_json(
                                tuned_messages,
                                goal=tuned_goal,
                                extra_context=tuned_extra_context,
                                on_chunk=on_chunk,
                                timeout_s=30,
                            )
                            if accumulated.strip():
                                print(f"[{tag}] Tuned Flash complete: "
                                      f"{len(accumulated)} chars")
                                return self._parse_response(accumulated)
                            else:
                                print(f"[{tag}] Tuned Flash returned empty "
                                      f"— falling back to Google direct")
                    else:
                        print(f"[{tag}] use_tuned=on but tuned endpoint "
                              f"missing — falling back to Google direct")
                except Exception as tuned_exc:
                    import traceback
                    print(f"[{tag}] Tuned Flash failed ({tuned_exc}) — falling back")
                    traceback.print_exc()
                    accumulated = ""

            # DeepSeek V4 Pro routing. Runs before Grok/KIE so the
            # toggle takes priority when both are on. Normal mode uses
            # the exact same system instruction we built above (playbook
            # + case studies + examples). Full mode injects the 620k
            # training corpus as a stable cached prefix.
            if use_deepseek and not use_flash:
                try:
                    from wingman.deepseek_client import (
                        generate_deepseek_stream, is_deepseek_configured,
                    )
                    if is_deepseek_configured():
                        ds_system = config.system_instruction or ""
                        # In "full" mode, prepend the corpus (stable
                        # prefix => cache-hit after first call).
                        if deepseek_full_corpus:
                            ds_system = deepseek_full_corpus + "\n\n" + ds_system
                        if isinstance(contents, str):
                            ds_user_text = contents
                        else:
                            pieces = [c for c in contents if isinstance(c, str)]
                            ds_user_text = "\n\n".join(pieces) if pieces else ""
                        corpus_tag = (
                            f", +corpus={len(deepseek_full_corpus)//1000}kc"
                            if deepseek_full_corpus else ""
                        )
                        print(f"[{tag}] Routing via DeepSeek ({deepseek_variant}, {deepseek_mode}{corpus_tag})")
                        accumulated = await generate_deepseek_stream(
                            system_instruction=ds_system,
                            user_text=ds_user_text,
                            images=image_parts,
                            on_chunk=on_chunk,
                            # Stable cache key lets Atlas Cloud cache
                            # the big prefix across calls in full mode.
                            cache_key=("wingman-ds-full-v1"
                                       if deepseek_full_corpus else None),
                            timeout_s=180,
                            variant=deepseek_variant,
                        )
                        if accumulated.strip():
                            print(f"[{tag}] DeepSeek complete: "
                                  f"{len(accumulated)} chars")
                            return self._parse_response(accumulated)
                        else:
                            print(f"[{tag}] DeepSeek returned empty — "
                                  f"falling back to Google direct")
                    else:
                        print(f"[{tag}] use_deepseek=on but "
                              f"ATLASCLOUD_API_KEY missing — falling back")
                except Exception as ds_exc:
                    print(f"[{tag}] DeepSeek failed ({ds_exc}) — falling back to Google direct")
                    accumulated = ""

            if use_grok and not use_flash:
                try:
                    from wingman.grok_client import (
                        generate_grok_stream, is_grok_configured,
                    )
                    if is_grok_configured():
                        # Rebuild the system instruction for Grok so we
                        # can insert the full training corpus INSIDE the
                        # stable cache prefix (after the playbook, before
                        # case studies). The Gemini path above already
                        # ran on `config.system_instruction`; we don't
                        # mutate that — we just re-compose for Grok.
                        # Honor the user's custom baseline override if set.
                        base_sys_source = system_prompt_override or REPLY_SYSTEM_PROMPT
                        base_sys = base_sys_source.split(
                            "Conversation:\n{transcript}"
                        )[0].rstrip()
                        grok_sys_parts = [base_sys]
                        if knowledge_summary:
                            grok_sys_parts.append(knowledge_summary)
                        # FULL CORPUS — big one. Put it BEFORE examples
                        # and case_studies so the cache prefix stays
                        # stable across chats (variable content comes
                        # last so cache invalidation only affects the
                        # tail).
                        if grok_full_corpus:
                            grok_sys_parts.append(grok_full_corpus)
                        if examples_block:
                            grok_sys_parts.append(examples_block)
                        if case_studies_block:
                            grok_sys_parts.append(case_studies_block)
                        system_instruction = "\n\n".join(grok_sys_parts)

                        if isinstance(contents, str):
                            user_text = contents
                        else:
                            pieces = [c for c in contents if isinstance(c, str)]
                            user_text = "\n\n".join(pieces) if pieces else ""
                        corpus_tag = (
                            f", +corpus={len(grok_full_corpus)//1000}kc"
                            if grok_full_corpus else ""
                        )
                        print(f"[{tag}] Routing via Grok ({grok_mode}{corpus_tag})")
                        # Stable cache key: same across all Wingman
                        # runs so the 610k-token corpus prefix stays
                        # cached on xAI's side. Versioned so we can
                        # intentionally invalidate later if needed.
                        accumulated = await generate_grok_stream(
                            system_instruction=system_instruction,
                            user_text=user_text,
                            images=image_parts,
                            on_chunk=on_chunk,
                            mode=grok_mode,
                            cache_key="wingman-training-v1",
                            timeout_s=240,  # first call pays 610k tokens of prefix
                        )
                        if accumulated.strip():
                            print(f"[{tag}] Grok complete: {len(accumulated)} chars")
                            return self._parse_response(accumulated)
                        else:
                            print(f"[{tag}] Grok returned empty — falling back to Google direct")
                    else:
                        print(f"[{tag}] use_grok=on but XAI_API_KEY missing — falling back to Google direct")
                except Exception as grok_exc:
                    print(f"[{tag}] Grok failed ({grok_exc}) — falling back to Google direct")
                    accumulated = ""

            # Opt-in KIE routing for Pro. Translates our Gemini-native
            # prompt shape into OpenAI-compat and runs through kie.ai
            # instead of google-genai. Falls back to the Google retry
            # loop below on any KIE error. Flash always stays on Google.
            if use_kie and not use_flash:
                try:
                    from wingman.kie_client import generate_kie_stream, is_kie_configured
                    if is_kie_configured():
                        # Recover the system instruction + user text that
                        # _build_prompt_and_config just constructed.
                        system_instruction = config.system_instruction or ""
                        # contents is either a plain str (when no images)
                        # or [text_prompt, Part, Part, "screenshots above..."].
                        if isinstance(contents, str):
                            user_text = contents
                        else:
                            # First entry is the text prompt; last is the
                            # screenshots-hint string we appended.
                            pieces = [c for c in contents if isinstance(c, str)]
                            user_text = "\n\n".join(pieces) if pieces else ""
                        print(f"[{tag}] Routing via KIE (use_kie=on)")
                        accumulated = await generate_kie_stream(
                            system_instruction=system_instruction,
                            user_text=user_text,
                            images=image_parts,
                            on_chunk=on_chunk,
                            timeout_s=120,
                        )
                        print(f"[{tag}] KIE complete: {len(accumulated)} chars")
                        return self._parse_response(accumulated)
                    else:
                        print(f"[{tag}] use_kie=on but KIE_API_KEY missing — falling back to Google direct")
                except Exception as kie_exc:
                    print(f"[{tag}] KIE failed ({kie_exc}) — falling back to Google direct")
                    accumulated = ""

            # Retry loop for both 429 (rotate key) and 503 overload
            # (backoff + retry SAME key — other keys won't help a
            # Google-side model overload).
            from wingman.config import _ALL_KEYS, rotate_api_key
            max_key_attempts = max(1, len(_ALL_KEYS))
            max_overload_retries = 3
            overload_retries = 0
            succeeded = False
            last_err = None
            total_attempts = 0

            # Per-attempt timeouts. TTFT (time to first token) catches
            # DEAD keys + network hangs fast — if the first token isn't
            # back in 20s, something's wrong (bad key, billing cap that
            # silently hangs instead of 429'ing, routing issue). Kill
            # quickly and rotate to a different key. Once the stream
            # starts producing tokens, let it run until TOTAL_TIMEOUT.
            TTFT_TIMEOUT = 20      # seconds to first token
            TOTAL_TIMEOUT = 60     # seconds total (after first token starts)

            async def _consume():
                nonlocal accumulated, chunk_count
                accumulated = ""
                chunk_count = 0
                stream = await client.aio.models.generate_content_stream(
                    model=model, contents=contents, config=config,
                )
                first_token_deadline = asyncio.get_event_loop().time() + TTFT_TIMEOUT
                async for chunk in stream:
                    if chunk.text:
                        # First token check — if we're still waiting
                        # when the deadline passes, the stream iteration
                        # above will be killed by asyncio.wait_for below.
                        accumulated += chunk.text
                        chunk_count += 1
                        if on_chunk:
                            try:
                                await on_chunk(accumulated)
                            except Exception as cb_err:
                                print(f"[{tag}] chunk callback error: {cb_err}")
                    # Enforce TTFT inside the loop too, as a safety net
                    # when stream yields empty chunks (heartbeats).
                    if chunk_count == 0 and asyncio.get_event_loop().time() > first_token_deadline:
                        raise asyncio.TimeoutError(
                            f"no first token within {TTFT_TIMEOUT}s"
                        )

            while total_attempts < (max_key_attempts + max_overload_retries):
                total_attempts += 1
                try:
                    # TTFT gates the first ~20s. If we've started
                    # streaming tokens it's by definition a working key,
                    # so we give it TOTAL_TIMEOUT for the full response.
                    await asyncio.wait_for(_consume(), timeout=TOTAL_TIMEOUT)
                    succeeded = True
                    break
                except asyncio.TimeoutError:
                    # Hang = bad key (dead / capped / routed wrong).
                    # Rotate IMMEDIATELY — retrying the same key wastes
                    # another 20-60s. This was the real cause of the
                    # multi-minute regen delays when one key was dead.
                    last_err = asyncio.TimeoutError(
                        f"stream hung (ttft={TTFT_TIMEOUT}s / total={TOTAL_TIMEOUT}s)"
                    )
                    if total_attempts < max_key_attempts:
                        rotate_api_key()
                        self._client = None
                        client = self._get_client()
                        print(f"[{tag}] Stream hung — rotated to next key (attempt {total_attempts}/{max_key_attempts})")
                        continue
                    break
                except Exception as exc:
                    last_err = exc
                    err_str = str(exc)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    is_overload = "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str.lower()
                    if is_rate_limit:
                        rotate_api_key()
                        self._client = None
                        client = self._get_client()
                        print(f"[{tag}] Rate-limited, rotated key (attempt {total_attempts})")
                        await asyncio.sleep(1)
                        continue
                    if is_overload and overload_retries < max_overload_retries:
                        overload_retries += 1
                        backoff = 2 ** overload_retries  # 2s, 4s, 8s
                        print(f"[{tag}] Pro overloaded (503), retrying in {backoff}s (retry {overload_retries}/{max_overload_retries})")
                        await asyncio.sleep(backoff)
                        continue
                    # Non-retryable, or out of retries — bail to outer except.
                    raise

            if not succeeded:
                print(f"[{tag}] Stream failed after {max_key_attempts} key attempts: {last_err}")
                return GenerationResult(replies=[])

            print(f"[{tag}] Stream complete: {chunk_count} chunks, {len(accumulated)} chars")

            # Fallback for PROHIBITED_CONTENT gateway blocks (explicit chats).
            # Two escalating retry tiers, fired only when the initial
            # stream returned nothing. Normal chats never reach this.
            if not accumulated.strip():
                print(f"[{tag}] Empty stream — retrying with safe framing...")
                safe_retry_text = ""
                try:
                    from wingman.config import REPLY_SYSTEM_PROMPT_SAFE
                    safe_contents, safe_config = self._build_prompt_and_config(
                        transcript_json, extra_context, goal, use_flash=use_flash,
                        use_training=use_training, rag_context=rag_context,
                        knowledge_summary=knowledge_summary,
                        case_studies_block=case_studies_block,
                        examples_block=examples_block,
                        time_context=time_context,
                        receptiveness=receptiveness, image_parts=image_parts,
                        system_prompt_override=REPLY_SYSTEM_PROMPT_SAFE,
                    )
                    retry = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model, contents=safe_contents, config=safe_config,
                    )
                    safe_retry_text = (retry.text or "").strip()
                    if safe_retry_text:
                        accumulated = safe_retry_text
                        if on_chunk:
                            try:
                                await on_chunk(accumulated)
                            except Exception:
                                pass
                        print(f"[{tag}] Safe-framing retry produced {len(accumulated)} chars")
                    else:
                        block_reason = getattr(retry.prompt_feedback, "block_reason", None)
                        print(f"[{tag}] Safe-framing retry empty (block_reason={block_reason})")
                except Exception as exc:
                    print(f"[{tag}] Safe-framing retry failed: {exc}")

                # Tier 3: redacted retry. Replace explicit message bodies
                # with a placeholder so the gateway accepts the prompt.
                if not safe_retry_text and not accumulated.strip():
                    print(f"[{tag}] Safe retry also blocked — final retry with redacted transcript...")
                    try:
                        from wingman.config import REPLY_SYSTEM_PROMPT_SAFE
                        from wingman.content_policy import (
                            redact_transcript_block, redact_prose, REDACTION_NOTE,
                        )
                        red_transcript = redact_transcript_block(transcript_json)
                        red_goal = redact_prose(goal) if goal else goal
                        red_extra = redact_prose(extra_context) if extra_context else extra_context
                        red_time = redact_prose(time_context) if time_context else time_context

                        red_contents, red_config = self._build_prompt_and_config(
                            red_transcript, red_extra, red_goal, use_flash=use_flash,
                            use_training=use_training, rag_context=rag_context,
                            knowledge_summary=knowledge_summary,
                            case_studies_block=case_studies_block,
                            examples_block=examples_block,
                            time_context=red_time,
                            receptiveness=receptiveness, image_parts=image_parts,
                            system_prompt_override=REPLY_SYSTEM_PROMPT_SAFE,
                            system_prompt_extra=REDACTION_NOTE,
                            drop_images=True,
                        )
                        final = await asyncio.to_thread(
                            client.models.generate_content,
                            model=model, contents=red_contents, config=red_config,
                        )
                        final_text = (final.text or "").strip()
                        if final_text:
                            accumulated = final_text
                            if on_chunk:
                                try:
                                    await on_chunk(accumulated)
                                except Exception:
                                    pass
                            print(f"[{tag}] Redacted retry produced {len(accumulated)} chars")
                        else:
                            final_block = getattr(final.prompt_feedback, "block_reason", None)
                            print(f"[{tag}] Redacted retry still blocked (block_reason={final_block})")
                    except Exception as exc:
                        print(f"[{tag}] Redacted retry failed: {exc}")

            return self._parse_response(accumulated)

        except Exception as exc:
            tc = self._flash_training_cache if use_flash else self._training_cache
            print(f"[{tag}] Stream generation failed: {exc}")
            if tc and ("403" in str(exc) or "CachedContent" in str(exc)):
                print(f"[{tag}] Cache expired during stream, falling back to non-stream...")
                self._generating = False
                tc._file_hash = None
                await asyncio.to_thread(tc.load)
                if use_flash:
                    self._flash_cache_name = tc.cache_name
                else:
                    self._cache_name = tc.cache_name
                return await self.generate(transcript_json, extra_context, goal, use_flash=use_flash)
            return GenerationResult(replies=[])
        finally:
            self._generating = False

    @staticmethod
    def _parse_response(raw: str) -> GenerationResult:
        import re
        text = raw.strip()

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if fence_match:
            text = fence_match.group(1).strip()

        # Try to find JSON object in the response
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            print("[pro] No JSON in response, treating as freeform")
            return GenerationResult(replies=[], read=text, advice="")

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            print(f"[pro] Bad JSON, treating as freeform")
            return GenerationResult(replies=[], read=text, advice="")

        read = ""
        advice = ""
        replies_data = []

        if isinstance(data, dict):
            read = data.get("read", "")
            advice = data.get("advice", "")
            replies_data = data.get("replies", [])
        elif isinstance(data, list):
            replies_data = data

        replies = [
            ReplyOption(
                label=item.get("label", "option"),
                text=item["text"],
                why=item.get("why", ""),
            )
            for item in replies_data[:10]
            if isinstance(item, dict) and "text" in item
        ]

        return GenerationResult(replies=replies, read=read, advice=advice)
