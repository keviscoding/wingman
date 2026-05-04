"""Editor-facing web UI — FastAPI + single-page HTML.

Purpose: freelance editors point their browser at this app, fill in
a tiny form (mode / bias / length / twist), click Generate, preview
the script and rendered frames, then one-click download a ZIP of the
PNG frame pack + manifest.json for their CapCut timeline.

No logins for v1 — gated by a shared bearer token in the ``X-Editor-Token``
header (or ``?token=`` query string for copy-paste-friendly links).
When the ``MUZO_EDITOR_TOKEN`` env var is unset the gate is disabled
(convenient for local dev).

Deployed as its own DigitalOcean App Platform app. The app image
bundles Playwright + Chromium — see ``marketing/Dockerfile``.
"""

from __future__ import annotations

import io
import json
import os
import random
import secrets
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .corpus import load_raw_corpus
from .generate import VARIANT_HINTS, generate_one, pretty_print_script
from .render import render_script
from .prompts import TonalMode, OpenerBias


# ---------------------------------------------------------------------------
# Auth — shared token, simple and sufficient for an editor network
# ---------------------------------------------------------------------------

def _require_editor_token(
    request: Request,
    token: Optional[str] = Query(default=None),
) -> None:
    """Shared-secret gate. Skip entirely if env var is unset (dev mode)."""
    expected = os.getenv("MUZO_EDITOR_TOKEN", "").strip()
    if not expected:
        return
    supplied = (
        request.headers.get("x-editor-token", "").strip()
        or (token or "").strip()
    )
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="bad_token")


app = FastAPI(
    title="Muzo Editor Tool",
    description="Generate viral DM-style marketing scripts + rendered frames.",
)


# In-process cache of rendered jobs. Keys are random IDs; values are
# paths to a temp dir holding frames + manifest. Cheap TTL eviction on
# each new job keeps the disk bounded.
_JOBS_DIR = Path(tempfile.gettempdir()) / "muzo_editor_jobs"
_JOBS_DIR.mkdir(parents=True, exist_ok=True)
_JOB_TTL_S = 60 * 60  # 1 hour


def _gc_jobs() -> None:
    now = time.time()
    for d in _JOBS_DIR.glob("*"):
        if not d.is_dir():
            continue
        try:
            age = now - d.stat().st_mtime
            if age > _JOB_TTL_S:
                for f in d.rglob("*"):
                    if f.is_file():
                        f.unlink(missing_ok=True)
                for f in sorted(d.rglob("*"), reverse=True):
                    if f.is_dir():
                        f.rmdir()
                d.rmdir()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Muzo — Editor Tool</title>
<style>
  :root {
    color-scheme: dark;
    --bg:      #0a0a0f;
    --surface: #13131c;
    --surface2:#1a1a25;
    --border:  #2a2a3a;
    --text:    #f5f5f7;
    --dim:     #9494a3;
    --dimmer:  #5f5f6e;
    --accent:  #66e0b4;
    --danger:  #ff4757;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, 'SF Pro Text', Inter, system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    line-height: 1.4;
  }
  header {
    padding: 28px 32px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  header .brand {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.3px;
  }
  header .brand span {
    color: var(--accent);
  }
  header .pill {
    padding: 6px 14px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 13px;
    color: var(--dim);
  }
  main {
    max-width: 1200px;
    margin: 0 auto;
    padding: 36px 24px 80px;
    display: grid;
    grid-template-columns: 380px 1fr;
    gap: 32px;
  }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
  }
  .card h2 {
    margin: 0 0 18px;
    font-size: 17px;
    font-weight: 600;
    letter-spacing: 0.3px;
    text-transform: uppercase;
    color: var(--dim);
  }
  label {
    display: block;
    margin: 16px 0 6px;
    font-size: 13px;
    color: var(--dim);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  select, input[type=text] {
    width: 100%;
    padding: 12px 14px;
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 10px;
    font-size: 15px;
    font-family: inherit;
  }
  select:focus, input:focus { outline: 1px solid var(--accent); }
  button {
    width: 100%;
    padding: 14px 20px;
    margin-top: 24px;
    background: var(--accent);
    color: var(--bg);
    border: none;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
    cursor: pointer;
    font-family: inherit;
  }
  button:disabled { opacity: 0.5; cursor: wait; }
  button.secondary {
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
    margin-top: 10px;
  }
  .status {
    padding: 12px 14px;
    border-radius: 10px;
    font-size: 14px;
    color: var(--dim);
    background: var(--surface2);
    margin-top: 16px;
    min-height: 20px;
  }
  .status.err { color: var(--danger); border: 1px solid var(--danger); }
  .status.ok  { color: var(--accent); }
  pre {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
    font-size: 13px;
    overflow-x: auto;
    color: var(--text);
    line-height: 1.5;
    max-height: 360px;
    overflow-y: auto;
    white-space: pre-wrap;
  }
  .bubble-line { padding: 2px 0; font-family: 'SF Mono', Menlo, monospace; }
  .bubble-line.him { color: #c4a5ff; }
  .bubble-line.her { color: var(--dim); }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px;
    margin-top: 14px;
  }
  .grid img {
    width: 100%;
    border-radius: 8px;
    background: #000;
    cursor: pointer;
    border: 1px solid var(--border);
    aspect-ratio: 9 / 16;
    object-fit: cover;
  }
  .muted { color: var(--dimmer); font-size: 13px; }
  .row { display: flex; gap: 10px; align-items: center; }
  .row > * { flex: 1; }
  .pill.ok { color: var(--accent); border-color: var(--accent); }
</style>
</head>
<body>
<header>
  <div class="brand">Muzo <span>·</span> Editor Tool</div>
  <div class="pill" id="status-pill">ready</div>
</header>
<main>
  <aside class="card">
    <h2>Script options</h2>

    <label>Mode</label>
    <select id="mode">
      <option value="playful_goofball">Playful Goofball</option>
      <option value="cocky_critic">Cocky Critic</option>
      <option value="forward_direct">Forward Direct</option>
      <option value="smooth_recovery">Smooth Recovery</option>
      <option value="dark_taboo">Dark Taboo (risky)</option>
    </select>

    <label>Opener bias</label>
    <select id="opener-bias">
      <option value="balanced" selected>Balanced (recommended)</option>
      <option value="spontaneous">Spontaneous only</option>
      <option value="image_tied">Image-tied only</option>
    </select>

    <label>Length</label>
    <select id="length">
      <option value="short" selected>Short (~12s)</option>
      <option value="medium">Medium (~17s)</option>
      <option value="long">Long (~22s)</option>
    </select>

    <label>Plot twist</label>
    <select id="twist">
      <option value="optional" selected>Optional</option>
      <option value="required">Required</option>
      <option value="none">No twist</option>
    </select>

    <label>Hook image</label>
    <select id="hook-source">
      <option value="random" selected>Random from library</option>
      <option value="upload">Upload mine</option>
      <option value="none">No image</option>
    </select>
    <input type="file" id="hook-upload" accept="image/*" style="display:none; margin-top:10px;" />

    <label>Contact name</label>
    <input type="text" id="contact-name" value="mystery.girl" />

    <button id="go">Generate script + frames</button>
    <div class="status" id="status">fill in options and click generate</div>
  </aside>

  <section>
    <div class="card" style="margin-bottom:24px;">
      <h2>Script preview</h2>
      <pre id="script-preview" class="muted">no script yet</pre>
    </div>
    <div class="card">
      <h2>Rendered frames</h2>
      <div id="frames-wrap">
        <div class="muted">frames will appear after generation</div>
      </div>
      <div class="row" style="margin-top:16px;">
        <button id="download" class="secondary" disabled>Download ZIP</button>
        <button id="regenerate" class="secondary" disabled>Regenerate</button>
      </div>
    </div>
  </section>
</main>
<script>
  const TOKEN_FROM_URL = new URLSearchParams(location.search).get('token') || '';
  const statusEl = document.getElementById('status');
  const pillEl = document.getElementById('status-pill');
  const previewEl = document.getElementById('script-preview');
  const framesEl = document.getElementById('frames-wrap');
  const downloadBtn = document.getElementById('download');
  const regenBtn = document.getElementById('regenerate');
  const goBtn = document.getElementById('go');
  const hookSrc = document.getElementById('hook-source');
  const hookUpload = document.getElementById('hook-upload');

  hookSrc.addEventListener('change', () => {
    hookUpload.style.display = hookSrc.value === 'upload' ? 'block' : 'none';
  });

  let currentJobId = null;

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = 'status ' + (cls || '');
    pillEl.textContent = cls === 'err' ? 'error' : (cls === 'ok' ? 'ready' : 'working…');
    pillEl.className = 'pill ' + (cls === 'ok' ? 'ok' : '');
  }

  async function generate() {
    goBtn.disabled = true;
    downloadBtn.disabled = true;
    regenBtn.disabled = true;
    setStatus('generating script (~30-60s)…', '');
    previewEl.textContent = '';
    framesEl.innerHTML = '<div class="muted">waiting for script…</div>';

    const fd = new FormData();
    fd.append('mode', document.getElementById('mode').value);
    fd.append('opener_bias', document.getElementById('opener-bias').value);
    fd.append('length', document.getElementById('length').value);
    fd.append('twist', document.getElementById('twist').value);
    fd.append('hook_source', hookSrc.value);
    fd.append('contact_name', document.getElementById('contact-name').value);
    if (hookSrc.value === 'upload' && hookUpload.files[0]) {
      fd.append('upload', hookUpload.files[0]);
    }
    if (TOKEN_FROM_URL) fd.append('token', TOKEN_FROM_URL);

    try {
      const r = await fetch('/api/generate', { method: 'POST', body: fd });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt || ('http ' + r.status));
      }
      const data = await r.json();
      currentJobId = data.job_id;
      previewEl.innerHTML = '';
      (data.script.messages || []).forEach((m, i) => {
        const arrow = m.speaker === 'him' ? '►' : '◄';
        const line = document.createElement('div');
        line.className = 'bubble-line ' + (m.speaker === 'him' ? 'him' : 'her');
        line.textContent = `${arrow} ${m.text}`;
        previewEl.appendChild(line);
      });
      const framesHtml = (data.frames || []).map(f =>
        `<img src="/api/job/${data.job_id}/frame/${encodeURIComponent(f)}" alt="${f}" />`
      ).join('');
      framesEl.innerHTML = '<div class="grid">' + framesHtml + '</div>';
      setStatus(
        `${data.frames.length} frames · ~${(data.duration_ms / 1000).toFixed(1)}s video`,
        'ok'
      );
      downloadBtn.disabled = false;
      regenBtn.disabled = false;
    } catch (e) {
      setStatus('error: ' + (e.message || e), 'err');
    } finally {
      goBtn.disabled = false;
    }
  }

  goBtn.addEventListener('click', generate);
  regenBtn.addEventListener('click', generate);
  downloadBtn.addEventListener('click', () => {
    if (!currentJobId) return;
    const url = `/api/job/${currentJobId}/zip` + (TOKEN_FROM_URL ? `?token=${encodeURIComponent(TOKEN_FROM_URL)}` : '');
    window.location.href = url;
  });
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index(_ok: Annotated[None, Depends(_require_editor_token)]) -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "muzo-editor"}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post("/api/generate")
async def api_generate(
    request: Request,
    mode: Annotated[str, Form()],
    opener_bias: Annotated[str, Form()],
    length: Annotated[str, Form()],
    twist: Annotated[str, Form()],
    hook_source: Annotated[str, Form()],
    contact_name: Annotated[str, Form()],
    token: Annotated[Optional[str], Form()] = None,
    upload: Annotated[Optional[UploadFile], File()] = None,
) -> JSONResponse:
    _require_editor_token(request, token)
    _gc_jobs()

    mode = mode if mode in (
        "playful_goofball", "cocky_critic", "dark_taboo",
        "forward_direct", "smooth_recovery",
    ) else "playful_goofball"
    opener_bias = opener_bias if opener_bias in ("spontaneous", "image_tied", "balanced") else "balanced"
    length = length if length in ("short", "medium", "long") else "short"
    twist = twist if twist in ("none", "optional", "required") else "optional"
    contact_name = (contact_name or "mystery.girl").strip()[:64]

    hook_path: Optional[Path] = None
    if hook_source == "random":
        hook_dir = Path(__file__).resolve().parent.parent / "hook_images_v2"
        pool = sorted(hook_dir.glob("*.jpg"))
        if pool:
            hook_path = random.choice(pool)
    elif hook_source == "upload" and upload is not None:
        suffix = Path(upload.filename or "upload.jpg").suffix or ".jpg"
        tmp = Path(tempfile.mkdtemp()) / f"hook{suffix}"
        tmp.write_bytes(await upload.read())
        hook_path = tmp

    corpus = load_raw_corpus()
    if not corpus:
        raise HTTPException(status_code=500, detail="training corpus missing")

    script = generate_one(
        mode=mode,  # type: ignore[arg-type]
        opener_bias=opener_bias,  # type: ignore[arg-type]
        length=length,
        twist=twist,
        hook_image_note=None,
        hook_image_path=hook_path,
        variant_hint=random.choice(VARIANT_HINTS),
        corpus=corpus,
    )
    if isinstance(script, list):
        if not script:
            raise HTTPException(status_code=502, detail="empty_generation")
        script = script[0]
    if not isinstance(script, dict):
        raise HTTPException(status_code=502, detail="bad_generation_shape")
    if hook_path is not None:
        script["_hook_image"] = hook_path.name

    job_id = secrets.token_urlsafe(12)
    job_dir = _JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = job_dir / "frames"

    # render_script resolves the hook image by looking in
    # hook_images_v2/ by name. If the user uploaded a file we need
    # to temporarily point the renderer at the right path — simplest
    # approach is to drop-in the uploaded file under the expected
    # name. Safe because each job has its own dir.
    if hook_path is not None and hook_path.parent.name != "hook_images_v2":
        uploaded_target = Path(__file__).resolve().parent.parent / "hook_images_v2" / hook_path.name
        # Only copy if it doesn't already exist (don't clobber curated set).
        if not uploaded_target.exists():
            uploaded_target.write_bytes(hook_path.read_bytes())
            script["_hook_image"] = uploaded_target.name

    manifest = render_script(
        script, frames_dir,
        contact_name=contact_name,
        include_typing_at_reveal=True,
    )
    (job_dir / "script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")

    return JSONResponse({
        "job_id": job_id,
        "script": script,
        "frames": [f["file"] for f in manifest["frames"]],
        "duration_ms": manifest["total_duration_ms"],
        "cta": script.get("suggested_cta"),
    })


@app.get("/api/job/{job_id}/frame/{name}")
async def api_frame(
    request: Request, job_id: str, name: str,
    token: Annotated[Optional[str], Query()] = None,
) -> FileResponse:
    _require_editor_token(request, token)
    if not job_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="bad_id")
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="bad_name")
    path = _JOBS_DIR / job_id / "frames" / name
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/png")


@app.get("/api/job/{job_id}/zip")
async def api_zip(
    request: Request, job_id: str,
    token: Annotated[Optional[str], Query()] = None,
) -> StreamingResponse:
    _require_editor_token(request, token)
    if not job_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="bad_id")
    job_dir = _JOBS_DIR / job_id
    frames_dir = job_dir / "frames"
    if not frames_dir.exists():
        raise HTTPException(status_code=404)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(frames_dir.glob("*.png")):
            z.write(p, arcname=f"frames/{p.name}")
        manifest = frames_dir / "manifest.json"
        if manifest.exists():
            z.write(manifest, arcname="manifest.json")
        script_json = job_dir / "script.json"
        if script_json.exists():
            z.write(script_json, arcname="script.json")
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=muzo_{job_id}.zip"},
    )
