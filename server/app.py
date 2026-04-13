"""FastAPI server — polls Wingman state and pushes to browser."""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from wingman.main import Wingman, HEADLESS
from wingman.config import SERVER_HOST, SERVER_PORT

STATIC_DIR = Path(__file__).parent / "static"

wingman: Wingman | None = None
ws_clients: set[WebSocket] = set()


async def broadcast(msg: dict):
    payload = json.dumps(msg)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    ws_clients -= dead


def _state() -> dict:
    w = wingman
    return {
        "status": w.status,
        "messages": len(w.conversation.messages),
        "has_replies": len(w.latest_replies) > 0,
        "contact": w.current_contact,
        "contacts": w.saved_contacts,
        "mic_muted": getattr(w.live, "mic_muted", False),
        "headless": w.headless,
        "training_status": w.training.status,
        "training_files": w.training.file_count,
        "training_tokens": w.training.token_count,
        "presets": w.presets.presets,
        "active_preset": w.active_preset,
    }


async def _poll_loop():
    last_sv, last_tv, last_rv = -1, -1, -1
    while True:
        await asyncio.sleep(0.3)
        if not wingman:
            continue
        if wingman.status_version != last_sv:
            last_sv = wingman.status_version
            await broadcast({"type": "status", **_state()})
        if wingman.transcript_version != last_tv:
            last_tv = wingman.transcript_version
            await broadcast({"type": "transcript", "messages": wingman.conversation.to_display_list()})
        if wingman.replies_version != last_rv:
            last_rv = wingman.replies_version
            await broadcast({
                "type": "replies",
                "options": wingman.latest_replies,
                "read": wingman.latest_read,
                "advice": wingman.latest_advice,
            })


@asynccontextmanager
async def lifespan(app: FastAPI):
    global wingman
    if HEADLESS:
        wingman = Wingman(headless=True)
    else:
        from wingman.capture import CaptureRegion
        wingman = Wingman(capture_region=CaptureRegion())
    tasks = [asyncio.create_task(wingman.run()), asyncio.create_task(_poll_loop())]
    yield
    wingman.capture.stop()
    wingman.live.stop()
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/state")
async def api_state():
    if not wingman:
        return {}
    return {
        **_state(),
        "transcript": wingman.conversation.to_display_list(),
        "replies": wingman.latest_replies,
        "read": wingman.latest_read,
        "advice": wingman.latest_advice,
    }


@app.post("/api/upload-training")
async def upload_training(files: list[UploadFile] = File(...)):
    """Upload training transcript files."""
    from wingman.training import TRAINING_DIR
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        content = await f.read()
        path = TRAINING_DIR / f.filename
        path.write_bytes(content)
        saved.append(f.filename)
        print(f"[server] Saved training file: {f.filename} ({len(content):,} bytes)")

    # Reload cache with new files
    if wingman and saved:
        success = wingman.training.load()
        if success:
            wingman.generator.set_cache(wingman.training.cache_name)
        wingman._bump()

    return {"saved": saved, "training_status": wingman.training.status if wingman else "unknown"}


@app.post("/api/upload-screenshots")
async def upload_screenshots(
    files: list[UploadFile] = File(...),
    contact: str = Form(""),
    extra_context: str = Form(""),
):
    """Upload chat screenshots from mobile. Extracts messages and generates replies."""
    if not wingman:
        return {"error": "Wingman not ready"}

    if wingman.status in ("processing", "generating"):
        return {"error": "Already processing — wait for current analysis to finish"}

    jpeg_images: list[bytes] = []
    for f in files:
        data = await f.read()
        jpeg_images.append(data)
        print(f"[server] Received screenshot: {f.filename} ({len(data):,} bytes)")

    if not jpeg_images:
        return {"error": "No images uploaded"}

    asyncio.create_task(
        wingman.process_screenshots(contact, jpeg_images, extra_context)
    )

    return {
        "status": "processing",
        "screenshots": len(jpeg_images),
        "contact": contact or "Unknown",
    }


@app.get("/frame.jpg")
async def latest_frame():
    if wingman and wingman.latest_frame_b64:
        return Response(content=base64.b64decode(wingman.latest_frame_b64), media_type="image/jpeg")
    return Response(content=b"", status_code=204)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        if wingman:
            await ws.send_text(json.dumps({"type": "status", **_state()}))
            if wingman.conversation.messages:
                await ws.send_text(json.dumps({"type": "transcript", "messages": wingman.conversation.to_display_list()}))
            if wingman.latest_replies:
                await ws.send_text(json.dumps({
                    "type": "replies",
                    "options": wingman.latest_replies,
                    "read": wingman.latest_read,
                    "advice": wingman.latest_advice,
                }))
    except Exception:
        pass

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                continue
            action = msg.get("action")

            if action == "pause":
                wingman.live.mic_muted = True
                wingman._bump()
            elif action == "resume":
                wingman.live.mic_muted = False
                wingman._bump()
            elif action == "regenerate":
                wingman._pending_regen = msg.get("preset", -1)
                wingman._regen_extra_context = msg.get("extra_context", "")
            elif action == "set_preset":
                wingman.active_preset = msg.get("index", -1)
                wingman._bump()
            elif action == "add_preset":
                wingman.presets.add(msg.get("name", ""), msg.get("instruction", ""))
                wingman._bump()
            elif action == "delete_preset":
                wingman.presets.delete(msg.get("index", -1))
                if wingman.active_preset == msg.get("index", -1):
                    wingman.active_preset = -1
                wingman._bump()
            elif action == "edit_message":
                idx = msg.get("index", -1)
                msgs = wingman.conversation.messages
                if 0 <= idx < len(msgs):
                    if "speaker" in msg:
                        msgs[idx].speaker = msg["speaker"]
                    if "text" in msg:
                        msgs[idx].text = msg["text"]
                    if msg.get("delete"):
                        msgs.pop(idx)
                    wingman.transcript_version += 1
                    if wingman.current_contact:
                        wingman.store.save(wingman.current_contact, msgs)
                    wingman._bump()
            elif action == "load_contact":
                wingman.load_contact(msg.get("contact", ""))
            elif action == "delete_contact":
                contact = msg.get("contact", "")
                if contact:
                    wingman.store.delete(contact)
                    wingman.saved_contacts = wingman.store.list_contacts()
                    if wingman.current_contact == contact:
                        wingman.conversation.messages.clear()
                        wingman.latest_replies = []
                        wingman.latest_read = ""
                        wingman.latest_advice = ""
                        wingman.current_contact = ""
                        wingman.transcript_version += 1
                        wingman.replies_version += 1
                        wingman.status = "idle"
                    wingman._bump()
                    print(f"[server] Deleted chat: {contact}")
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def run_server():
    import uvicorn
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)

if __name__ == "__main__":
    run_server()
