// Device fingerprint resolution.
//
// Returns a stable identifier for the current device. Stable means it
// survives reinstalling the app:
//
//   • Android: Settings.Secure.ANDROID_ID (SSAID) — only resets on
//     factory reset.
//   • iOS:    identifierForVendor — same value across reinstalls of
//     any app from this vendor; only resets if user uninstalls ALL
//     apps from the vendor.
//
// Used at signup to deny trial credits to secondary accounts created
// from a device that's already burned a previous account's trial. The
// server stores the value on the user row and looks it up at /signup
// time. Whether or not we send a value, the server never penalises a
// user — null just disables the freeloader check for that signup.

import * as Application from "expo-application";
import { Platform } from "react-native";

let cached: string | null = null;
let resolving: Promise<string | null> | null = null;

/** Resolve a stable per-device id. Cached for the app's lifetime —
 *  the underlying APIs are cheap but predictable values are nice. */
export async function getDeviceId(): Promise<string | null> {
  if (cached !== null) return cached;
  if (resolving) return resolving;
  resolving = (async () => {
    try {
      if (Platform.OS === "android") {
        const id = Application.getAndroidId?.() ?? null;
        cached = id || null;
        return cached;
      }
      if (Platform.OS === "ios") {
        const id = await Application.getIosIdForVendorAsync?.();
        cached = id || null;
        return cached;
      }
    } catch {
      // expo-application can throw on simulators / in rare env failures.
      // We don't crash the app — the server tolerates a null device_id.
    }
    cached = null;
    return null;
  })();
  return resolving;
}
