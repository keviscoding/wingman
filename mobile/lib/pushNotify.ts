// Local push notification on generation completion.
//
// Soft-required so old APKs (built before we added expo-notifications)
// don't crash on require — they just no-op. The native module SHIP only
// in production builds where the dep is bundled.
//
// We only fire when the app is BACKGROUNDED. Foregrounded users have
// the dock chip already shouting at them; firing a system push on top
// would be obnoxious.

import { AppState } from "react-native";

const ENABLED = true;

let notif: any = null;
let configured = false;
let permissionRequested = false;

function load() {
  if (configured) return;
  configured = true;
  if (!ENABLED) return;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    notif = require("expo-notifications");
  } catch {
    notif = null;
    return;
  }
  // Required handler for foregrounded events. We don't actually fire
  // any while the app is foregrounded (see firePushReady), but the SDK
  // warns if this isn't set.
  try {
    notif.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowBanner: true,
        shouldShowList: true,
        shouldPlaySound: false,
        shouldSetBadge: false,
      }),
    });
  } catch {
    /* tolerate */
  }
}

async function ensurePermission() {
  if (!notif || permissionRequested) return;
  permissionRequested = true;
  try {
    const current = await notif.getPermissionsAsync?.();
    if (current?.status !== "granted") {
      await notif.requestPermissionsAsync?.();
    }
  } catch {
    /* tolerate */
  }
}

/** Fire-and-forget. Triggers a system push notification ONLY if the
 *  app is currently backgrounded. Safe to call from anywhere — silent
 *  no-op when expo-notifications isn't bundled or permission denied.
 */
export async function firePushReady(contactName: string) {
  load();
  if (!notif) return;
  if (AppState.currentState === "active") return;
  await ensurePermission();
  try {
    await notif.scheduleNotificationAsync({
      content: {
        title: "Your reply is ready ✓",
        body: `5 replies for ${contactName} · tap to copy`,
        data: { contact: contactName },
      },
      trigger: null, // immediate
    });
  } catch {
    /* tolerate any failure silently */
  }
}

/** Eagerly request notification permission at app launch — better UX
 *  than waiting for the first job to fire and asking mid-flow. */
export async function primeNotifications() {
  load();
  if (!notif) return;
  await ensurePermission();
}

/** Resolve the device's Expo Push Token (ExponentPushToken[...]).
 *  We send this to our backend so the SERVER can fire notifications
 *  via Expo's Push API even when the app is suspended in background.
 *  Returns null if expo-notifications isn't bundled or permission
 *  was denied. */
export async function getExpoPushToken(): Promise<string | null> {
  load();
  if (!notif) return null;
  await ensurePermission();
  try {
    // Android: ensure default channel so notifications actually appear
    if (notif.setNotificationChannelAsync) {
      await notif.setNotificationChannelAsync("default", {
        name: "Wingman replies",
        importance: notif.AndroidImportance?.DEFAULT ?? 3,
        vibrationPattern: [0, 250, 250, 250],
        lightColor: "#66e0b4",
      });
    }
    const r = await notif.getExpoPushTokenAsync({
      // EAS project ID is read from app.json automatically; this also
      // works in classic builds.
      projectId: "48c58bd6-8026-416d-b830-aa37bfa4fe7f",
    });
    return r?.data || null;
  } catch (e) {
    if (__DEV__) console.warn("[push] getExpoPushTokenAsync failed:", e);
    return null;
  }
}
