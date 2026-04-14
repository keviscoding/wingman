(() => {
  const readBtn = document.getElementById("readBtn");
  const readIcon = document.getElementById("readIcon");
  const readLabel = document.getElementById("readLabel");
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
  const toastEl = document.getElementById("toast");

  const trainingBar = document.getElementById("trainingBar");
  const trainingLabel = document.getElementById("trainingLabel");
  const trainingIcon = document.getElementById("trainingIcon");
  const uploadInput = document.getElementById("uploadInput");

  const readContactInput = document.getElementById("readContactInput");
  const readExtraContext = document.getElementById("readExtraContext");
  const readingContactBar = document.getElementById("readingContactBar");

  // Headless-only elements
  const contactInput = document.getElementById("contactInput");
  const screenshotInput = document.getElementById("screenshotInput");
  const uploadPreview = document.getElementById("uploadPreview");
  const analyzeBtn = document.getElementById("analyzeBtn");
  const analyzeBtnText = document.getElementById("analyzeBtnText");
  const extraContextEl = document.getElementById("extraContext");
  const uploadSection = document.getElementById("uploadSection");

  function isMobileHost() {
    return document.documentElement.classList.contains("headless-mobile");
  }

  /** Contact / context for screenshot uploads (headless uses upload section fields). */
  function contactForUpload() {
    if (isMobileHost() && contactInput) return contactInput.value.trim();
    return readContactInput ? readContactInput.value.trim() : "";
  }

  function extraForUpload() {
    if (isMobileHost() && extraContextEl) return extraContextEl.value.trim();
    return readExtraContext ? readExtraContext.value.trim() : "";
  }

  let ws = null, reconnectTimer = null, isHeadless = false;
  let isReading = false;
  let pendingFiles = [];
  let lastSoundState = "idle";

  if (isMobileHost()) {
    isHeadless = true;
    readBtn.style.display = "none";
    if (readingContactBar) readingContactBar.style.display = "none";
    if (previewSection) previewSection.style.display = "none";
    if (uploadSection) uploadSection.style.display = "";
    statusText.textContent = "Upload chat screenshots to get started";
  }

  // ── Sound effects (Web Audio API) ─────────────────────────────────

  let audioCtx = null;

  function ensureAudio() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    return audioCtx;
  }

  document.addEventListener("click", ensureAudio, { once: true });
  document.addEventListener("keydown", ensureAudio, { once: true });
  document.addEventListener("touchstart", ensureAudio, { once: true });

  function playStartSound() {
    const ctx = ensureAudio();
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.setValueAtTime(523, now);
    osc.frequency.setValueAtTime(659, now + 0.1);
    osc.frequency.setValueAtTime(784, now + 0.2);
    gain.gain.setValueAtTime(0.25, now);
    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4);
    osc.start(now);
    osc.stop(now + 0.4);
  }

  function playDoneSound() {
    const ctx = ensureAudio();
    const now = ctx.currentTime;
    [784, 1047].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "sine";
      const t = now + i * 0.15;
      osc.frequency.setValueAtTime(freq, t);
      gain.gain.setValueAtTime(0.28, t);
      gain.gain.exponentialRampToValueAtTime(0.01, t + 0.35);
      osc.start(t);
      osc.stop(t + 0.35);
    });
  }

  function playRepliesReady() {
    const ctx = ensureAudio();
    const now = ctx.currentTime;
    [523, 659, 784, 1047].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "triangle";
      const t = now + i * 0.1;
      osc.frequency.setValueAtTime(freq, t);
      gain.gain.setValueAtTime(0.2, t);
      gain.gain.exponentialRampToValueAtTime(0.01, t + 0.25);
      osc.start(t);
      osc.stop(t + 0.25);
    });
  }

  function playBeep(freq = 880, dur = 0.12) {
    const ctx = ensureAudio();
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, now);
    gain.gain.setValueAtTime(0.3, now);
    gain.gain.exponentialRampToValueAtTime(0.01, now + dur);
    osc.start(now);
    osc.stop(now + dur);
  }

  let countdownActive = false;

  async function startCountdownRead(contact, context) {
    if (countdownActive || isReading) return;
    countdownActive = true;

    // Phase 1: Navigate countdown (3-2-1, go to the chat)
    for (let i = 3; i >= 1; i--) {
      statusText.textContent = `Go to the chat... ${i}`;
      statusBanner.classList.add("active");
      playBeep(660, 0.1);
      await new Promise(r => setTimeout(r, 1000));
    }

    // Start reading
    playStartSound();
    send({ action: "start_reading", contact, context });
    setReadingState(true);
    statusText.textContent = "Reading...";

    // Phase 2: Capture countdown (3 seconds to capture the screen)
    for (let i = 3; i >= 1; i--) {
      statusText.textContent = `Capturing... ${i}`;
      playBeep(880, 0.08);
      await new Promise(r => setTimeout(r, 1000));
    }

    // Auto-stop
    send({ action: "stop_reading" });
    playDoneSound();
    setReadingState(false);
    statusText.textContent = "Done — processing...";
    countdownActive = false;
  }

  // ── Theme toggle ──────────────────────────────────────────────────

  const themeBtn = document.getElementById("themeBtn");
  const savedTheme = localStorage.getItem("wingman-theme") || "dark";
  if (savedTheme === "light") document.documentElement.setAttribute("data-theme", "light");
  updateThemeBtn();

  themeBtn.addEventListener("click", () => {
    const isLight = document.documentElement.getAttribute("data-theme") === "light";
    if (isLight) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem("wingman-theme", "dark");
    } else {
      document.documentElement.setAttribute("data-theme", "light");
      localStorage.setItem("wingman-theme", "light");
    }
    updateThemeBtn();
  });

  function updateThemeBtn() {
    const isLight = document.documentElement.getAttribute("data-theme") === "light";
    themeBtn.textContent = isLight ? "\u263E" : "\u2606";
    themeBtn.title = isLight ? "Switch to dark mode" : "Switch to light mode";
  }

  // ── Start Reading / Done button ───────────────────────────────────

  // ── Drop zone for screenshots ──────────────────────────────────

  const dropZone = document.getElementById("dropZone");
  const dropZoneInner = document.getElementById("dropZoneInner");
  const dropPreview = document.getElementById("dropPreview");
  const dropFileInput = document.getElementById("dropFileInput");
  const dropAnalyzeBtn = document.getElementById("dropAnalyzeBtn");
  let dropFiles = [];

  ["dragenter", "dragover"].forEach(evt => {
    dropZoneInner.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(evt => {
    dropZoneInner.addEventListener(evt, () => dropZone.classList.remove("dragover"));
  });

  dropZoneInner.addEventListener("drop", (e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith("image/") || f.type.startsWith("video/"));
    if (files.length) {
      dropFiles.push(...files);
      renderDropPreview();
    }
  });

  dropFileInput.addEventListener("change", () => {
    dropFiles.push(...Array.from(dropFileInput.files));
    dropFileInput.value = "";
    renderDropPreview();
  });

  function renderDropPreview() {
    dropPreview.innerHTML = "";
    dropFiles.forEach((f, i) => {
      let el;
      if (f.type.startsWith("video/")) {
        el = document.createElement("video");
        el.src = URL.createObjectURL(f);
        el.muted = true;
      } else {
        el = document.createElement("img");
        el.src = URL.createObjectURL(f);
      }
      el.title = `${f.name} — click to remove`;
      el.addEventListener("click", () => {
        dropFiles.splice(i, 1);
        renderDropPreview();
      });
      dropPreview.appendChild(el);
    });
    dropAnalyzeBtn.classList.toggle("hidden", dropFiles.length === 0);
    const label = dropFiles.length === 1 ? "1 file" : `${dropFiles.length} files`;
    dropAnalyzeBtn.textContent = `Analyze ${label}`;
  }

  dropAnalyzeBtn.addEventListener("click", async () => {
    if (!dropFiles.length) return;

    dropAnalyzeBtn.disabled = true;
    dropAnalyzeBtn.textContent = "Reading...";

    const fd = new FormData();
    dropFiles.forEach(f => fd.append("files", f));
    fd.append("contact", contactForUpload());
    fd.append("extra_context", extraForUpload());

    try {
      const r = await fetch("/api/upload-screenshots", { method: "POST", body: fd });
      const d = await r.json();
      if (d.error) {
        dropAnalyzeBtn.textContent = d.error;
        setTimeout(() => renderDropPreview(), 2000);
      } else {
        dropFiles = [];
        dropPreview.innerHTML = "";
        dropAnalyzeBtn.classList.add("hidden");
        if (d.contact) {
          if (readContactInput) readContactInput.value = d.contact;
          if (contactInput) contactInput.value = d.contact;
        }
      }
    } catch (e) {
      dropAnalyzeBtn.textContent = "Upload failed — try again";
    }
    dropAnalyzeBtn.disabled = false;
  });

  // ── Start Reading / Done button ───────────────────────────────────

  readBtn.addEventListener("click", () => {
    if (isReading) {
      send({ action: "stop_reading" });
      playDoneSound();
      setReadingState(false);
      countdownActive = false;
    } else {
      const contact = readContactInput ? readContactInput.value.trim() : "";
      const context = readExtraContext ? readExtraContext.value.trim() : "";
      startCountdownRead(contact, context);
    }
  });

  function setReadingState(reading) {
    isReading = reading;
    if (reading) {
      readBtn.classList.add("active");
      readIcon.textContent = "\u2713";
      readLabel.textContent = "Done";
      addToggle.textContent = "\u2713 Done";
      addToggle.classList.add("active");
    } else {
      readBtn.classList.remove("active");
      readIcon.textContent = "\uD83D\uDC41";
      readLabel.textContent = "Start Reading";
      addToggle.textContent = "+ Add new";
      addToggle.classList.remove("active");
    }
  }

  // ── Screenshot upload (headless only) ─────────────────────────────

  if (screenshotInput) {
    screenshotInput.addEventListener("change", () => {
      pendingFiles = Array.from(screenshotInput.files);
      renderUploadPreview();
      updateAnalyzeBtn();
    });
  }

  function renderUploadPreview() {
    if (!uploadPreview) return;
    uploadPreview.innerHTML = "";
    if (!pendingFiles.length) return;
    pendingFiles.forEach((f, i) => {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(f);
      img.title = f.name;
      img.addEventListener("click", () => {
        pendingFiles.splice(i, 1);
        if (screenshotInput) screenshotInput.value = "";
        renderUploadPreview();
        updateAnalyzeBtn();
      });
      uploadPreview.appendChild(img);
    });
  }

  function updateAnalyzeBtn() {
    if (!analyzeBtn) return;
    if (pendingFiles.length > 0) {
      analyzeBtn.disabled = false;
      analyzeBtnText.textContent = `Analyze ${pendingFiles.length} screenshot${pendingFiles.length > 1 ? "s" : ""}`;
    } else {
      analyzeBtn.disabled = true;
      analyzeBtnText.textContent = "Select screenshots";
    }
  }

  if (analyzeBtn) {
    analyzeBtn.addEventListener("click", async () => {
      if (!pendingFiles.length) return;

      const fd = new FormData();
      pendingFiles.forEach(f => fd.append("files", f));
      fd.append("contact", contactInput ? contactInput.value.trim() : "");
      fd.append("extra_context", extraContextEl ? extraContextEl.value.trim() : "");

      analyzeBtn.disabled = true;
      analyzeBtn.classList.add("processing");
      analyzeBtnText.textContent = "Processing...";

      try {
        const r = await fetch("/api/upload-screenshots", { method: "POST", body: fd });
        const d = await r.json();
        if (d.error) {
          analyzeBtnText.textContent = d.error;
          analyzeBtn.classList.remove("processing");
          setTimeout(() => updateAnalyzeBtn(), 2000);
        } else {
          const n = d.files ?? 1;
          analyzeBtnText.textContent = `Reading ${n} file${n > 1 ? "s" : ""}...`;
          if (d.contact) {
            if (contactInput) contactInput.value = d.contact;
            if (readContactInput) readContactInput.value = d.contact;
          }
        }
      } catch (e) {
        analyzeBtnText.textContent = "Upload failed — try again";
        analyzeBtn.classList.remove("processing");
        analyzeBtn.disabled = false;
      }
    });
  }

  // ── WebSocket ─────────────────────────────────────────────────────

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
      if (d.transcript) renderTranscript(d.transcript);
      if (d.replies && d.replies.length) renderReplies(d.replies, d.read, d.advice);
    } catch {}
  }, 2000);

  setInterval(() => {
    if (!isHeadless) previewImg.src = "/frame.jpg?t=" + Date.now();
  }, 2000);

  // ── Status ────────────────────────────────────────────────────────

  const desktopMsgs = {
    idle: 'Say "read this" or click Start Reading while looking at a chat',
    collecting: "Reading chat — keep scrolling...",
    generating: "Generating reply options...",
    done: 'Done! Say "read this" for another chat.',
  };
  const headlessMsgs = {
    idle: "Upload chat screenshots to get started",
    processing: "Reading the chat...",
    collecting: "Reading the chat...",
    generating: "Generating reply options...",
    done: "Done! Upload more screenshots for another chat.",
  };

  function handleStatus(s) {
    const state = s.status || s.state || "idle";
    isHeadless = s.headless || false;

    const msgs = isHeadless ? headlessMsgs : desktopMsgs;
    let statusMsg = msgs[state] || state;
    if (state === "collecting" && s.collecting_count) {
      statusMsg = `Reading — ${s.collecting_count} messages so far. Keep scrolling, click Done when finished.`;
    }
    statusText.textContent = statusMsg;
    statusBanner.classList.toggle("active", state !== "idle");
    statusBanner.classList.toggle("collecting", state === "collecting");

    // Sound effects on state transitions
    if (state !== lastSoundState) {
      if (state === "collecting" && lastSoundState !== "collecting") playStartSound();
      if (lastSoundState === "collecting" && state !== "collecting") playDoneSound();
      if (state === "done" && lastSoundState === "generating") playRepliesReady();
      lastSoundState = state;
    }

    // Sync reading button state with server
    if (state === "collecting" && !isReading) setReadingState(true);
    if (state !== "collecting" && isReading) setReadingState(false);

    if (isHeadless) {
      readBtn.style.display = "none";
      if (readingContactBar) readingContactBar.style.display = "none";
      if (previewSection) previewSection.style.display = "none";
      if (uploadSection) uploadSection.style.display = "";
    } else {
      readBtn.style.display = "";
      if (readingContactBar) readingContactBar.style.display = "";
      if (previewSection) previewSection.style.display = "";
      if (uploadSection) uploadSection.style.display = "none";
    }

    if (state === "done" || state === "idle") {
      if (analyzeBtn) {
        analyzeBtn.classList.remove("processing");
        if (state === "done") {
          pendingFiles = [];
          if (screenshotInput) screenshotInput.value = "";
          if (uploadPreview) uploadPreview.innerHTML = "";
        }
        updateAnalyzeBtn();
      }
    }

    if (s.contact) {
      contactLabel.textContent = "Chat with " + s.contact;
      if (readContactInput && !readContactInput.value.trim()) readContactInput.value = s.contact;
      if (contactInput && !contactInput.value.trim()) contactInput.value = s.contact;
    } else {
      contactLabel.textContent = "";
    }

    if (s.contacts && s.contacts.length) {
      contactsList.innerHTML = s.contacts.map(c =>
        `<div class="contact-item${c === s.contact ? " active" : ""}" data-contact="${esc(c)}">` +
        `<span class="contact-name">${esc(c)}</span>` +
        `<span class="contact-actions">` +
        `<span class="contact-rename" data-rename="${esc(c)}" title="Rename">&#9998;</span>` +
        `<span class="contact-delete" data-del="${esc(c)}" title="Delete">\u2715</span>` +
        `</span></div>`
      ).join("");
      contactsList.querySelectorAll(".contact-item").forEach(el => {
        el.addEventListener("click", (e) => {
          if (e.target.classList.contains("contact-delete") || e.target.classList.contains("contact-rename")) return;
          const contact = el.dataset.contact;
          if (readContactInput) readContactInput.value = contact;
          if (contactInput) contactInput.value = contact;
          lastTranscriptCount = 0;
          send({ action: "load_contact", contact });
        });
      });
      contactsList.querySelectorAll(".contact-rename").forEach(el => {
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          const oldName = el.dataset.rename;
          const newName = prompt("Rename chat:", oldName);
          if (newName && newName.trim() && newName.trim() !== oldName) {
            send({ action: "rename_contact", old_name: oldName, new_name: newName.trim() });
          }
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

  // ── Rendering ─────────────────────────────────────────────────────

  let lastTranscriptCount = 0;

  function renderTranscript(messages) {
    if (!messages || !messages.length) {
      transcriptEl.innerHTML = "";
      msgCountEl.textContent = "";
      lastTranscriptCount = 0;
      return;
    }
    results.classList.remove("hidden");
    const prevCount = lastTranscriptCount;
    lastTranscriptCount = messages.length;
    if (messages.length === prevCount) return;
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

    const wasNearBottom = transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight < 80;
    if (wasNearBottom || prevCount === 0) {
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
    }
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

    if ((read || advice) && !isMobileHost()) {
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

  // ── Events ────────────────────────────────────────────────────────

  const extraRequestInput = document.getElementById("extraRequestInput");

  regenBtn.addEventListener("click", () => {
    const extraRequest = extraRequestInput ? extraRequestInput.value.trim() : "";
    const baseContext = extraForUpload();
    const combined = [baseContext, extraRequest].filter(Boolean).join("\n");
    send({
      action: "regenerate",
      preset: parseInt(presetSelect.value),
      extra_context: combined,
    });
    if (extraRequestInput) extraRequestInput.value = "";
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

  // ── Add new dropdown (read screen or screenshot) ─────────────────

  const addToggle = document.getElementById("addToggle");
  const addMenu = document.getElementById("addMenu");
  const addReadScreen = document.getElementById("addReadScreen");
  const addScreenshotInput = document.getElementById("addScreenshotInput");

  addToggle.addEventListener("click", () => {
    if (isReading) {
      send({ action: "stop_reading" });
      playDoneSound();
      setReadingState(false);
      return;
    }
    addMenu.classList.toggle("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#addDropdown")) addMenu.classList.add("hidden");
  });

  addReadScreen.addEventListener("click", () => {
    addMenu.classList.add("hidden");
    const contact = contactForUpload();
    const context = extraForUpload();
    startCountdownRead(contact, context);
  });

  addScreenshotInput.addEventListener("change", async () => {
    addMenu.classList.add("hidden");
    const files = Array.from(addScreenshotInput.files);
    if (!files.length) return;

    addToggle.classList.add("processing");
    addToggle.textContent = "Reading...";

    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    fd.append("contact", contactForUpload());
    fd.append("extra_context", extraForUpload());

    try {
      const r = await fetch("/api/upload-screenshots", { method: "POST", body: fd });
      const d = await r.json();
      if (d.error) {
        statusText.textContent = d.error;
        setTimeout(() => { statusText.textContent = ""; }, 2000);
      }
    } catch (e) {
      statusText.textContent = "Upload failed";
    }

    addScreenshotInput.value = "";
    addToggle.classList.remove("processing");
    addToggle.textContent = "+ Add new";
  });

  // ── Drag-and-drop strip below transcript ─────────────────────────

  const addDropStrip = document.getElementById("addDropStrip");
  const addDropFileInput = document.getElementById("addDropFileInput");

  addDropStrip.addEventListener("click", () => addDropFileInput.click());

  ["dragenter", "dragover"].forEach(evt => {
    addDropStrip.addEventListener(evt, (e) => {
      e.preventDefault();
      addDropStrip.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(evt => {
    addDropStrip.addEventListener(evt, () => addDropStrip.classList.remove("dragover"));
  });

  addDropStrip.addEventListener("drop", (e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith("image/") || f.type.startsWith("video/"));
    if (files.length) uploadAddFiles(files);
  });

  addDropFileInput.addEventListener("change", () => {
    const files = Array.from(addDropFileInput.files);
    addDropFileInput.value = "";
    if (files.length) uploadAddFiles(files);
  });

  async function uploadAddFiles(files) {
    addDropStrip.classList.add("uploading");
    addDropStrip.querySelector(".add-drop-label").textContent = `Reading ${files.length} file${files.length > 1 ? "s" : ""}...`;

    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    fd.append("contact", contactForUpload());
    fd.append("extra_context", extraForUpload());

    try {
      const r = await fetch("/api/upload-screenshots", { method: "POST", body: fd });
      const d = await r.json();
      if (d.error) {
        addDropStrip.querySelector(".add-drop-label").textContent = d.error;
        setTimeout(() => resetDropStrip(), 2000);
      } else {
        addDropStrip.querySelector(".add-drop-label").textContent = "Processing...";
      }
    } catch (e) {
      addDropStrip.querySelector(".add-drop-label").textContent = "Upload failed";
      setTimeout(() => resetDropStrip(), 2000);
    }
    addDropStrip.classList.remove("uploading");
    resetDropStrip();
  }

  function resetDropStrip() {
    addDropStrip.querySelector(".add-drop-label").textContent = "Drop screenshots here to add";
  }

  // ── New Chat button ──────────────────────────────────────────────

  document.getElementById("newChatBtn").addEventListener("click", () => {
    send({ action: "new_chat" });
    if (readContactInput) readContactInput.value = "";
    if (readExtraContext) readExtraContext.value = "";
    if (contactInput) contactInput.value = "";
    if (extraContextEl) extraContextEl.value = "";
    lastTranscriptCount = 0;
    transcriptEl.innerHTML = "";
    repliesEl.innerHTML = "";
    msgCountEl.textContent = "";
    contactLabel.textContent = "";
    coachSection.classList.add("hidden");
    results.classList.add("hidden");
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
