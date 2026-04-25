// Global "fresh screenshot" watcher.
//
// Goal: while the user is reading the chat detail screen, detect when
// they've taken a new screenshot (e.g. switched to another chat in
// WhatsApp) and surface a non-intrusive banner: "New screenshot
// detected — analyze?". Tapping fires an upload + navigation to the
// resulting chat. Dismissing remembers the screenshot id so we don't
// re-prompt for it.
//
// Shared state lives in module-level refs (no Context required) since
// screen lifecycles aren't strict siblings — the home screen and chat
// detail screen both subscribe.

import { useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import {
  getMostRecentScreenshot,
  RecentScreenshot,
} from "./screenshot";

// Newest screenshot id we've actually run through quick-capture.
// Set when home → quick-capture succeeds; gates the banner from showing
// for a screenshot the user already analyzed.
let processedId: string | null = null;
// Newest screenshot id the user explicitly dismissed via the banner.
// Stops nagging.
let dismissedId: string | null = null;
// Don't surface a banner for a screenshot older than this — they would
// have shown up on the home screen instead.
const MAX_FRESH_AGE_S = 5 * 60;

const listeners = new Set<(s: RecentScreenshot | null) => void>();
let inFlight = false;

export function setProcessedScreenshotId(id: string | null) {
  processedId = id;
  // Anything we've now processed should also clear from "fresh" state.
  notify(null);
}

async function scanAndNotify() {
  if (inFlight) return;
  inFlight = true;
  try {
    const r = await getMostRecentScreenshot();
    if (r.status !== "ok") {
      notify(null);
      return;
    }
    const s = r.screenshot;
    if (s.id === processedId) {
      notify(null);
      return;
    }
    if (s.id === dismissedId) {
      notify(null);
      return;
    }
    if (s.ageSeconds > MAX_FRESH_AGE_S) {
      notify(null);
      return;
    }
    notify(s);
  } finally {
    inFlight = false;
  }
}

function notify(s: RecentScreenshot | null) {
  listeners.forEach((fn) => fn(s));
}

/**
 * Subscribe to the "fresh screenshot" stream. Returns the freshest
 * unseen screenshot or null. Scans on every foreground transition AND
 * once on mount.
 *
 * The hook stays mounted on whichever screen calls it; the banner
 * component is the canonical caller.
 */
export function useFreshScreenshot(): {
  shot: RecentScreenshot | null;
  dismiss: () => void;
} {
  const [shot, setShot] = useState<RecentScreenshot | null>(null);
  const lastSeenRef = useRef<string | null>(null);

  useEffect(() => {
    const fn = (s: RecentScreenshot | null) => {
      lastSeenRef.current = s?.id || null;
      setShot(s);
    };
    listeners.add(fn);
    // Kick a scan immediately so the banner can show on first mount
    // (e.g. user opened the app already on the chat detail screen).
    scanAndNotify();
    return () => {
      listeners.delete(fn);
    };
  }, []);

  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") scanAndNotify();
    });
    return () => sub.remove();
  }, []);

  const dismiss = () => {
    if (lastSeenRef.current) {
      dismissedId = lastSeenRef.current;
    }
    setShot(null);
  };

  return { shot, dismiss };
}
