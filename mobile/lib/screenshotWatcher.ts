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

// Mirror home's auto-fire window so the watcher's deferred-banner
// logic uses the same threshold for "this is fresh enough to claim".
// Keeping these in sync prevents the banner from firing for a
// screenshot that home WOULD auto-fire on (we'd just be racing).
const AUTO_FIRE_MAX_AGE_S = 180;

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
    // RACE FIX: when a screenshot is fresh enough that the home
    // screen's auto-fire might claim it, defer the banner so home
    // wins. If home's scan() ends up enqueueing, it'll call
    // setProcessedScreenshotId which immediately notifies(null) and
    // wipes the banner. If it doesn't, we surface the banner after
    // the grace period.
    //
    // 1500ms (was 600ms) — a tighter window was losing the race on
    // slower phones / when getMostRecentScreenshot took longer than
    // usual (e.g. just after MediaLibrary had to refresh its index).
    if (s.ageSeconds <= AUTO_FIRE_MAX_AGE_S) {
      setTimeout(() => {
        if (s.id === processedId) return; // home claimed it
        if (s.id === dismissedId) return;
        notify(s);
      }, 1500);
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
