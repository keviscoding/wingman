"""Gemini Live API voice session — the brain of Wingman.

The Live model sees the screen, hears the user, reads the chat,
and calls analyze_chat with the extracted transcript + style.
"""

from __future__ import annotations

import asyncio
from typing import Callable

import pyaudio

from google import genai
from google.genai import types

from wingman.config import (
    GEMINI_API_KEY,
    LIVE_MODEL,
    LIVE_SYSTEM_INSTRUCTION,
    AUDIO_CHANNELS,
    AUDIO_CHUNK,
    AUDIO_SEND_RATE,
)

ANALYZE_CHAT_DECL = {
    "name": "analyze_chat",
    "description": (
        "Submit the extracted chat conversation for reply generation. "
        "Called after reading the chat from the screen."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contact_name": {
                "type": "string",
                "description": "Name of the person/group this chat is with (from the chat header)",
            },
            "messages": {
                "type": "array",
                "description": "Chat messages in order, each with speaker, text, and optional reply_to",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {
                            "type": "string",
                            "description": "'me' for sent, 'them' for received",
                        },
                        "text": {
                            "type": "string",
                            "description": "The message text",
                        },
                        "reply_to": {
                            "type": "string",
                            "description": "If this message is a reply to another message, the text of the quoted/replied message. Empty if not a reply.",
                        },
                    },
                    "required": ["speaker", "text"],
                },
            },
            "style": {
                "type": "string",
                "description": "Reply style: balanced, playful, flirty, warm, direct, funny, confident, short",
            },
            "context": {
                "type": "string",
                "description": "Extra context or instructions from the user about this chat",
            },
        },
        "required": ["messages", "style"],
    },
}


class LiveSession:
    def __init__(
        self,
        on_analyze_chat: Callable[[str, list[dict], str, str], None] | None = None,
    ):
        self._on_analyze_chat = on_analyze_chat
        self._client: genai.Client | None = None
        self._out_queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._session = None
        self._running = False
        self._pya: pyaudio.PyAudio | None = None
        self.mic_muted = False

    def stop(self):
        self._running = False

    async def send_frame(self, jpeg_bytes: bytes):
        payload = {"_is_video": True, "data": jpeg_bytes}
        try:
            self._out_queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._out_queue.get_nowait()
            self._out_queue.put_nowait(payload)

    async def run(self):
        tools = [{"function_declarations": [ANALYZE_CHAT_DECL]}]

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(
                parts=[types.Part(text=LIVE_SYSTEM_INSTRUCTION)]
            ),
            tools=tools,
        )

        self._running = True
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        self._client = genai.Client(api_key=GEMINI_API_KEY)

        async with (
            self._client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
            asyncio.TaskGroup() as tg,
        ):
            self._session = session
            self._out_queue = asyncio.Queue(maxsize=10)

            tg.create_task(self._listen_mic())
            tg.create_task(self._send_realtime())
            tg.create_task(self._receive())

    async def _listen_mic(self):
        try:
            self._pya = pyaudio.PyAudio()
            mic_info = self._pya.get_default_input_device_info()
            stream = await asyncio.to_thread(
                self._pya.open,
                format=pyaudio.paInt16, channels=AUDIO_CHANNELS,
                rate=AUDIO_SEND_RATE, input=True,
                input_device_index=int(mic_info["index"]),
                frames_per_buffer=AUDIO_CHUNK,
            )
        except Exception as exc:
            print(f"[live] Microphone unavailable: {exc}")
            while self._running:
                await asyncio.sleep(1)
            return

        print("[live] Microphone warming up (3s)...")
        await asyncio.sleep(3)
        print("[live] Microphone active — speak to Wingman")

        try:
            while self._running:
                data = await asyncio.to_thread(
                    stream.read, AUDIO_CHUNK, exception_on_overflow=False,
                )
                if self.mic_muted:
                    continue
                payload = {"data": data, "mime_type": "audio/pcm"}
                try:
                    self._out_queue.put_nowait(payload)
                except asyncio.QueueFull:
                    self._out_queue.get_nowait()
                    self._out_queue.put_nowait(payload)
        except asyncio.CancelledError:
            pass
        finally:
            stream.stop_stream()
            stream.close()
            self._pya.terminate()

    async def _send_realtime(self):
        try:
            while self._running:
                msg = await self._out_queue.get()
                try:
                    if msg.get("_is_video"):
                        blob = types.Blob(data=msg["data"], mime_type="image/jpeg")
                        await self._session.send_realtime_input(video=blob)
                    else:
                        await self._session.send_realtime_input(audio=msg)
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    async def _receive(self):
        try:
            while self._running:
                turn = self._session.receive()
                async for resp in turn:
                    if resp.data:
                        continue  # discard audio output
                    if resp.tool_call:
                        await self._handle_tool_calls(resp.tool_call)
                        continue
                    if text := resp.text:
                        print(f"[live] {text}")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"[live] Receive error: {exc}")

    async def _handle_tool_calls(self, tool_call):
        responses = []
        for fc in tool_call.function_calls:
            if fc.name == "analyze_chat":
                contact = fc.args.get("contact_name", "Unknown")
                messages = fc.args.get("messages", [])
                style = fc.args.get("style", "balanced")
                context = fc.args.get("context", "")
                print(f"[live] analyze_chat: {contact}, {len(messages)} msgs, style={style}")
                if context:
                    print(f"[live] context: {context}")
                if self._on_analyze_chat:
                    self._on_analyze_chat(contact, messages, style, context)
                responses.append(types.FunctionResponse(
                    id=fc.id, name=fc.name,
                    response={"result": f"Processing {len(messages)} messages"},
                ))
            else:
                responses.append(types.FunctionResponse(
                    id=fc.id, name=fc.name, response={"result": "unknown tool"},
                ))
        await self._session.send_tool_response(function_responses=responses)
