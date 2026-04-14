"""FastAPI server — polls Wingman state and pushes to browser."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
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
        "headless": w.headless,
        "mic_muted": getattr(w.live, "mic_muted", False),
        "collecting_count": w.collecting_count,
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


@app.middleware("http")
async def allow_web_notifications(request: Request, call_next):
    """Ensure Notifications API is not blocked by a missing Permissions-Policy (some hosts default-deny)."""
    response = await call_next(request)
    if not any(k.lower() == "permissions-policy" for k in response.headers.keys()):
        response.headers["Permissions-Policy"] = "notifications=(self)"
    return response


@app.get("/")
async def index():
    """Serve SPA; inject headless-only layout hooks when WINGMAN_HEADLESS is set (DO / Safari)."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    if HEADLESS:
        html = html.replace("<html lang=\"en\">", "<html lang=\"en\" class=\"headless-mobile\">", 1)
        inject = '  <link rel="stylesheet" href="/static/mobile.css?v=4">\n'
        html = html.replace("</head>", inject + "</head>", 1)
    return Response(content=html, media_type="text/html")


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


TRAINING_EXPORT_EXTS = frozenset({".txt", ".md", ".text", ".csv", ".json", ".srt", ".vtt"})


def _collect_training_files_export() -> list[dict]:
    from wingman.training import TRAINING_DIR

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for fp in sorted(TRAINING_DIR.iterdir()):
        if fp.is_file() and fp.suffix.lower() in TRAINING_EXPORT_EXTS:
            try:
                out.append({"name": fp.name, "content": fp.read_text(encoding="utf-8", errors="replace")})
            except Exception as exc:
                print(f"[export] skip {fp}: {exc}")
    return out


def _collect_chats_export() -> list[dict]:
    from wingman.chat_store import STORE_DIR

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for fp in sorted(STORE_DIR.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            out.append({"contact": data.get("contact", fp.stem), "messages": data.get("messages", [])})
        except Exception as exc:
            print(f"[export] skip chat {fp}: {exc}")
    return out


def _export_presets_only() -> dict:
    if not wingman:
        return {"presets": [], "active_preset": -1}
    return {"presets": wingman.presets.presets, "active_preset": wingman.active_preset}


def _is_full_bundle(body: dict) -> bool:
    if body.get("wingman_bundle_version") == 1:
        return True
    if "training_files" in body or "chats" in body:
        return True
    return False


def _clear_training_for_import() -> None:
    from wingman.training import TRAINING_DIR

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    for fp in TRAINING_DIR.iterdir():
        if fp.is_file() and fp.suffix.lower() in TRAINING_EXPORT_EXTS:
            try:
                fp.unlink()
            except Exception:
                pass


def _clear_chats_for_import() -> None:
    from wingman.chat_store import STORE_DIR

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    for fp in STORE_DIR.glob("*.json"):
        try:
            fp.unlink()
        except Exception:
            pass


def _apply_full_bundle(body: dict) -> dict:
    w = wingman
    assert w is not None
    _clear_training_for_import()
    _clear_chats_for_import()
    presets = body.get("presets", [])
    if isinstance(presets, list):
        w.presets.replace_all(presets)
    ap = body.get("active_preset", -1)
    try:
        ap = int(ap)
    except (TypeError, ValueError):
        ap = -1
    n = len(w.presets.presets)
    if n == 0:
        w.active_preset = -1
    elif ap < 0 or ap >= n:
        w.active_preset = -1
    else:
        w.active_preset = ap

    from wingman.training import TRAINING_DIR

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    for item in body.get("training_files") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name or not isinstance(name, str):
            continue
        safe = Path(str(name)).name
        if not safe or safe.startswith("."):
            continue
        content = item.get("content", "")
        (TRAINING_DIR / safe).write_text(str(content), encoding="utf-8")

    if w.training.load():
        w.generator.set_cache(w.training.cache_name, training_cache=w.training)

    for ch in body.get("chats") or []:
        if not isinstance(ch, dict):
            continue
        contact = str(ch.get("contact", "imported")).strip() or "imported"
        messages = ch.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        w.store.save_raw(contact, messages)
    w.saved_contacts = w.store.list_contacts()
    w._bump()
    return {
        "ok": True,
        "presets_count": n,
        "training_files": len(body.get("training_files") or []),
        "chats_count": len(body.get("chats") or []),
        "active_preset": w.active_preset,
    }


def apply_import_payload(body: Any) -> dict:
    """Import goals-only export, raw presets array, or full wingman bundle."""
    if not wingman:
        return {"error": "Wingman not ready"}
    if isinstance(body, list):
        wingman.presets.replace_all(body)
        wingman.active_preset = -1
        wingman._bump()
        return {"ok": True, "count": len(wingman.presets.presets), "active_preset": -1}
    if not isinstance(body, dict):
        return {"error": "Invalid JSON"}
    if _is_full_bundle(body):
        return _apply_full_bundle(body)
    raw = body.get("presets")
    if not isinstance(raw, list):
        return {"error": "Invalid JSON: use Export, or a list of {name, instruction}"}
    wingman.presets.replace_all(raw)
    ap = body.get("active_preset", -1)
    try:
        ap = int(ap)
    except (TypeError, ValueError):
        ap = -1
    n = len(wingman.presets.presets)
    if n == 0:
        wingman.active_preset = -1
    elif ap < 0 or ap >= n:
        wingman.active_preset = -1
    else:
        wingman.active_preset = ap
    wingman._bump()
    return {"ok": True, "count": n, "active_preset": wingman.active_preset}


@app.get("/api/export/bundle")
async def api_export_bundle():
    """Full backup: goals, training transcript files, and saved chats (JSON)."""
    if not wingman:
        return {
            "wingman_bundle_version": 1,
            "presets": [],
            "active_preset": -1,
            "training_files": [],
            "chats": [],
        }
    return {
        "wingman_bundle_version": 1,
        "presets": wingman.presets.presets,
        "active_preset": wingman.active_preset,
        "training_files": _collect_training_files_export(),
        "chats": _collect_chats_export(),
    }


@app.get("/api/export/presets")
async def api_export_presets():
    """Goals only (smaller file)."""
    return _export_presets_only()


@app.get("/api/presets-export")
async def api_export_presets_legacy_path():
    """Legacy path — same as /api/export/presets (some proxies mis-handle hyphenated paths)."""
    return _export_presets_only()


@app.post("/api/import/bundle")
@app.post("/api/presets-import")
async def api_import_any(body: Any = Body(...)):
    """Import full bundle, goals-only export, or raw presets array."""
    return apply_import_payload(body)


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
    """Upload chat screenshots and/or videos."""
    if not wingman:
        return {"error": "Wingman not ready"}

    if wingman.status in ("processing", "generating"):
        return {"error": "Already processing — wait for current analysis to finish"}

    from wingman.chat_reader import ChatReader
    media_items: list[tuple[bytes, str]] = []
    for f in files:
        data = await f.read()
        mime = ChatReader.detect_mime(f.filename or "", data)
        media_items.append((data, mime))
        print(f"[server] Received: {f.filename} ({len(data):,} bytes, {mime})")

    if not media_items:
        return {"error": "No files uploaded"}

    asyncio.create_task(
        wingman.process_media(contact, media_items, extra_context)
    )

    return {
        "status": "processing",
        "files": len(media_items),
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

            if action == "new_chat":
                wingman.conversation.messages.clear()
                wingman.latest_replies = []
                wingman.latest_read = ""
                wingman.latest_advice = ""
                wingman.current_contact = ""
                wingman.collecting_count = 0
                wingman.transcript_version += 1
                wingman.replies_version += 1
                wingman.status = "idle"
                wingman._bump()
                print("[server] New chat started")
            elif action == "start_reading":
                contact = msg.get("contact", "")
                context = msg.get("context", "")
                wingman.start_collecting(contact, context)
            elif action == "stop_reading":
                asyncio.create_task(wingman.stop_collecting())
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
            elif action == "rename_contact":
                old_name = msg.get("old_name", "")
                new_name = msg.get("new_name", "")
                if old_name and new_name and old_name != new_name:
                    old_msgs = wingman.store.load(old_name)
                    if old_msgs:
                        wingman.store.delete(old_name)
                        wingman.store.save_raw(new_name, old_msgs)
                        wingman.saved_contacts = wingman.store.list_contacts()
                        if wingman.current_contact == old_name:
                            wingman.current_contact = new_name
                        wingman.transcript_version += 1
                        wingman._bump()
                        print(f"[server] Renamed chat: {old_name} -> {new_name}")
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
