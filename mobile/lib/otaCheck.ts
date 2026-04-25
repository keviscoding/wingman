// Active OTA update polling.
//
// expo-updates' default behavior is "check at launch, apply NEXT
// launch". In practice that means users are perpetually one launch
// behind — and if a download is interrupted, two launches behind, and
// so on, with no visible signal anything's happening.
//
// We force the issue: on app launch we explicitly check for an update,
// fetch it, and if a new bundle exists we reload right then. The user
// sees a brief "Updating..." then the new code is live. One quit, one
// open. Everything stays in sync with what's been published.

import * as Updates from "expo-updates";

let lastChecked = 0;
const MIN_INTERVAL_MS = 5 * 60_000; // don't check more than once every 5 min

/** Best-effort update check + auto-reload. Safe to call from anywhere
 *  (idempotent, debounced, never throws). Calling on app launch is
 *  the canonical use; you can also call on AppState=active transitions
 *  if you want to be aggressive. */
export async function checkAndApplyUpdate(): Promise<void> {
  // Disabled in development / Expo Go / dev-client (the metro bundle
  // is the source of truth there).
  if (__DEV__) return;
  // Some build profiles ship without updates enabled.
  if (!Updates.isEnabled) return;

  const now = Date.now();
  if (now - lastChecked < MIN_INTERVAL_MS) return;
  lastChecked = now;

  try {
    const result = await Updates.checkForUpdateAsync();
    if (!result.isAvailable) return;
    await Updates.fetchUpdateAsync();
    // Apply immediately — short "Updating..." flash then back in business.
    await Updates.reloadAsync();
  } catch (err: any) {
    // Common: network failure, no update available, etc. We swallow —
    // the user will pick it up on the next call.
    if (__DEV__) console.warn("[ota] check failed:", err?.message);
  }
}
