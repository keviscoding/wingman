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

let inFlight = false;

/** Best-effort update check + auto-reload. Calls Expo's update SDK on
 *  every invocation — Expo's internal cache + manifest hashing
 *  dedupes redundant network calls; we don't need to add our own
 *  debounce on top, and a debounce was preventing fast iteration
 *  during testing.
 *
 *  Safe to call from anywhere (idempotent guard via inFlight, never
 *  throws). Call on launch + on every AppState=active transition.
 */
export async function checkAndApplyUpdate(): Promise<void> {
  if (__DEV__) return;
  if (!Updates.isEnabled) return;
  if (inFlight) return;
  inFlight = true;
  try {
    const result = await Updates.checkForUpdateAsync();
    if (!result.isAvailable) return;
    await Updates.fetchUpdateAsync();
    await Updates.reloadAsync();
  } catch (err: any) {
    if (__DEV__) console.warn("[ota] check failed:", err?.message);
  } finally {
    inFlight = false;
  }
}
