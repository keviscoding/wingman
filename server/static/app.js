(() => {
  const micBtn = document.getElementById("micBtn");
  const micIcon = document.getElementById("micIcon");
  const micLabel = document.getElementById("micLabel");
  const coachSection = document.getElementById("coachSection");
  const coachRead = document.getElementById("coachRead");
  const coachAdvice = document.getElementById("coachAdvice");
  const statusBanner = document.getElementById("statusBanner");
  const statusText = document.getElementById("statusText");
  const previewImg = document.getElementById("previewImg");
  const previewSection = document.getElementById("previewSection");
  const contactLabel = document.getElementById("contactLabel");
  const contactsList = document.getElementById("contactsList");
  const results = document.getElementById("results");
  const transcriptEl = document.getElementById("transcript");
  const repliesEl = document.getElementById("replies");
  const msgCountEl = document.getElementById("msgCount");
  const regenBtn = document.getElementById("regenBtn");
  const presetSelect = document.getElementById("presetSelect");
  const addPresetBtn = document.getElementById("addPresetBtn");
  const extraContextEl = document.getElementById("extraContext");
  const toastEl = document.getElementById("toast");

  const trainingBar = document.getElementById("trainingBar");
  const trainingLabel = document.getElementById("trainingLabel");
  const trainingIcon = document.getElementById("trainingIcon");
  const uploadInput = document.getElementById("uploadInput");

  const uploadSection = document.getElementById("uploadSection");
  const contactInput = document.getElementById("contactInput");
  const screenshotInput = document.getElementById("screenshotInput");
  const uploadPreview = document.getElementById("uploadPreview");
  const analyzeBtn = document.getElementById("analyzeBtn");
  const analyzeBtnText = document.getElementById("analyzeBtnText");

  let ws = null, reconnectTimer = null, micMuted = false, isHeadless = false;
  let pendingFiles = [];

  // ── Screenshot upload ──────────────────────────────────────────────

  screenshotInput.addEventListener("change", () => {
    pendingFiles = Array.from(screenshotInput.files);
    renderUploadPreview();
  });

  function renderUploadPreview() {
    uploadPreview.innerHTML = "";
    if (!pendingFiles.length) {
      analyzeBtn.disabled = true;
      analyzeBtnText.textContent = "Select screenshots first";
      return;
    }
    pendingFiles.forEach((f, i) => {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(f);
      img.title = f.name;
      img.addEventListener("click", () => {
        pendingFiles.splice(i, 1);
        screenshotInput.value = "";
        renderUploadPreview();
      });
      uploadPreview.appendChild(img);
    });
    const n = pendingFiles.length;
    analyzeBtn.disabled = false;
    analyzeBtnText.textContent = `Analyze ${n} screenshot${n > 1 ? "s" : ""}`;
  }

  analyzeBtn.addEventListener("click", async () => {
    if (!pendingFiles.length) return;

    const fd = new FormData();
    pendingFiles.forEach(f => fd.append("files", f));
    fd.append("contact", contactInput.value.trim());
    fd.append("extra_context", extraContextEl.value.trim());

    analyzeBtn.disabled = true;
    analyzeBtn.classList.add("processing");
    analyzeBtnText.textContent = "Processing...";

    try {
      const r = await fetch("/api/upload-screenshots", { method: "POST", body: fd });
      const d = await r.json();
      if (d.error) {
        analyzeBtnText.textContent = d.error;
        analyzeBtn.classList.remove("processing");
        setTimeout(() => {
          analyzeBtn.disabled = false;
          analyzeBtnText.textContent = `Analyze ${pendingFiles.length} screenshot${pendingFiles.length > 1 ? "s" : ""}`;
        }, 2000);
      } else {
        analyzeBtnText.textContent = `Reading ${d.screenshots} screenshot${d.screenshots > 1 ? "s" : ""}...`;
        if (d.contact) contactInput.value = d.contact;
      }
    } catch (e) {
      analyzeBtnText.textContent = "Upload failed — try again";
      analyzeBtn.classList.remove("processing");
      analyzeBtn.disabled = false;
    }
  });

  // ── WebSocket ──────────────────────────────────────────────────────

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { if (reconnectTimer) clearTimeout(reconnectTimer); };
    ws.onclose = () => { reconnectTimer = setTimeout(connect, 2000); };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => handle(JSON.parse(e.data));
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function handle(msg) {
    if (msg.type === "status") handleStatus(msg);
    if (msg.type === "transcript") renderTranscript(msg.messages);
    if (msg.type === "replies") renderReplies(msg.options, msg.read, msg.advice);
  }

  setInterval(async () => {
    try {
      const d = await (await fetch("/api/state")).json();
      handleStatus(d);
      if (d.transcript && d.transcript.length) renderTranscript(d.transcript);
      if (d.replies && d.replies.length) renderReplies(d.replies, d.read, d.advice);
    } catch {}
  }, 2000);

  setInterval(() => {
    if (!isHeadless) previewImg.src = "/frame.jpg?t=" + Date.now();
  }, 2000);

  // ── Status ─────────────────────────────────────────────────────────

  const msgs = {
    idle: "Upload screenshots or say \"read this chat\"",
    processing: "Reading the chat...",
    generating: "Generating reply options...",
    done: "Done! Upload more screenshots or say \"read this\" for another chat.",
  };

  function handleStatus(s) {
    const state = s.status || s.state || "idle";
    isHeadless = s.headless || false;

    statusText.textContent = msgs[state] || state;
    statusBanner.classList.toggle("active", state !== "idle");

    // In headless mode, hide desktop-only elements
    if (isHeadless) {
      micBtn.classList.add("hidden-headless");
      if (previewSection) previewSection.style.display = "none";
    } else {
      micBtn.classList.remove("hidden-headless");
      if (previewSection) previewSection.style.display = "";
    }

    // Reset analyze button when done/idle
    if (state === "done" || state === "idle") {
      analyzeBtn.classList.remove("processing");
      if (pendingFiles.length) {
        analyzeBtn.disabled = false;
        analyzeBtnText.textContent = `Analyze ${pendingFiles.length} screenshot${pendingFiles.length > 1 ? "s" : ""}`;
      } else {
        analyzeBtn.disabled = true;
        analyzeBtnText.textContent = "Select screenshots first";
      }
      if (state === "done") {
        pendingFiles = [];
        screenshotInput.value = "";
        uploadPreview.innerHTML = "";
        analyzeBtn.disabled = true;
        analyzeBtnText.textContent = "Select screenshots first";
      }
    }

    micMuted = s.mic_muted || false;
    micBtn.classList.toggle("muted", micMuted);
    micIcon.textContent = micMuted ? "\u23F8" : "\uD83C\uDFA4";
    micLabel.textContent = micMuted ? "Paused" : "Listening";

    if (s.contact) {
      contactLabel.textContent = "Chat with " + s.contact;
      if (!contactInput.value.trim()) contactInput.value = s.contact;
    } else {
      contactLabel.textContent = "";
    }

    if (s.contacts && s.contacts.length) {
      contactsList.innerHTML = s.contacts.map(c =>
        `<div class="contact-item${c === s.contact ? " active" : ""}" data-contact="${esc(c)}">` +
        `<span>${esc(c)}</span>` +
        `<span class="contact-delete" data-del="${esc(c)}" title="Delete chat">\u2715</span></div>`
      ).join("");
      contactsList.querySelectorAll(".contact-item").forEach(el => {
        el.addEventListener("click", (e) => {
          if (e.target.classList.contains("contact-delete")) return;
          const contact = el.dataset.contact;
          contactInput.value = contact;
          send({ action: "load_contact", contact });
        });
      });
      contactsList.querySelectorAll(".contact-delete").forEach(el => {
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          if (confirm(`Delete chat with ${el.dataset.del}?`)) {
            send({ action: "delete_contact", contact: el.dataset.del });
          }
        });
      });
    } else {
      contactsList.innerHTML = '<p class="empty-small">No chats yet</p>';
    }

    if (s.messages > 0 || s.has_replies) results.classList.remove("hidden");

    if (s.presets) {
      const current = presetSelect.value;
      presetSelect.innerHTML = '<option value="-1">No goal (default)</option>' +
        s.presets.map((p, i) =>
          `<option value="${i}"${i === s.active_preset ? " selected" : ""}>${esc(p.name)}</option>`
        ).join("");
      if (current !== presetSelect.value) presetSelect.value = s.active_preset;
    }

    if (s.training_status === "loaded") {
      trainingBar.classList.add("loaded");
      trainingLabel.textContent = `Training: ${s.training_files} files, ${(s.training_tokens || 0).toLocaleString()} tokens`;
      trainingIcon.textContent = "\u2705";
    } else if (s.training_status === "loading") {
      trainingLabel.textContent = "Training: loading...";
    } else {
      trainingBar.classList.remove("loaded");
      trainingLabel.textContent = "Training: " + (s.training_status || "not loaded");
    }
  }

  // ── Rendering ──────────────────────────────────────────────────────

  function renderTranscript(messages) {
    if (!messages || !messages.length) return;
    results.classList.remove("hidden");
    msgCountEl.textContent = `(${messages.length})`;
    transcriptEl.innerHTML = messages.map((m, i) => {
      const replyHtml = m.reply_to
        ? `<span class="reply-quote">Replying to: ${esc(m.reply_to)}</span>` : "";
      const textHtml = formatMedia(esc(m.text));
      const swap = m.speaker === "me" ? "them" : "me";
      return `<div class="msg ${m.speaker}" data-idx="${i}">` +
        `<div class="msg-actions">` +
        `<button class="msg-action" data-swap="${swap}" title="Change to ${swap}">&#8644;</button>` +
        `<button class="msg-action" data-edit="1" title="Edit text">&#9998;</button>` +
        `<button class="msg-action" data-del="1" title="Delete">&times;</button>` +
        `</div>` +
        `<span class="who">${m.speaker === "me" ? "You" : "Them"}</span>` +
        `${replyHtml}${textHtml}</div>`;
    }).join("");

    transcriptEl.querySelectorAll(".msg-action").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const msg = btn.closest(".msg");
        const idx = parseInt(msg.dataset.idx);
        if (btn.dataset.swap) {
          send({ action: "edit_message", index: idx, speaker: btn.dataset.swap });
        } else if (btn.dataset.edit) {
          const current = messages[idx]?.text || "";
          const newText = prompt("Edit message:", current);
          if (newText !== null && newText !== current) {
            send({ action: "edit_message", index: idx, text: newText });
          }
        } else if (btn.dataset.del) {
          send({ action: "edit_message", index: idx, delete: true });
        }
      });
    });

    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }

  function formatMedia(text) {
    return text.replace(/\[(image|video|voice note|sticker|GIF|link|shared post)([^\]]*)\]/g,
      (match, type, desc) => {
        const icons = {
          "image": "\uD83D\uDDBC\uFE0F", "video": "\uD83C\uDFAC",
          "voice note": "\uD83C\uDF99\uFE0F", "sticker": "\uD83E\uDEA7",
          "GIF": "\uD83C\uDF1F", "link": "\uD83D\uDD17", "shared post": "\uD83D\uDCE4"
        };
        const icon = icons[type] || "\uD83D\uDCCE";
        const label = desc.trim().replace(/^:\s*/, "") || type;
        return `<span class="media-tag">${icon} ${label}</span>`;
      }
    );
  }

  function renderReplies(options, read, advice) {
    if (!options || !options.length) return;
    results.classList.remove("hidden");

    if (read || advice) {
      coachRead.textContent = read || "";
      coachAdvice.textContent = advice ? "\u2192 " + advice : "";
      coachSection.classList.remove("hidden");
    }

    repliesEl.innerHTML = options.map(o => {
      const whyHtml = o.why ? `<div class="why">${esc(o.why)}</div>` : "";
      return `<div class="reply-card" data-text="${escA(o.text)}">` +
        `<span class="label">${esc(o.label)}</span>` +
        `<div class="text">${esc(o.text)}</div>` +
        `${whyHtml}` +
        `<div class="hint">Tap to copy</div></div>`;
    }).join("");
    repliesEl.querySelectorAll(".reply-card").forEach(c =>
      c.addEventListener("click", () => copy(c.dataset.text))
    );
  }

  function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function escA(s) { return s.replace(/"/g, "&quot;"); }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); } catch {
      const t = document.createElement("textarea"); t.value = text;
      t.style.cssText = "position:fixed;left:-9999px";
      document.body.appendChild(t); t.select(); document.execCommand("copy");
      document.body.removeChild(t);
    }
    toastEl.classList.add("show");
    setTimeout(() => toastEl.classList.remove("show"), 1500);
  }

  // ── Events ─────────────────────────────────────────────────────────

  micBtn.addEventListener("click", () => {
    send({ action: micMuted ? "resume" : "pause" });
  });

  regenBtn.addEventListener("click", () => {
    send({
      action: "regenerate",
      preset: parseInt(presetSelect.value),
      extra_context: extraContextEl.value.trim(),
    });
  });

  presetSelect.addEventListener("change", () => {
    send({ action: "set_preset", index: parseInt(presetSelect.value) });
  });

  addPresetBtn.addEventListener("click", () => {
    const name = prompt("Preset name (short label):", "Get her on a date");
    if (!name) return;
    const instr = prompt("Goal instruction (what to add to the prompt):",
      "Goal is to get her invested and set up a date this week");
    if (!instr) return;
    send({ action: "add_preset", name: name, instruction: instr });
  });

  uploadInput.addEventListener("change", async () => {
    if (!uploadInput.files.length) return;
    const fd = new FormData();
    for (const f of uploadInput.files) fd.append("files", f);
    trainingLabel.textContent = `Uploading ${uploadInput.files.length} files...`;
    try {
      const r = await fetch("/api/upload-training", { method: "POST", body: fd });
      const d = await r.json();
      trainingLabel.textContent = `Uploaded! ${d.training_status}`;
    } catch (e) {
      trainingLabel.textContent = "Upload failed";
    }
    uploadInput.value = "";
  });

  connect();
})();
