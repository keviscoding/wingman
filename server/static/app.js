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
  const contactSearch = document.getElementById("contactSearch");
  const contactSelect = document.getElementById("contactSelect");
  const analysisToggleBtn = document.getElementById("analysisToggleBtn");
  const results = document.getElementById("results");
  const transcriptEl = document.getElementById("transcript");
  const repliesEl = document.getElementById("replies");
  const msgCountEl = document.getElementById("msgCount");
  const regenBtn = document.getElementById("regenBtn");
  const modelToggle = document.getElementById("modelToggle");
  const tunedVersionBtn = document.getElementById("tunedVersionBtn");
  const trainingToggle = document.getElementById("trainingToggle");
  const kieToggle = document.getElementById("kieToggle");
  const lessonsToggle = document.getElementById("lessonsToggle");
  const lessonsAppliedPill = document.getElementById("lessonsApplied");
  const examplesToggle = document.getElementById("examplesToggle");
  const examplesAppliedPill = document.getElementById("examplesApplied");
  const grokToggle = document.getElementById("grokToggle");
  const grokModeBtn = document.getElementById("grokModeBtn");
  const grokFullBtn = document.getElementById("grokFullBtn");
  const dsToggle = document.getElementById("dsToggle");
  const dsModeBtn = document.getElementById("dsModeBtn");
  const dsVariantBtn = document.getElementById("dsVariantBtn");
  const receptivenessBar = document.getElementById("receptivenessBar");
  const receptivenessSlider = document.getElementById("receptivenessSlider");
  const receptivenessText = document.getElementById("receptivenessText");
  const receptivenessDesc = document.getElementById("receptivenessDesc");
  const presetSelect = document.getElementById("presetSelect");
  const addPresetBtn = document.getElementById("addPresetBtn");
  const exportPresetsBtn = document.getElementById("exportPresetsBtn");
  const importPresetsInput = document.getElementById("importPresetsInput");
  // Baseline-prompt editor modal
  const editBaselineBtn = document.getElementById("editBaselineBtn");
  const baselineModal = document.getElementById("baselineModal");
  const baselineTextarea = document.getElementById("baselineTextarea");
  const baselineIndicator = document.getElementById("baselineIndicator");
  const baselineCharCount = document.getElementById("baselineCharCount");
  const baselineShowOriginal = document.getElementById("baselineShowOriginal");
  const baselineOriginal = document.getElementById("baselineOriginal");
  const baselineSaveBtn = document.getElementById("baselineSaveBtn");
  const baselineResetBtn = document.getElementById("baselineResetBtn");
  const baselineCancelBtn = document.getElementById("baselineCancelBtn");
  const baselineCloseBtn = document.getElementById("baselineCloseBtn");
  // Snapshot of state's baseline values, refreshed on every state tick.
  // We snapshot rather than re-reading state so typing in the textarea
  // doesn't flicker when a 2Hz state broadcast arrives.
  const baselineState = { current: "", factory: "", loaded: false };
  const notifyBtn = document.getElementById("notifyBtn");
  const toastEl = document.getElementById("toast");
  const replyToasts = document.getElementById("replyToasts");
  const replyHistoryNav = document.getElementById("replyHistoryNav");
  const historyPrev = document.getElementById("historyPrev");
  const historyNext = document.getElementById("historyNext");
  const historyLabel = document.getElementById("historyLabel");

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
  let _currentViewedContact = "";
  /** Dedupes system notifications when the same reply batch is re-polled. */
  let lastRepliesNotifyFp = "";
  /** True while user is opening or scrolling a native select menu (focus alone is unreliable on iOS). */
  let contactSelectUiLock = false;
  let presetSelectUiLock = false;
  let lastContactsDomSig = null;
  let lastPresetStateSig = null;
  /** Monotonic server `replies_version`; avoids fragile JSON.stringify dedupe on polled replies. */
  let lastSeenRepliesVersion = -1;
  let lastServerSessionId = null;

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

  const notifyIconUrl = () =>
    (typeof location !== "undefined" ? new URL("/static/icon-192.png", location.origin).href : undefined);

  /** WebKit (Safari / iOS) often only supports the callback form; Promise-only can resolve without a prompt. */
  function requestNotificationPermissionCompat() {
    return new Promise((resolve) => {
      if (typeof Notification === "undefined") {
        resolve("unsupported");
        return;
      }
      const cur = Notification.permission;
      if (cur === "granted" || cur === "denied") {
        resolve(cur);
        return;
      }
      let settled = false;
      const finish = (r) => {
        if (settled) return;
        settled = true;
        resolve(r === "granted" || r === "denied" || r === "default" ? r : Notification.permission);
      };
      try {
        const ret = Notification.requestPermission((result) => finish(result));
        if (ret !== undefined && ret !== null && typeof ret.then === "function") {
          ret.then((result) => finish(result)).catch(() => finish(Notification.permission));
        }
      } catch (e) {
        finish("denied");
      }
    });
  }

  function isStandalonePwa() {
    try {
      return (
        window.matchMedia("(display-mode: standalone)").matches ||
        window.matchMedia("(display-mode: fullscreen)").matches ||
        (typeof navigator !== "undefined" && navigator.standalone === true)
      );
    } catch (_) {
      return false;
    }
  }

  function updateNotifyBtn() {
    if (!notifyBtn) return;
    if (typeof Notification === "undefined") {
      notifyBtn.hidden = false;
      notifyBtn.title = "Notifications are not available in this browser";
      notifyBtn.classList.remove("notify-on");
      return;
    }
    notifyBtn.hidden = false;
    if (Notification.permission === "granted") {
      notifyBtn.title = "Reply alerts on — tap for a test notification";
      notifyBtn.classList.add("notify-on");
    } else if (Notification.permission === "denied") {
      notifyBtn.title = "Notifications blocked — iPhone: Settings → Apps → Safari → Notifications, or site settings";
      notifyBtn.classList.remove("notify-on");
    } else {
      notifyBtn.title = "Tap to allow notifications when replies are ready (iPhone: use Home Screen app)";
      notifyBtn.classList.remove("notify-on");
    }
  }

  if (notifyBtn) {
    notifyBtn.addEventListener("click", async () => {
      if (typeof Notification === "undefined") {
        statusText.textContent =
          "This browser does not support notifications. Try Safari on iPhone, or Chrome/Edge on desktop.";
        statusBanner.classList.add("active");
        return;
      }
      if (Notification.permission === "granted") {
        try {
          new Notification("Wingman", {
            body: "You will see this when new reply options are ready.",
            tag: "wingman-test",
            icon: notifyIconUrl(),
          });
        } catch (_) {}
        return;
      }
      if (Notification.permission === "denied") {
        statusText.textContent =
          "Notifications are off for this site. On iPhone: Settings → Apps → Safari → Notifications, or open the site in Safari (aA) → Website Settings.";
        statusBanner.classList.add("active");
        return;
      }
      if (!window.isSecureContext) {
        statusText.textContent = "Notifications require HTTPS (secure connection).";
        statusBanner.classList.add("active");
        return;
      }

      const before = Notification.permission;
      const p = await requestNotificationPermissionCompat();
      updateNotifyBtn();

      if (p === "granted") {
        try {
          new Notification("Wingman", {
            body: "Alerts enabled — switch away while generating to get notified.",
            tag: "wingman-test",
            icon: notifyIconUrl(),
          });
        } catch (_) {}
        statusText.textContent = "Notifications allowed — you will get alerts when replies are ready.";
        statusBanner.classList.add("active");
        return;
      }

      if (p === "denied") {
        statusText.textContent = "Notifications were blocked. You can allow them in browser or system Settings.";
        statusBanner.classList.add("active");
        return;
      }

      if (p === "default" && before === "default") {
        const ios = typeof navigator !== "undefined" && /iPhone|iPad|iPod/i.test(navigator.userAgent);
        if (ios && !isStandalonePwa()) {
          statusText.textContent =
            "iPhone: Add Wingman to your Home Screen (Share → Add to Home Screen), open from the icon, then tap the bell again.";
        } else {
          statusText.textContent =
            "No permission prompt appeared. Try Settings → Safari → Advanced, or allow notifications for this website in site settings.";
        }
        statusBanner.classList.add("active");
      }
    });
    updateNotifyBtn();
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
    ws.onopen = () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      lastSeenRepliesVersion = -1;
      void pollStateFromApi();
    };
    ws.onclose = () => { reconnectTimer = setTimeout(connect, 2000); };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => handle(JSON.parse(e.data));
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  let _lastUnreadSet = new Set();

  function showReplyToast(contact) {
    if (!replyToasts) return;
    if (replyToasts.querySelectorAll(".reply-toast").length >= 3) {
      replyToasts.firstChild?.remove();
    }
    const el = document.createElement("div");
    el.className = "reply-toast";
    el.innerHTML = `<span class="toast-dot"></span><span class="toast-text">Replies ready for <b>${esc(contact)}</b></span><span class="toast-close">&times;</span>`;
    el.querySelector(".toast-text").addEventListener("click", () => {
      if (readContactInput) readContactInput.value = contact;
      if (contactInput) contactInput.value = contact;
      lastTranscriptCount = 0;
      send({ action: "load_contact", contact });
      el.remove();
    });
    el.querySelector(".toast-close").addEventListener("click", (e) => {
      e.stopPropagation();
      el.remove();
    });
    replyToasts.appendChild(el);
  }

  function updateUnreadBadges(unreadList) {
    const newSet = new Set(unreadList || []);
    const added = [...newSet].filter(c => !_lastUnreadSet.has(c));
    _lastUnreadSet = newSet;

    contactsList.querySelectorAll(".contact-item").forEach(el => {
      const name = el.dataset.contact;
      el.classList.toggle("has-new-replies", newSet.has(name));
    });

    if (added.length > 0) {
      // Clear search so the new reply is visible
      if (contactSearch && contactSearch.value) {
        contactSearch.value = "";
        filterContactsBySearch();
      }

      for (const contact of added) {
        showReplyToast(contact);
        const item = contactsList.querySelector(`.contact-item[data-contact="${CSS.escape(contact)}"]`);
        if (item) item.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }
  }

  function handle(msg) {
    if (msg.type === "status") handleStatus(msg);
    if (msg.type === "transcript") renderTranscript(msg.messages);
    if (msg.type === "reply_chunk") {
      if (!msg.contact || msg.contact === _currentViewedContact) {
        renderStreamChunk(msg.text);
      }
    }
    if (msg.type === "replies") {
      if (typeof msg.replies_version === "number") {
        lastSeenRepliesVersion = msg.replies_version;
      }
      if (msg.contact && msg.contact !== _currentViewedContact) return;
      if (msg.options && msg.options.length) {
        renderReplies(msg.options, msg.read, msg.advice);
      } else {
        repliesEl.innerHTML = "";
        coachRead.textContent = "";
        coachAdvice.textContent = "";
      }
    }
  }

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

  let _genTimerInterval = null, _genStartTime = null;

  function handleStatus(s) {
    const state = s.status || s.state || "idle";
    isHeadless = s.headless || false;
    const prevContact = _currentViewedContact;
    _currentViewedContact = s.contact || "";

    // Snapshot baseline-prompt values from state so the modal has
    // fresh data to show. Only stored; re-read on modal open so user
    // edits aren't clobbered by 2Hz state broadcasts.
    if (typeof s.default_reply_system_prompt === "string") {
      baselineState.factory = s.default_reply_system_prompt;
    }
    if (typeof s.custom_reply_system_prompt === "string") {
      baselineState.current = s.custom_reply_system_prompt;
    }
    baselineState.loaded = true;
    // Visually mark the trigger button when a custom override is active
    if (editBaselineBtn) {
      editBaselineBtn.classList.toggle("has-override", !!baselineState.current);
      editBaselineBtn.title = baselineState.current
        ? "Baseline CUSTOMIZED — click to view/edit or reset"
        : "Edit the baseline (No goal) behavior — the system prompt used when no goal is selected";
    }

    // Sync global-lock state FIRST (it's independent of which chat we
    // view). Any value change → re-render the badge + button.
    const serverGlobal = (s.global_extra_context || "").trim();
    if (serverGlobal !== _globalLockValue) {
      _globalLockValue = serverGlobal;
      renderGlobalBadge();
    }

    // Sync the extra-context lock UI when the viewed chat changes, OR
    // when server state updates the lock for the same chat. Don't stomp
    // user's in-flight typing unless the chat actually changed.
    const contactChanged = prevContact !== _currentViewedContact;
    const serverLocked = (s.locked_extra_context || "").trim();
    if (contactChanged) {
      _extraLockContact = _currentViewedContact;
      if (extraRequestInput) {
        extraRequestInput.value = serverLocked;
      }
      setLockUI(!!serverLocked);
    } else if (_extraLockContact === _currentViewedContact
               && document.activeElement !== extraRequestInput
               && serverLocked !== (extraRequestInput ? (extraRequestInput.value || "").trim() : "")) {
      // Server drifted from our UI (e.g. another tab edited it) and the
      // user isn't currently typing — reconcile.
      if (extraRequestInput) extraRequestInput.value = serverLocked;
      setLockUI(!!serverLocked);
    } else {
      // Same chat, user typing — just keep lock icon in sync with state.
      setLockUI(_extraLocked && serverLocked === (extraRequestInput ? (extraRequestInput.value || "").trim() : ""));
    }

    if (state === "generating" && !_genStartTime) {
      _genStartTime = Date.now();
      if (_genTimerInterval) clearInterval(_genTimerInterval);
      _genTimerInterval = setInterval(() => {
        if (!_genStartTime) return;
        const sec = Math.round((Date.now() - _genStartTime) / 1000);
        const base = statusText.textContent.replace(/\s*\(\d+s\)$/, "");
        statusText.textContent = `${base} (${sec}s)`;
      }, 1000);
    }
    if (state !== "generating" && _genStartTime) {
      clearInterval(_genTimerInterval);
      _genTimerInterval = null;
      _genStartTime = null;
    }

    const msgs = isHeadless ? headlessMsgs : desktopMsgs;
    let statusMsg = msgs[state] || state;
    if (state === "collecting" && s.collecting_count) {
      statusMsg = `Reading — ${s.collecting_count} messages so far. Keep scrolling, click Done when finished.`;
    }
    if (state === "generating" && s.messages) {
      const model = (s.reply_model || "pro").toUpperCase();
      const count = s.messages;
      const info = count > 30 ? ` — ${count} msgs (summarized)` : ` — ${count} msgs`;
      statusMsg = `Generating with ${model}${info}...`;
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
      const line = "Chat with " + s.contact;
      contactLabel.textContent = line;
      contactLabel.title = line;
      if (readContactInput && !readContactInput.value.trim()) readContactInput.value = s.contact;
      if (contactInput && !contactInput.value.trim()) contactInput.value = s.contact;
    } else {
      contactLabel.textContent = "";
      contactLabel.title = "";
    }

    if (contactSelect) {
      const contactHtml =
        s.contacts && s.contacts.length
          ? '<option value="">Chats…</option>' +
            s.contacts
              .map(
                (c) =>
                  `<option value="${escA(c)}"${c === s.contact ? " selected" : ""}>${esc(c)}</option>`,
              )
              .join("")
          : '<option value="">No saved chats</option>';
      const contactBusy =
        document.activeElement === contactSelect || contactSelectUiLock;
      if (!contactBusy && contactSelect.innerHTML !== contactHtml) {
        contactSelect.innerHTML = contactHtml;
      }
    }

    const contactsDomSig = JSON.stringify(s.contacts || []) + "\0" + String(s.contact || "");
    if (!contactSelectUiLock && contactsDomSig !== lastContactsDomSig) {
      lastContactsDomSig = contactsDomSig;
      if (s.contacts && s.contacts.length) {
        const previews = s.contact_previews || {};
        const sorted = [...s.contacts].sort((a, b) => {
          const pa = previews[a] || {};
          const pb = previews[b] || {};
          return (pb.last_generated_at || 0) - (pa.last_generated_at || 0);
        });
        contactsList.innerHTML = sorted.map(c => {
          const p = previews[c] || {};
          const preview = p.preview || "";
          const recep = p.receptiveness ?? 5;
          const dotClass = recep <= 3 ? "cold" : recep <= 6 ? "warm" : "hot";
          const isActive = c === s.contact;
          const leadTag = p.lead_tag ? `<span class="lead-tag ${esc(p.lead_tag)}">${recep}/10</span>` : "";
          const activityTs = p.last_activity_at || p.last_generated_at || 0;
          const ago = timeAgo(activityTs);
          const agoHtml = ago ? `<span class="contact-time-ago" title="Last activity">${esc(ago)}</span>` : "";
          const bad = !!p.bad_outcome;
          const csReady = !!p.case_study_ready;
          const csAnalyzing = !!p.case_study_analyzing;
          const flagTitle = bad
            ? (csAnalyzing ? "Flagged — analyzing..." : (csReady ? "Flagged — lessons active" : "Flagged"))
            : "Flag this chat as a bad outcome";
          const flagCls = "contact-flag" + (bad ? " flagged" : "") + (csAnalyzing ? " analyzing" : "") + (csReady ? " ready" : "");
          const badNameBadge = bad
            ? `<span class="bad-outcome-badge" title="${esc(flagTitle)}">${csAnalyzing ? "…" : (csReady ? "LESSON" : "FLAG")}</span>`
            : "";
          const bottomHtml = (preview || ago)
            ? `<div class="contact-bottom">` +
                (preview ? `<span class="contact-preview">${esc(preview)}</span>` : `<span class="contact-preview"></span>`) +
                agoHtml +
              `</div>`
            : "";
          return `<div class="contact-item${isActive ? " active" : ""}${bad ? " bad-outcome" : ""}" data-contact="${esc(c)}">` +
            `<div class="contact-top">` +
            `<span class="contact-recep-dot ${dotClass}"></span>` +
            `<span class="contact-name">${esc(c)}${leadTag}${badNameBadge}</span>` +
            `<span class="contact-actions">` +
            `<span class="${flagCls}" data-flag="${esc(c)}" title="${esc(flagTitle)}">&#9888;</span>` +
            `<span class="contact-rename" data-rename="${esc(c)}" title="Rename">&#9998;</span>` +
            `<span class="contact-delete" data-del="${esc(c)}" title="Delete">\u2715</span>` +
            `</span>` +
            `</div>` +
            bottomHtml +
            `</div>`;
        }).join("");
        contactsList.querySelectorAll(".contact-item").forEach(el => {
          el.addEventListener("click", (e) => {
            if (
              e.target.classList.contains("contact-delete") ||
              e.target.classList.contains("contact-rename") ||
              e.target.classList.contains("contact-flag")
            ) return;
            const contact = el.dataset.contact;
            if (readContactInput) readContactInput.value = contact;
            if (contactInput) contactInput.value = contact;
            lastTranscriptCount = 0;
            send({ action: "load_contact", contact });
            // Dismiss toasts for this contact
            if (replyToasts) {
              replyToasts.querySelectorAll(".reply-toast").forEach(t => {
                if (t.textContent.includes(contact)) t.remove();
              });
            }
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
        contactsList.querySelectorAll(".contact-flag").forEach(el => {
          el.addEventListener("click", (e) => {
            e.stopPropagation();
            const contact = el.dataset.flag;
            if (!contact) return;
            const alreadyFlagged = el.classList.contains("flagged");
            if (alreadyFlagged) {
              if (confirm(`Remove bad-outcome flag from ${contact}? Its case study will be deleted too.`)) {
                send({ action: "unflag_bad_outcome", contact });
              }
              return;
            }
            const note = prompt(
              `Flag ${contact} as a BAD OUTCOME?\n\n` +
              `Only flag chats that went dead because of our game — not flakes/busy.\n\n` +
              `Optional short note (what went wrong in your own words):`,
              ""
            );
            if (note === null) return;
            send({ action: "flag_bad_outcome", contact, note: (note || "").trim() });
          });
        });
      } else {
        contactsList.innerHTML = '<p class="empty-small">No chats yet</p>';
      }
      filterContactsBySearch();
    }

    if (s.messages > 0 || s.has_replies) results.classList.remove("hidden");
    const dz = document.getElementById("dropZone");
    if (dz) dz.classList.toggle("collapsed", s.messages > 0 || s.has_replies);

    if (s.presets) {
      lastPresetsList = s.presets;
      const current = presetSelect.value;
      const dp = typeof s.default_preset === "number" ? s.default_preset : -1;
      const presetHtml =
        `<option value="-1">No goal${dp === -1 ? " ★" : ""}</option>` +
        s.presets
          .map(
            (p, i) =>
              `<option value="${i}"${i === s.active_preset ? " selected" : ""}>${esc(p.name)}${i === dp ? " ★" : ""}</option>`,
          )
          .join("");
      const presetSig = JSON.stringify(s.presets) + "|" + String(s.active_preset);
      const presetBusy =
        document.activeElement === presetSelect || presetSelectUiLock;
      if (!presetBusy && presetSelect.innerHTML !== presetHtml) {
        presetSelect.innerHTML = presetHtml;
        if (current !== presetSelect.value) presetSelect.value = String(s.active_preset);
        lastPresetStateSig = presetSig;
        updatePresetSelectTitle();
      } else if (!presetBusy && presetSig !== lastPresetStateSig) {
        lastPresetStateSig = presetSig;
        updatePresetSelectTitle();
      }
    }

    if (modelToggle && s.reply_model) {
      modelToggle.querySelectorAll(".model-btn").forEach(btn => {
        // The version-selector button is inside modelToggle but isn't a
        // model choice itself — skip the active/disabled handling.
        if (btn.id === "tunedVersionBtn") return;
        btn.classList.toggle("active", btn.dataset.model === s.reply_model);
        // Tuned button is disabled until training finishes + endpoint is wired
        if (btn.dataset.model === "tuned") {
          const ready = !!s.tuned_configured;
          btn.classList.toggle("disabled", !ready);
          btn.title = ready
            ? "Your fine-tuned Gemini 2.5 Flash — trained on Pro outputs, fast + personalized."
            : "Tuned model not ready yet — fine-tuning job is still running or hasn't been kicked off.";
        }
      });
    }
    if (tunedVersionBtn) {
      const ver = (s.tuned_version || "v3").toLowerCase();
      const avail = Array.isArray(s.tuned_versions_available) ? s.tuned_versions_available : ["v3"];
      tunedVersionBtn.textContent = ver;
      tunedVersionBtn.dataset.version = ver;
      tunedVersionBtn.dataset.available = avail.join(",");
      // Only visible/relevant when Tuned is the active model
      const tunedActive = s.reply_model === "tuned";
      tunedVersionBtn.classList.toggle("visible", tunedActive);
      const notes = {
        "v1": "628 pairs · Pro-labels only · short-context",
        "v2": "1185 pairs · +528 Alex transcript fragments · 12-msg context",
        "v3": "3576 pairs · full arcs, progressive context, multi-woman aware",
        "v4": "2900 pairs · PRO RE-DISTILLED · playbook-in-training · hygiene-filtered",
      };
      tunedVersionBtn.title = `Tuned ${ver.toUpperCase()}: ${notes[ver] || ""} · Click to cycle.`;
    }
    if (trainingToggle && typeof s.use_training === "boolean") {
      trainingToggle.classList.toggle("active", s.use_training);
    }
    if (kieToggle) {
      kieToggle.classList.toggle("active", !!s.use_kie);
      // Disable visually when KIE isn't configured in .env
      if (typeof s.kie_configured === "boolean" && !s.kie_configured) {
        kieToggle.classList.add("disabled");
        kieToggle.title = "Set KIE_API_KEY in .env to enable";
      } else {
        kieToggle.classList.remove("disabled");
      }
    }
    if (grokToggle) {
      grokToggle.classList.toggle("active", !!s.use_grok);
      if (typeof s.grok_configured === "boolean" && !s.grok_configured) {
        grokToggle.classList.add("disabled");
        grokToggle.title = "Set XAI_API_KEY in .env to enable";
      } else {
        grokToggle.classList.remove("disabled");
        const mode = s.grok_mode || "multi-agent";
        const tips = {
          "multi-agent": "Grok 4.20 Multi-Agent (Lucas + Harper + Benjamin + Grok). Best creative quality. ~10-30s before first token.",
          "reasoning": "Grok 4.20 Reasoning (single-agent). Fast, no Lucas. Good for quick generations.",
          "non-reasoning": "Grok 4.20 Non-Reasoning (fastest, lowest quality).",
        };
        grokToggle.title = (s.use_grok ? "ON — " : "OFF — click to enable. ") + (tips[mode] || "");
      }
    }
    if (grokModeBtn) {
      const mode = s.grok_mode || "multi-agent";
      const label = mode === "multi-agent" ? "MA" : (mode === "reasoning" ? "R" : "NR");
      grokModeBtn.textContent = label;
      grokModeBtn.dataset.mode = mode;
      const shortTips = {
        "multi-agent": "Multi-Agent (Lucas active)",
        "reasoning": "Reasoning (single-agent)",
        "non-reasoning": "Non-Reasoning (fastest)",
      };
      grokModeBtn.title = `Grok mode: ${shortTips[mode] || mode}. Click to cycle.`;
      if (grokToggle && grokToggle.classList.contains("active")) {
        grokModeBtn.classList.add("visible");
      } else {
        grokModeBtn.classList.remove("visible");
      }
    }
    if (grokFullBtn) {
      const on = !!s.grok_full_training;
      grokFullBtn.classList.toggle("active", on);
      const files = s.grok_corpus_files || 0;
      const chars = s.grok_corpus_chars || 0;
      const kTokens = Math.round(chars / 4 / 1000);
      grokFullBtn.title = on
        ? `FULL training ON — all ${files} transcripts (~${kTokens}k tokens) sent on every Grok call. Cached after first call.`
        : `FULL training OFF — Grok gets only the 9k Master Playbook. Click to enable full corpus (${files} files, ~${kTokens}k tokens).`;
      if (grokToggle && grokToggle.classList.contains("active")) {
        grokFullBtn.classList.add("visible");
      } else {
        grokFullBtn.classList.remove("visible");
      }
    }
    if (dsToggle) {
      dsToggle.classList.toggle("active", !!s.use_deepseek);
      if (typeof s.deepseek_configured === "boolean" && !s.deepseek_configured) {
        dsToggle.classList.add("disabled");
        dsToggle.title = "Set ATLASCLOUD_API_KEY in .env to enable";
      } else {
        dsToggle.classList.remove("disabled");
        const mode = s.deepseek_mode || "normal";
        dsToggle.title = (s.use_deepseek ? "ON — " : "OFF — ") +
          `DeepSeek V4 Pro via Atlas (${mode}). ${mode === "full" ? "Full 620k-token corpus cached per call." : "Playbook + chat context only."}`;
      }
    }
    if (dsModeBtn) {
      const mode = s.deepseek_mode || "normal";
      dsModeBtn.textContent = mode === "full" ? "F" : "N";
      dsModeBtn.dataset.mode = mode;
      dsModeBtn.title = mode === "full"
        ? "Mode: FULL — 620k-token training corpus sent on every call. Click to switch to normal."
        : "Mode: NORMAL — playbook + chat only. Click to switch to full-training mode.";
      if (dsToggle && dsToggle.classList.contains("active")) {
        dsModeBtn.classList.add("visible");
      } else {
        dsModeBtn.classList.remove("visible");
      }
    }
    if (dsVariantBtn) {
      const variant = (s.deepseek_variant || "pro").toLowerCase();
      dsVariantBtn.textContent = variant === "flash" ? "Fl" : "Pro";
      dsVariantBtn.dataset.variant = variant;
      dsVariantBtn.title = variant === "flash"
        ? "Variant: FLASH — faster inference. Click to switch to Pro."
        : "Variant: PRO — deeper reasoning. Click to switch to Flash.";
      if (dsToggle && dsToggle.classList.contains("active")) {
        dsVariantBtn.classList.add("visible");
      } else {
        dsVariantBtn.classList.remove("visible");
      }
    }
    if (lessonsToggle) {
      const on = typeof s.use_lessons === "boolean" ? s.use_lessons : true;
      lessonsToggle.classList.toggle("active", on);
      const count = typeof s.case_study_count === "number" ? s.case_study_count : 0;
      const building = Array.isArray(s.case_study_building) ? s.case_study_building.length : 0;
      const label = building > 0
        ? `Lessons (${count}+${building}…)`
        : (count > 0 ? `Lessons (${count})` : "Lessons");
      lessonsToggle.textContent = label;
      lessonsToggle.title = count === 0
        ? "Flag chats as bad outcomes with the ⚠ icon — the model will learn from them"
        : `${count} case stud${count === 1 ? "y" : "ies"} active${building > 0 ? ` • ${building} analyzing…` : ""}`;
      lessonsToggle.classList.toggle("disabled", count === 0 && !on);
    }
    if (lessonsAppliedPill) {
      const applied = Array.isArray(s.applied_case_studies) ? s.applied_case_studies : [];
      if (applied.length > 0) {
        const top = applied[0];
        lessonsAppliedPill.classList.remove("hidden");
        lessonsAppliedPill.textContent = `📚 ${applied.length} lesson${applied.length > 1 ? "s" : ""} applied`;
        const detail = applied
          .map(a => `${a.contact} (${(typeof a.similarity === "number" ? a.similarity : 0).toFixed(2)})`)
          .join("\n");
        lessonsAppliedPill.title =
          "These flagged chats shaped the advice for this generation:\n" + detail +
          "\n\nLook for '[Lesson applied: ...]' inside the coach's advice for a direct citation.";
        lessonsAppliedPill.dataset.topContact = (top && top.contact) || "";
      } else {
        lessonsAppliedPill.classList.add("hidden");
        lessonsAppliedPill.textContent = "";
        lessonsAppliedPill.title = "";
      }
    }
    if (examplesToggle) {
      const on = typeof s.use_examples === "boolean" ? s.use_examples : true;
      examplesToggle.classList.toggle("active", on);
      const count = typeof s.examples_count === "number" ? s.examples_count : 0;
      const building = !!s.examples_building;
      const progress = Array.isArray(s.examples_build_progress) ? s.examples_build_progress : [0, 0];
      let label;
      if (building) {
        label = progress[1] > 0
          ? `Examples (${progress[0]}/${progress[1]}…)`
          : "Examples (building…)";
      } else if (count > 0) {
        label = `Examples (${count})`;
      } else {
        label = "Examples";
      }
      examplesToggle.textContent = label;
      examplesToggle.title = count === 0 && !building
        ? "No examples yet — they bootstrap from your existing chats on first run"
        : building
          ? `Building library from your chats: ${progress[0]}/${progress[1]}…`
          : `${count} reply examples active. Right-click to rebuild from latest chats.`;
      examplesToggle.classList.toggle("building", building);
    }
    if (examplesAppliedPill) {
      const applied = Array.isArray(s.applied_examples) ? s.applied_examples : [];
      if (applied.length > 0) {
        examplesAppliedPill.classList.remove("hidden");
        examplesAppliedPill.textContent = `⭐ ${applied.length} example${applied.length > 1 ? "s" : ""} applied`;
        const detail = applied
          .map(a => {
            const sim = (typeof a.similarity === "number" ? a.similarity : 0).toFixed(2);
            const reply = (a.reply || "").slice(0, 80);
            return `${a.contact} (${sim}):\n  "${reply}"`;
          })
          .join("\n\n");
        examplesAppliedPill.title =
          "These past replies of yours anchored the style for this generation:\n\n" + detail;
      } else {
        examplesAppliedPill.classList.add("hidden");
        examplesAppliedPill.textContent = "";
        examplesAppliedPill.title = "";
      }
    }
    if (receptivenessBar) {
      if (s.contact) {
        receptivenessBar.classList.add("visible");
        const v = typeof s.receptiveness === "number" ? s.receptiveness : 5;
        receptivenessSlider.value = v;
        updateReceptivenessLabel(v);
      } else {
        receptivenessBar.classList.remove("visible");
      }
    }

    if (s.unread_replies) {
      updateUnreadBadges(s.unread_replies);
    }
    if (replyHistoryNav) {
      const count = s.reply_history_count || 0;
      const idx = s.reply_history_index || 0;
      const modes = Array.isArray(s.reply_history_modes) ? s.reply_history_modes : [];
      if (count > 1) {
        replyHistoryNav.classList.remove("hidden");
        const mode = modes[idx] || "";
        const modeTag = mode === "lessons_on"
          ? " <span class=\"history-mode on\" title=\"Generated with case studies\">L+</span>"
          : (mode === "lessons_off" ? " <span class=\"history-mode off\" title=\"Generated without case studies\">L-</span>" : "");
        historyLabel.innerHTML = `${idx + 1} of ${count}${modeTag}`;
        historyPrev.disabled = idx <= 0;
        historyNext.disabled = idx >= count - 1;
      } else {
        replyHistoryNav.classList.add("hidden");
      }
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

  function applyRepliesFromPoll(d) {
    if (typeof d.replies_version === "number") {
      if (d.replies_version < lastSeenRepliesVersion) return;
      if (d.replies_version === lastSeenRepliesVersion) return;
      lastSeenRepliesVersion = d.replies_version;
      if (d.replies && d.replies.length) {
        renderReplies(d.replies, d.read, d.advice);
      } else {
        repliesEl.innerHTML = "";
        coachRead.textContent = "";
        coachAdvice.textContent = "";
      }
      return;
    }
    if (d.replies && d.replies.length) {
      renderReplies(d.replies, d.read, d.advice);
    }
  }

  async function pollStateFromApi() {
    try {
      const d = await (await fetch("/api/state")).json();
      if (d.server_session_id && d.server_session_id !== lastServerSessionId) {
        lastServerSessionId = d.server_session_id;
        lastSeenRepliesVersion = -1;
      }
      handleStatus(d);
      if (d.transcript) renderTranscript(d.transcript);
      applyRepliesFromPoll(d);
    } catch {}
  }

  setInterval(pollStateFromApi, 2000);
  void pollStateFromApi();

  // Deep-link: #contact=Name  -> open that chat (used by notification clicks)
  function loadContactFromHash() {
    const raw = (window.location.hash || "").replace(/^#/, "");
    if (!raw) return;
    const params = new URLSearchParams(raw);
    const c = params.get("contact");
    if (!c) return;
    const contact = decodeURIComponent(c);
    if (!contact) return;
    if (readContactInput) readContactInput.value = contact;
    if (contactInput) contactInput.value = contact;
    lastTranscriptCount = 0;
    send({ action: "load_contact", contact });
    try { window.history.replaceState(null, "", window.location.pathname + window.location.search); } catch {}
  }
  window.addEventListener("hashchange", loadContactFromHash);
  setTimeout(loadContactFromHash, 150);

  // ── Rendering ─────────────────────────────────────────────────────

  let lastTranscriptCount = 0;
  let lastPresetsList = [];

  function updatePresetSelectTitle() {
    if (!presetSelect) return;
    const idx = parseInt(presetSelect.value, 10);
    if (idx < 0 || !lastPresetsList.length) {
      presetSelect.title = "Choose a goal";
      return;
    }
    const p = lastPresetsList[idx];
    if (!p) {
      presetSelect.title = "";
      return;
    }
    const n = (p.name || "").trim();
    const instr = (p.instruction || "").trim();
    presetSelect.title = instr ? `${n}\n\n${instr}` : n;
  }

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

  function maybeNotifyRepliesReady(options) {
    if (!options || !options.length) return;
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    const fp = JSON.stringify(options.map(o => o.text));
    if (fp === lastRepliesNotifyFp) return;
    lastRepliesNotifyFp = fp;
    if (document.visibilityState === "visible" && document.hasFocus()) return;
    try {
      new Notification("Wingman", {
        body: "Reply options are ready — open the app to pick one.",
        tag: "wingman-replies",
        icon: notifyIconUrl(),
      });
    } catch (_) {}
  }

  function tryParseStreamJSON(raw) {
    let text = raw.trim();
    const fence = text.match(/```(?:json)?\s*([\s\S]*?)(?:```|$)/);
    if (fence) text = fence[1].trim();
    const m = text.match(/\{[\s\S]*\}/);
    if (!m) return null;
    try {
      return JSON.parse(m[0]);
    } catch {
      // Incomplete JSON — try to close it off for partial parse
      let s = m[0];
      // Close open strings, arrays, objects
      const opens = (s.match(/\{/g) || []).length - (s.match(/\}/g) || []).length;
      const openArr = (s.match(/\[/g) || []).length - (s.match(/\]/g) || []).length;
      // Trim trailing comma or partial key
      s = s.replace(/,\s*$/, "");
      // Close incomplete string
      if ((s.match(/"/g) || []).length % 2 !== 0) s += '"';
      for (let i = 0; i < openArr; i++) s += "]";
      for (let i = 0; i < opens; i++) s += "}";
      try { return JSON.parse(s); } catch { return null; }
    }
  }

  function renderStreamChunk(raw) {
    results.classList.remove("hidden");
    const data = tryParseStreamJSON(raw);
    if (!data) return;

    if (data.read) {
      coachRead.textContent = data.read;
      if (!isMobileHost()) coachSection.classList.remove("hidden");
    }
    if (data.advice) {
      coachAdvice.textContent = "\u2192 " + data.advice;
    }

    const items = data.replies || [];
    if (!items.length) return;

    repliesEl.innerHTML = items.map((o, i) => {
      if (!o || !o.text) return "";
      const whyHtml = o.why ? `<div class="why">${esc(o.why)}</div>` : "";
      const hint = "Click to copy";
      return `<div class="reply-card streaming" data-text="${escA(o.text)}">` +
        `<span class="label">${esc(o.label || "...")}</span>` +
        `<div class="text">${esc(o.text)}</div>` +
        `${whyHtml}` +
        `<div class="hint">${hint}</div></div>`;
    }).filter(Boolean).join("");

    repliesEl.querySelectorAll(".reply-card").forEach(c =>
      c.addEventListener("click", () => copy(c.dataset.text))
    );
  }

  function renderReplies(options, read, advice) {
    if (!options || !options.length) return;
    results.classList.remove("hidden");

    if (read || advice) {
      coachRead.textContent = read || "";
      coachAdvice.textContent = advice ? "\u2192 " + advice : "";
      if (isMobileHost()) {
        coachSection.classList.add("hidden");
        if (analysisToggleBtn) {
          analysisToggleBtn.classList.add("visible");
          analysisToggleBtn.textContent = "Show analysis";
        }
      } else {
        coachSection.classList.remove("hidden");
        if (analysisToggleBtn) analysisToggleBtn.classList.remove("visible");
      }
    } else if (analysisToggleBtn) {
      analysisToggleBtn.classList.remove("visible");
    }

    repliesEl.innerHTML = options.map((o, i) => {
      const whyHtml = o.why ? `<div class="why">${esc(o.why)}</div>` : "";
      const hint = "Click to copy";
      return `<div class="reply-card" data-text="${escA(o.text)}">` +
        `<span class="label">${esc(o.label)}</span>` +
        `<div class="text">${esc(o.text)}</div>` +
        `${whyHtml}` +
        `<div class="hint">${hint}</div></div>`;
    }).join("");
    repliesEl.querySelectorAll(".reply-card").forEach(c =>
      c.addEventListener("click", () => copy(c.dataset.text))
    );
    maybeNotifyRepliesReady(options);
  }

  function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function escA(s) { return s.replace(/"/g, "&quot;"); }
  function timeAgo(tsSec) {
    if (!tsSec) return "";
    const secs = Math.max(0, Math.floor(Date.now() / 1000 - tsSec));
    if (secs < 60) return "now";
    const mins = Math.floor(secs / 60);
    if (mins < 60) return mins + "m";
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + "h";
    const days = Math.floor(hrs / 24);
    if (days < 7) return days + "d";
    const weeks = Math.floor(days / 7);
    if (weeks < 5) return weeks + "w";
    const months = Math.floor(days / 30);
    if (months < 12) return months + "mo";
    const years = Math.floor(days / 365);
    return years + "y";
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); } catch {
      const t = document.createElement("textarea"); t.value = text;
      t.style.cssText = "position:fixed;left:-9999px";
      document.body.appendChild(t); t.select(); document.execCommand("copy");
      document.body.removeChild(t);
    }
    send({ action: "clear_unread" });
    if (replyToasts) {
      replyToasts.querySelectorAll(".reply-toast").forEach(t => t.remove());
    }
    toastEl.classList.add("show");
    setTimeout(() => toastEl.classList.remove("show"), 1500);
  }

  // ── Contact search ────────────────────────────────────────────────

  function filterContactsBySearch() {
    if (!contactSearch) return;
    const q = contactSearch.value.toLowerCase().trim();
    contactsList.querySelectorAll(".contact-item").forEach(el => {
      const name = (el.dataset.contact || "").toLowerCase();
      el.style.display = !q || name.includes(q) ? "" : "none";
    });
  }

  if (contactSearch) {
    contactSearch.addEventListener("input", filterContactsBySearch);
  }

  // ── Events ────────────────────────────────────────────────────────

  const extraRequestInput = document.getElementById("extraRequestInput");
  const lockExtraBtn = document.getElementById("lockExtraBtn");
  const globalLockBtn = document.getElementById("globalLockBtn");
  const globalLockBadge = document.getElementById("globalLockBadge");

  // Tracks whether the current chat's extra-context is locked (sticky).
  // Updated from server state (s.locked_extra_context) whenever we switch
  // chats; toggled locally via the lock button.
  let _extraLocked = false;
  let _extraLockContact = "";  // which chat the current lock state belongs to
  let _globalLockValue = "";    // current global-lock text shown as badge

  function setLockUI(locked) {
    _extraLocked = !!locked;
    if (!lockExtraBtn || !extraRequestInput) return;
    lockExtraBtn.classList.toggle("active", _extraLocked);
    extraRequestInput.classList.toggle("locked", _extraLocked);
    lockExtraBtn.innerHTML = _extraLocked ? "&#128274;" : "&#128275;";  // 🔒 / 🔓
    lockExtraBtn.title = _extraLocked
      ? "Locked — this extra context applies to every generation for this chat. Click to unlock."
      : "Lock this extra context to this chat so every generation uses it.";
  }

  if (lockExtraBtn && extraRequestInput) {
    lockExtraBtn.addEventListener("click", () => {
      if (!_currentViewedContact) {
        toast("Open a chat first to lock extra context to it");
        return;
      }
      if (_extraLocked) {
        // unlock → clear server-side meta, keep input as-is (user can edit/reuse or clear)
        send({ action: "set_locked_extra_context", contact: _currentViewedContact, value: "" });
        setLockUI(false);
      } else {
        const value = (extraRequestInput.value || "").trim();
        if (!value) {
          toast("Type some extra context first, then click the lock");
          return;
        }
        send({ action: "set_locked_extra_context", contact: _currentViewedContact, value });
        setLockUI(true);
      }
    });

    // While locked, auto-save edits on blur so the input always reflects
    // the persisted lock without needing to click the button again.
    extraRequestInput.addEventListener("blur", () => {
      if (!_extraLocked || !_currentViewedContact) return;
      const value = (extraRequestInput.value || "").trim();
      if (!value) {
        // Edited down to empty → unlock
        send({ action: "set_locked_extra_context", contact: _currentViewedContact, value: "" });
        setLockUI(false);
      } else {
        send({ action: "set_locked_extra_context", contact: _currentViewedContact, value });
      }
    });
  }

  function renderGlobalBadge() {
    if (!globalLockBadge) return;
    if (_globalLockValue) {
      const short = _globalLockValue.length > 120
        ? _globalLockValue.slice(0, 117) + "…"
        : _globalLockValue;
      globalLockBadge.innerHTML =
        `<span class="glb-icon">&#127760;</span>` +
        `<span class="glb-label">Applied to all chats:</span>` +
        `<span class="glb-text">${esc(short)}</span>` +
        `<button type="button" class="glb-unlock" title="Unlock (apply nothing globally)">&times;</button>`;
      globalLockBadge.classList.remove("hidden");
      const unlockBtn = globalLockBadge.querySelector(".glb-unlock");
      if (unlockBtn) {
        unlockBtn.addEventListener("click", () => {
          send({ action: "set_global_extra_context", value: "" });
        });
      }
    } else {
      globalLockBadge.innerHTML = "";
      globalLockBadge.classList.add("hidden");
    }
    if (globalLockBtn) {
      globalLockBtn.classList.toggle("active", !!_globalLockValue);
      globalLockBtn.title = _globalLockValue
        ? "Global lock ON — this context applies to every chat. Click to unlock."
        : "Lock this extra context to ALL chats (existing and new)";
    }
  }

  if (globalLockBtn && extraRequestInput) {
    globalLockBtn.addEventListener("click", () => {
      if (_globalLockValue) {
        // Already on → unlock globally
        send({ action: "set_global_extra_context", value: "" });
      } else {
        const value = (extraRequestInput.value || "").trim();
        if (!value) {
          toast("Type some extra context first, then click the globe");
          return;
        }
        send({ action: "set_global_extra_context", value });
      }
    });
  }

  if (modelToggle) {
    modelToggle.addEventListener("click", (e) => {
      const btn = e.target.closest(".model-btn");
      if (!btn) return;
      // The version cycle button is inside modelToggle — intercept so
      // clicking "v3" cycles versions instead of treating it as a model
      // selection.
      if (btn.id === "tunedVersionBtn") {
        const current = btn.dataset.version || "v3";
        const avail = (btn.dataset.available || "v3").split(",");
        const order = avail.length ? avail : ["v1", "v2", "v3"];
        const idx = order.indexOf(current);
        const next = order[(idx + 1) % order.length];
        btn.dataset.version = next;
        btn.textContent = next;
        send({ action: "set_tuned_version", version: next });
        toast(`Tuned: ${next.toUpperCase()}`);
        return;
      }
      if (btn.classList.contains("disabled")) {
        toast("Tuned model not ready yet — training is still running.");
        return;
      }
      const model = btn.dataset.model;
      modelToggle.querySelectorAll(".model-btn").forEach(b => {
        if (b.id === "tunedVersionBtn") return;  // don't toggle active on version btn
        b.classList.toggle("active", b === btn);
      });
      send({ action: "set_reply_model", model });
    });
  }

  if (lessonsToggle) {
    lessonsToggle.addEventListener("click", () => {
      const on = !lessonsToggle.classList.contains("active");
      lessonsToggle.classList.toggle("active", on);
      send({ action: "set_use_lessons", enabled: on });
      toast(on ? "Lessons on" : "Lessons off");
    });
  }
  if (examplesToggle) {
    examplesToggle.addEventListener("click", () => {
      const on = !examplesToggle.classList.contains("active");
      examplesToggle.classList.toggle("active", on);
      send({ action: "set_use_examples", enabled: on });
      toast(on ? "Examples on" : "Examples off");
    });
    // Right-click = rebuild library from latest chats
    examplesToggle.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      if (!confirm("Rebuild the examples library from all current chats? (Takes ~30s)")) return;
      send({ action: "rebuild_examples_library" });
      toast("Rebuilding examples library…");
    });
  }
  if (grokToggle) {
    grokToggle.addEventListener("click", () => {
      if (grokToggle.classList.contains("disabled")) {
        toast("Grok not configured — add XAI_API_KEY to .env");
        return;
      }
      const on = !grokToggle.classList.contains("active");
      grokToggle.classList.toggle("active", on);
      send({ action: "set_use_grok", enabled: on });
      toast(on ? "Grok on — Lucas active" : "Grok off");
    });
  }
  if (grokModeBtn) {
    grokModeBtn.addEventListener("click", () => {
      const current = grokModeBtn.dataset.mode || "multi-agent";
      // multi-agent → reasoning → non-reasoning → multi-agent
      const next = current === "multi-agent" ? "reasoning"
                 : current === "reasoning" ? "non-reasoning"
                 : "multi-agent";
      grokModeBtn.dataset.mode = next;
      send({ action: "set_grok_mode", mode: next });
      const labels = {
        "multi-agent": "Multi-Agent (Lucas active)",
        "reasoning": "Reasoning (single-agent)",
        "non-reasoning": "Non-Reasoning (fastest)",
      };
      toast(`Grok: ${labels[next]}`);
    });
  }
  if (grokFullBtn) {
    grokFullBtn.addEventListener("click", () => {
      const on = !grokFullBtn.classList.contains("active");
      grokFullBtn.classList.toggle("active", on);
      send({ action: "set_grok_full_training", enabled: on });
      toast(on ? "Grok: FULL training ON (all 121 transcripts)" : "Grok: Master Playbook only");
    });
  }
  if (dsToggle) {
    dsToggle.addEventListener("click", () => {
      if (dsToggle.classList.contains("disabled")) {
        toast("DeepSeek not configured — add ATLASCLOUD_API_KEY to .env");
        return;
      }
      const on = !dsToggle.classList.contains("active");
      dsToggle.classList.toggle("active", on);
      send({ action: "set_use_deepseek", enabled: on });
      toast(on ? "DeepSeek V4 Pro on" : "DeepSeek off");
    });
  }
  if (dsModeBtn) {
    dsModeBtn.addEventListener("click", () => {
      const current = dsModeBtn.dataset.mode || "normal";
      const next = current === "full" ? "normal" : "full";
      dsModeBtn.dataset.mode = next;
      dsModeBtn.textContent = next === "full" ? "F" : "N";
      send({ action: "set_deepseek_mode", mode: next });
      toast(`DeepSeek: ${next === "full" ? "FULL training (620k tokens)" : "NORMAL (playbook only)"}`);
    });
  }
  if (dsVariantBtn) {
    dsVariantBtn.addEventListener("click", () => {
      const current = dsVariantBtn.dataset.variant || "pro";
      const next = current === "flash" ? "pro" : "flash";
      dsVariantBtn.dataset.variant = next;
      dsVariantBtn.textContent = next === "flash" ? "Fl" : "Pro";
      send({ action: "set_deepseek_variant", variant: next });
      toast(`DeepSeek: ${next === "flash" ? "FLASH (faster)" : "PRO (deeper reasoning)"}`);
    });
  }
  if (kieToggle) {
    kieToggle.addEventListener("click", () => {
      if (kieToggle.classList.contains("disabled")) {
        toast("KIE not configured — add KIE_API_KEY to .env");
        return;
      }
      const on = !kieToggle.classList.contains("active");
      kieToggle.classList.toggle("active", on);
      send({ action: "set_use_kie", enabled: on });
    });
  }

  if (trainingToggle) {
    trainingToggle.addEventListener("click", () => {
      const on = !trainingToggle.classList.contains("active");
      trainingToggle.classList.toggle("active", on);
      send({ action: "set_use_training", enabled: on });
    });
  }

  function updateReceptivenessLabel(v) {
    receptivenessText.textContent = `Receptiveness: ${v}`;
    const descs = [
      "Ice cold", "Very guarded", "Guarded", "Cautious", "Lukewarm",
      "Neutral", "Interested", "Warm", "Very warm", "Eager", "DTF"
    ];
    receptivenessDesc.textContent = descs[v] || "";
  }

  if (receptivenessSlider) {
    receptivenessSlider.addEventListener("input", () => {
      updateReceptivenessLabel(parseInt(receptivenessSlider.value));
    });
    receptivenessSlider.addEventListener("change", () => {
      send({ action: "set_receptiveness", value: parseInt(receptivenessSlider.value) });
    });
  }

  if (historyPrev) {
    historyPrev.addEventListener("click", () => {
      const idx = parseInt(historyLabel.textContent) - 2;
      send({ action: "set_reply_history_index", index: idx });
    });
  }
  if (historyNext) {
    historyNext.addEventListener("click", () => {
      const idx = parseInt(historyLabel.textContent);
      send({ action: "set_reply_history_index", index: idx });
    });
  }

  regenBtn.addEventListener("click", () => {
    const currentInput = extraRequestInput ? extraRequestInput.value.trim() : "";
    const baseContext = extraForUpload();
    // If locked, the server already merges meta.locked_extra_context on
    // its side. Only send the DELTA (anything the user typed beyond the
    // locked text) as one-shot, so we don't double-apply.
    let oneShot = currentInput;
    if (_extraLocked && currentInput) {
      // The full locked text is persisted on the server — no need to resend.
      // Any extra text the user typed after the locked portion becomes
      // one-shot. Simplest robust rule: send "" when locked, let server
      // apply the sticky value. User can unlock + edit if they want a
      // different one-off.
      oneShot = "";
    }
    const combined = [baseContext, oneShot].filter(Boolean).join("\n");
    send({
      action: "regenerate",
      preset: parseInt(presetSelect.value),
      extra_context: combined,
    });
    // Only clear the input when it's NOT locked — locked context must
    // persist visually so the user can see what's being reused.
    if (extraRequestInput && !_extraLocked) extraRequestInput.value = "";
  });

  presetSelect.addEventListener("change", () => {
    presetSelectUiLock = false;
    send({ action: "set_preset", index: parseInt(presetSelect.value) });
    updatePresetSelectTitle();
  });
  presetSelect.addEventListener("focus", () => {
    presetSelectUiLock = true;
  });
  presetSelect.addEventListener("pointerdown", () => {
    presetSelectUiLock = true;
  }, true);
  presetSelect.addEventListener("touchstart", () => {
    presetSelectUiLock = true;
  }, { capture: true, passive: true });
  presetSelect.addEventListener("blur", () => {
    presetSelectUiLock = false;
    pollStateFromApi();
  });

  addPresetBtn.addEventListener("click", () => {
    const name = prompt("Preset name (short label):", "Get her on a date");
    if (!name) return;
    const instr = prompt("Goal instruction (what to add to the prompt):",
      "Goal is to get her invested and set up a date this week");
    if (!instr) return;
    send({ action: "add_preset", name: name, instruction: instr });
  });

  const deletePresetBtn = document.getElementById("deletePresetBtn");
  if (deletePresetBtn) {
    deletePresetBtn.addEventListener("click", () => {
      const idx = parseInt(presetSelect.value);
      if (!Number.isFinite(idx) || idx < 0) {
        alert("Pick a goal in the dropdown first, then click Delete.");
        return;
      }
      const opt = presetSelect.options[presetSelect.selectedIndex];
      const label = opt ? opt.textContent.replace(/\s*\u2605\s*$/, "").trim() : "this goal";
      if (!confirm(`Delete goal "${label}"?`)) return;
      send({ action: "delete_preset", index: idx });
      presetSelect.value = "-1";
      send({ action: "set_preset", index: -1 });
      pollStateFromApi();
    });
  }

  const setDefaultPresetBtn = document.getElementById("setDefaultPresetBtn");
  if (setDefaultPresetBtn) {
    setDefaultPresetBtn.addEventListener("click", () => {
      const idx = parseInt(presetSelect.value);
      send({ action: "set_default_preset", index: idx });
      setDefaultPresetBtn.textContent = "Default set!";
      setTimeout(() => { setDefaultPresetBtn.textContent = "Set default"; }, 1500);
    });
  }

  /** API calls only work when the page is served over http(s), e.g. http://localhost:8000 — not file:// */
  function apiUrl(path) {
    if (typeof location === "undefined") return null;
    const p = location.protocol;
    if (p !== "http:" && p !== "https:") return null;
    const rel = path.startsWith("/") ? path : "/" + path;
    return location.origin + rel;
  }

  async function readJsonError(r) {
    try {
      const j = await r.json();
      if (j && j.detail) {
        return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      }
      if (j && j.error) return j.error;
    } catch (_) {}
    return `Request failed (${r.status})`;
  }

  if (exportPresetsBtn) {
    exportPresetsBtn.addEventListener("click", async () => {
      try {
        const url = apiUrl("/api/export/bundle");
        if (!url) {
          statusText.textContent =
            "Run the server (python -m server.app), then open http://127.0.0.1:8000 — don't open index.html from Finder.";
          statusBanner.classList.add("active");
          return;
        }
        const r = await fetch(url);
        if (!r.ok) {
          if (r.status === 404) {
            statusText.textContent =
              "Export not found (404). Restart the server from the project folder: python -m server.app — then hard-refresh this page.";
          } else {
            statusText.textContent = await readJsonError(r);
          }
          statusBanner.classList.add("active");
          return;
        }
        const data = await r.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "wingman-bundle.json";
        a.click();
        URL.revokeObjectURL(a.href);
        statusText.textContent = "Saved wingman-bundle.json — goals, training files, and chats";
        statusBanner.classList.add("active");
      } catch (_) {
        statusText.textContent = "Could not export — use http://127.0.0.1:8000 and a running server";
        statusBanner.classList.add("active");
      }
    });
  }

  function parseImportFileJson(rawText) {
    const t = rawText.replace(/^\uFEFF/, "").trim();
    let v = JSON.parse(t);
    if (typeof v === "string") {
      v = JSON.parse(v);
    }
    return v;
  }

  if (importPresetsInput) {
    importPresetsInput.addEventListener("change", async () => {
      const f = importPresetsInput.files && importPresetsInput.files[0];
      importPresetsInput.value = "";
      if (!f) return;
      try {
        const url = apiUrl("/api/import/bundle");
        if (!url) {
          statusText.textContent =
            "Open the app at http://127.0.0.1:8000 (server running) — not from a saved HTML file.";
          statusBanner.classList.add("active");
          return;
        }
        const text = await f.text();
        let parsed;
        try {
          parsed = parseImportFileJson(text);
        } catch (e) {
          statusText.textContent =
            e instanceof SyntaxError
              ? "File is not valid JSON — use Export in Wingman, or open the file and check it starts with { or ["
              : "Could not parse import file";
          statusBanner.classList.add("active");
          return;
        }
        const r = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(parsed),
        });
        let d = {};
        try {
          d = await r.json();
        } catch (_) {}
        if (!r.ok) {
          const msg = d.detail
            ? (typeof d.detail === "string" ? d.detail : "Server error")
            : (d.error || `Import failed (${r.status})`);
          statusText.textContent = msg;
          statusBanner.classList.add("active");
          return;
        }
        if (d.error) {
          statusText.textContent = d.error;
          statusBanner.classList.add("active");
          return;
        }
        if (d.ok) {
          const parts = [];
          if (d.presets_count != null) parts.push(`${d.presets_count} goals`);
          else if (d.count != null) parts.push(`${d.count} goals`);
          if (d.training_files != null) parts.push(`${d.training_files} training`);
          if (d.chats_count != null) parts.push(`${d.chats_count} chats`);
          statusText.textContent = parts.length ? `Imported: ${parts.join(", ")}` : "Import OK";
          statusBanner.classList.add("active");
        }
      } catch (_) {
        statusText.textContent = "Import failed — use wingman-bundle.json or goals-only JSON";
        statusBanner.classList.add("active");
      }
    });
  }

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
    const baseCtx = extraForUpload();
    const extraReq = extraRequestInput ? extraRequestInput.value.trim() : "";
    const context = [baseCtx, extraReq].filter(Boolean).join("\n");
    startCountdownRead(contact, context);
  });

  const addQuickCapture = document.getElementById("addQuickCapture");
  if (addQuickCapture) {
    addQuickCapture.addEventListener("click", async () => {
      addMenu.classList.add("hidden");
      if (countdownActive) return;
      countdownActive = true;

      for (let i = 3; i >= 1; i--) {
        statusText.textContent = `Quick capture in ${i}...`;
        statusBanner.classList.add("active");
        playBeep(880, 0.08);
        await new Promise(r => setTimeout(r, 1000));
      }

      playStartSound();
      statusText.textContent = "Capturing + generating...";

      const fd = new FormData();
      fd.append("contact", contactForUpload());
      const baseCtx = extraForUpload();
      const extraReq = extraRequestInput ? extraRequestInput.value.trim() : "";
      fd.append("extra_context", [baseCtx, extraReq].filter(Boolean).join("\n"));

      try {
        const r = await fetch("/api/quick-capture", { method: "POST", body: fd });
        const d = await r.json();
        if (d.error) {
          statusText.textContent = d.error;
          setTimeout(() => { statusText.textContent = ""; }, 2000);
        }
      } catch (e) {
        statusText.textContent = "Quick capture failed";
      }
      countdownActive = false;
    });
  }

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

  if (contactSelect) {
    contactSelect.addEventListener("change", () => {
      contactSelectUiLock = false;
      const v = contactSelect.value;
      if (!v) return;
      if (readContactInput) readContactInput.value = v;
      if (contactInput) contactInput.value = v;
      lastTranscriptCount = 0;
      send({ action: "load_contact", contact: v });
    });
    contactSelect.addEventListener("focus", () => {
      contactSelectUiLock = true;
    });
    contactSelect.addEventListener("pointerdown", () => {
      contactSelectUiLock = true;
    }, true);
    contactSelect.addEventListener("touchstart", () => {
      contactSelectUiLock = true;
    }, { capture: true, passive: true });
    contactSelect.addEventListener("blur", () => {
      contactSelectUiLock = false;
      pollStateFromApi();
    });
  }

  if (analysisToggleBtn) {
    analysisToggleBtn.addEventListener("click", () => {
      coachSection.classList.toggle("hidden");
      analysisToggleBtn.textContent = coachSection.classList.contains("hidden")
        ? "Show analysis"
        : "Hide analysis";
    });
  }

  // ── New Chat button ──────────────────────────────────────────────

  const rankLeadsBtn = document.getElementById("rankLeadsBtn");
  if (rankLeadsBtn) {
    rankLeadsBtn.addEventListener("click", async () => {
      rankLeadsBtn.textContent = "Ranking...";
      rankLeadsBtn.disabled = true;
      try {
        const r = await fetch("/api/rank-leads", { method: "POST" });
        const d = await r.json();
        rankLeadsBtn.textContent = `Ranked ${d.ranked || 0}`;
        setTimeout(() => { rankLeadsBtn.textContent = "Rank"; rankLeadsBtn.disabled = false; }, 2000);
      } catch {
        rankLeadsBtn.textContent = "Failed";
        setTimeout(() => { rankLeadsBtn.textContent = "Rank"; rankLeadsBtn.disabled = false; }, 2000);
      }
    });
  }

  // ── Rapid Fire ──────────────────────────────────────────────────

  const rfModal = document.getElementById("rapidFireModal");
  const rfBtn = document.getElementById("rapidFireBtn");
  const rfStart = document.getElementById("rfStart");
  const rfStop = document.getElementById("rfStop");
  const rfGenerate = document.getElementById("rfGenerate");
  const rfClose = document.getElementById("rfClose");
  const rfSetup = document.getElementById("rfSetup");
  const rfCapturing = document.getElementById("rfCapturing");
  const rfReview = document.getElementById("rfReview");
  const rfPlatform = document.getElementById("rfPlatform");
  const rfDetectedCount = document.getElementById("rfDetectedCount");
  const rfChatList = document.getElementById("rfChatList");
  let rfPollInterval = null;

  if (rfBtn) {
    rfBtn.addEventListener("click", () => {
      rfModal.classList.remove("hidden");
      rfSetup.classList.remove("hidden");
      rfCapturing.classList.add("hidden");
      rfReview.classList.add("hidden");
    });
  }
  if (rfClose) {
    rfClose.addEventListener("click", () => rfModal.classList.add("hidden"));
  }
  if (rfStart) {
    let rfTimer = null;
    rfStart.addEventListener("click", async () => {
      const fd = new FormData();
      fd.append("platform", rfPlatform.value);
      await fetch("/api/rapid-fire/start", { method: "POST", body: fd });
      rfSetup.classList.add("hidden");
      rfCapturing.classList.remove("hidden");
      let secs = 0;
      rfDetectedCount.textContent = "0s";
      rfTimer = setInterval(() => {
        secs++;
        rfDetectedCount.textContent = `${secs}s`;
      }, 1000);
      rfStop._timer = rfTimer;
    });
  }
  if (rfStop) {
    rfStop.addEventListener("click", async () => {
      if (rfStop._timer) clearInterval(rfStop._timer);
      rfStop.textContent = "Analyzing video...";
      rfStop.disabled = true;
      const r = await fetch("/api/rapid-fire/stop", { method: "POST" });
      const d = await r.json();
      rfStop.textContent = "Stop & Review";
      rfStop.disabled = false;
      rfCapturing.classList.add("hidden");
      rfReview.classList.remove("hidden");
      const chats = d.detected || [];
      rfChatList.innerHTML = chats.map(c =>
        `<div class="rf-chat-item"><span>${esc(c.key)}</span><span class="rf-msgs">${c.message_count} msgs</span></div>`
      ).join("") || '<p style="font-size:12px;color:var(--dim)">No chats detected</p>';
    });
  }
  if (rfGenerate) {
    rfGenerate.addEventListener("click", async () => {
      rfGenerate.textContent = "Generating...";
      rfGenerate.disabled = true;
      const fd = new FormData();
      fd.append("extra_context", extraForUpload());
      await fetch("/api/rapid-fire/generate", { method: "POST", body: fd });
      rfModal.classList.add("hidden");
      rfGenerate.textContent = "Generate All Replies";
      rfGenerate.disabled = false;
    });
  }

  const newChatMenu = document.getElementById("newChatMenu");
  const newChatManual = document.getElementById("newChatManual");
  const newChatScreenshot = document.getElementById("newChatScreenshot");

  document.getElementById("newChatBtn").addEventListener("click", () => {
    newChatMenu.classList.toggle("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".new-chat-dropdown")) newChatMenu.classList.add("hidden");
  });

  function clearForNewChat() {
    send({ action: "new_chat" });
    lastRepliesNotifyFp = "";
    lastSeenRepliesVersion = -1;
    if (readContactInput) readContactInput.value = "";
    if (readExtraContext) readExtraContext.value = "";
    if (contactInput) contactInput.value = "";
    if (extraContextEl) extraContextEl.value = "";
    lastTranscriptCount = 0;
    transcriptEl.innerHTML = "";
    repliesEl.innerHTML = "";
    msgCountEl.textContent = "";
    contactLabel.textContent = "";
    contactLabel.title = "";
    if (contactSelect) contactSelect.value = "";
    coachSection.classList.add("hidden");
    if (analysisToggleBtn) {
      analysisToggleBtn.classList.remove("visible");
      analysisToggleBtn.textContent = "Show analysis";
    }
    results.classList.add("hidden");
  }

  if (newChatManual) {
    newChatManual.addEventListener("click", () => {
      newChatMenu.classList.add("hidden");
      clearForNewChat();
    });
  }

  if (newChatScreenshot) {
    newChatScreenshot.addEventListener("click", async () => {
      newChatMenu.classList.add("hidden");
      clearForNewChat();
      if (countdownActive) return;
      countdownActive = true;

      for (let i = 3; i >= 1; i--) {
        statusText.textContent = `Quick capture in ${i}...`;
        statusBanner.classList.add("active");
        playBeep(880, 0.08);
        await new Promise(r => setTimeout(r, 1000));
      }

      playStartSound();
      statusText.textContent = "Detecting chat + generating...";

      const fd = new FormData();
      fd.append("contact", "");
      fd.append("extra_context", "");

      try {
        const r = await fetch("/api/quick-capture", { method: "POST", body: fd });
        const d = await r.json();
        if (d.error) {
          statusText.textContent = d.error;
          setTimeout(() => { statusText.textContent = ""; }, 2000);
        }
      } catch (e) {
        statusText.textContent = "Quick capture failed";
      }
      countdownActive = false;
    });
  }

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

  // ── Keyboard: typing auto-focuses search ──────────────────────────

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;

    if (e.key === "Escape") {
      addMenu.classList.add("hidden");
      if (contactSearch) { contactSearch.value = ""; filterContactsBySearch(); contactSearch.blur(); }
      return;
    }

    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && contactSearch) {
      contactSearch.focus();
    }
  });

  // ── Generation timer ─────────────────────────────────────────────

  let genTimerInterval = null;
  let genStartTime = null;

  function startGenTimer() {
    genStartTime = Date.now();
    if (genTimerInterval) clearInterval(genTimerInterval);
    genTimerInterval = setInterval(() => {
      if (!genStartTime) return;
      const elapsed = ((Date.now() - genStartTime) / 1000).toFixed(0);
      const current = statusText.textContent;
      const base = current.replace(/\s*\(\d+s\)$/, "");
      statusText.textContent = `${base} (${elapsed}s)`;
    }, 1000);
  }

  function stopGenTimer() {
    if (genTimerInterval) {
      clearInterval(genTimerInterval);
      genTimerInterval = null;
    }
    genStartTime = null;
  }

  // ── Baseline system-prompt editor ────────────────────────────────
  // Lets the user tweak the REPLY_SYSTEM_PROMPT used on every
  // generation (the default "No goal" behavior). Persists across
  // restarts via global_settings.json. Reset clears the override and
  // restores the factory default from wingman/config.py.

  function openBaselineModal() {
    if (!baselineModal) return;
    // Refresh from state in case it arrived late
    void pollStateFromApi();
    const editing = baselineState.current || baselineState.factory || "";
    if (baselineTextarea) {
      baselineTextarea.value = editing;
      updateBaselineCharCount();
    }
    if (baselineIndicator) {
      if (baselineState.current) {
        baselineIndicator.textContent = "✎ Custom baseline active — edits are saved to global_settings.json";
        baselineIndicator.className = "baseline-indicator custom";
      } else {
        baselineIndicator.textContent = "Factory default — edit and Save to override";
        baselineIndicator.className = "baseline-indicator default";
      }
    }
    if (baselineOriginal) {
      baselineOriginal.textContent = baselineState.factory || "";
      baselineOriginal.classList.add("hidden");
    }
    if (baselineShowOriginal) {
      baselineShowOriginal.textContent = "Show factory default";
    }
    baselineModal.classList.remove("hidden");
    if (baselineTextarea) baselineTextarea.focus();
  }

  function closeBaselineModal() {
    if (baselineModal) baselineModal.classList.add("hidden");
  }

  function updateBaselineCharCount() {
    if (!baselineCharCount || !baselineTextarea) return;
    const n = baselineTextarea.value.length;
    baselineCharCount.textContent = `${n.toLocaleString()} chars`;
  }

  if (editBaselineBtn) {
    editBaselineBtn.addEventListener("click", openBaselineModal);
  }
  if (baselineCloseBtn) baselineCloseBtn.addEventListener("click", closeBaselineModal);
  if (baselineCancelBtn) baselineCancelBtn.addEventListener("click", closeBaselineModal);
  if (baselineTextarea) {
    baselineTextarea.addEventListener("input", updateBaselineCharCount);
  }
  if (baselineShowOriginal && baselineOriginal) {
    baselineShowOriginal.addEventListener("click", () => {
      const hidden = baselineOriginal.classList.toggle("hidden");
      baselineShowOriginal.textContent = hidden
        ? "Show factory default"
        : "Hide factory default";
    });
  }
  if (baselineSaveBtn) {
    baselineSaveBtn.addEventListener("click", () => {
      if (!baselineTextarea) return;
      const value = baselineTextarea.value;
      const factory = baselineState.factory || "";
      // Soft warning — don't block the save (user may want to restructure)
      // but flag if the JSON format template is missing because parsing
      // will silently fail on the model side.
      if (!value.includes("Format as JSON") && !value.includes("\"read\"")) {
        const proceed = confirm(
          "Heads up — your edit doesn't seem to include the JSON output " +
          "instructions ('Format as JSON' or a '\"read\"' key). Reply " +
          "parsing may break.\n\nSave anyway?"
        );
        if (!proceed) return;
      }
      // Treat identical-to-factory as a clear (cleaner state file)
      const normalized = value.trim() === factory.trim() ? "" : value;
      send({ action: "set_custom_reply_system_prompt", value: normalized });
      baselineState.current = normalized;
      toast(normalized ? "Baseline saved" : "Baseline matches factory — override cleared");
      closeBaselineModal();
      setTimeout(pollStateFromApi, 200);
    });
  }
  if (baselineResetBtn) {
    baselineResetBtn.addEventListener("click", () => {
      const hasOverride = !!baselineState.current;
      const msg = hasOverride
        ? "Reset to the factory default? Your current custom baseline will be discarded."
        : "Reload the factory default text into the editor?";
      if (!confirm(msg)) return;
      // Always clear the server-side override so future calls use the
      // hardcoded default, AND repopulate the textarea so the user can
      // see what "factory" looks like (they can still edit + save to
      // make a new override if they want).
      send({ action: "reset_reply_system_prompt" });
      baselineState.current = "";
      if (baselineTextarea) {
        baselineTextarea.value = baselineState.factory || "";
        updateBaselineCharCount();
      }
      if (baselineIndicator) {
        baselineIndicator.textContent = "Factory default restored";
        baselineIndicator.className = "baseline-indicator default";
      }
      toast("Baseline reset to factory default");
      setTimeout(pollStateFromApi, 200);
    });
  }
  // Click outside modal content to close
  if (baselineModal) {
    baselineModal.addEventListener("click", (e) => {
      if (e.target === baselineModal) closeBaselineModal();
    });
  }
  // Escape to close
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && baselineModal && !baselineModal.classList.contains("hidden")) {
      closeBaselineModal();
    }
  });

  connect();
})();
