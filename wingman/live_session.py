"""Gemini Flash Live voice session.

Flash Live sees the screen and hears the user. It handles voice commands
("read this", "done") and speaks back confirmations. The actual message
extraction from frames is handled separately by ChatReader.
"""

from __future__ import annotations

import asyncio
from typing import Callable

# pyaudio needs PortAudio at runtime — desktop-only. Guarded so the
# module imports cleanly on the headless server.
try:
    import pyaudio  # type: ignore
except Exception:  # pragma: no cover
    pyaudio = None  # type: ignore

from google import genai
from google.genai import types

from wingman.config import (
    LIVE_MODEL,
    AUDIO_CHANNELS,
    AUDIO_CHUNK,
    AUDIO_SEND_RATE,
    make_genai_client,
)

VOICE_COMMAND_DECL = {
    "name": "wingman_command",
    "description": (
        "Call this when the user gives a voice command. "
        "Supported commands: 'start_reading' (user wants to read a chat), "
        "'done' (user finished scrolling, generate replies now)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "'start_reading' or 'done'",
            },
            "contact_name": {
                "type": "string",
                "description": "Name from the chat header on screen (only needed for start_reading)",
            },
            "context": {
                "type": "string",
                "description": "Any extra context the user mentioned verbally, e.g. 'she's been cold lately'. Empty if none.",
            },
        },
        "required": ["command"],
    },
}

LIVE_INSTRUCTION = (
    "You are a wingman assistant. You can see the user's screen and hear them.\n\n"
    "Your ONLY job is to listen for two voice commands:\n\n"
    "1. START READING: When the user says 'read this', 'grab this', 'do this chat', "
    "'read this one', 'this chat', etc. — call wingman_command with command='start_reading'. "
    "Look at the screen to get the contact_name from the chat header. "
    "Say 'Reading — scroll when ready' BRIEFLY.\n\n"
    "2. DONE: When the user says 'done', 'that's it', 'go', 'finish', 'ok do it', "
    "'analyze', 'generate', etc. — call wingman_command with command='done'. "
    "Say 'Got it' BRIEFLY.\n\n"
    "If the user gives extra context while scrolling (e.g. 'she's been cold lately', "
    "'we met at a party'), include it in the 'context' field.\n\n"
    "RULES:\n"
    "- Keep ALL spoken responses to 2-4 words max.\n"
    "- Do NOT try to read or extract chat messages yourself.\n"
    "- Do NOT give advice or analysis — just acknowledge commands.\n"
    "- Ignore background noise, clicks, silence.\n"
    "- Only respond to clear voice commands from the user."
)


class LiveSession:
    def __init__(
        self,
        on_command: Callable[[str, str, str], None] | None = None,
    ):
        self._on_command = on_command
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
        tools = [{"function_declarations": [VOICE_COMMAND_DECL]}]

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(
                parts=[types.Part(text=LIVE_INSTRUCTION)]
            ),
            tools=tools,
        )

        self._running = True
        self._client = make_genai_client()

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
        print("[live] Microphone active — say 'read this' while looking at a chat")

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
                        continue
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
            if fc.name == "wingman_command":
                command = fc.args.get("command", "")
                contact = fc.args.get("contact_name", "")
                context = fc.args.get("context", "")
                print(f"[live] command: {command}, contact: {contact}")
                if context:
                    print(f"[live]   context: {context}")
                if self._on_command:
                    self._on_command(command, contact, context)
                responses.append(types.FunctionResponse(
                    id=fc.id, name=fc.name,
                    response={"result": f"Command '{command}' received."},
                ))
            else:
                responses.append(types.FunctionResponse(
                    id=fc.id, name=fc.name, response={"result": "unknown tool"},
                ))
        await self._session.send_tool_response(function_responses=responses)
