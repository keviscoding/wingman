// Push notifications: device side.
//
// Two pieces here:
//   1. firePushReady(contact)    — local notification (mostly redundant
//                                  now that the server fires from the
//                                  background job; kept as a fallback).
//   2. registerWithServer(token) — full chain: ask permission → resolve
//                                  Expo push token → POST to backend.
//                                  Returns a structured result so the
//                                  Settings UI can show the real reason
//                                  if it fails.

import { AppState } from "react-native";
import { api } from "./api";

const ENABLED = true;

let notif: any = null;
let configured = false;

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

export type RegisterResult =
  | { ok: true; tokenPrefix: string }
  | { ok: false; reason: "module_missing" | "permission_denied" | "no_token" | "server_error"; detail?: string };

/** Full chain: permission → Expo Push Token → POST to backend.
 *  Always returns a structured result so the UI can render specifics
 *  ("permission denied", "no Google Play Services", etc.). */
export async function registerWithServer(authToken: string): Promise<RegisterResult> {
  load();
  if (!notif) return { ok: false, reason: "module_missing" };

  // 1. Permission
  try {
    let perm = await notif.getPermissionsAsync?.();
    if (perm?.status !== "granted") {
      perm = await notif.requestPermissionsAsync?.();
    }
    if (perm?.status !== "granted") {
      return { ok: false, reason: "permission_denied" };
    }
  } catch (e: any) {
    return { ok: false, reason: "permission_denied", detail: e?.message };
  }

  // 2. Android channel — required for system to actually deliver
  try {
    if (notif.setNotificationChannelAsync) {
      await notif.setNotificationChannelAsync("default", {
        name: "Wingman replies",
        importance: notif.AndroidImportance?.DEFAULT ?? 3,
        vibrationPattern: [0, 250, 250, 250],
        lightColor: "#66e0b4",
      });
    }
  } catch {
    /* tolerate — channel creation is nice-to-have, not required */
  }

  // 3. Expo Push Token
  let expoToken: string | null = null;
  try {
    const r = await notif.getExpoPushTokenAsync({
      projectId: "48c58bd6-8026-416d-b830-aa37bfa4fe7f",
    });
    expoToken = r?.data || null;
  } catch (e: any) {
    if (__DEV__) console.warn("[push] token request failed:", e);
    return {
      ok: false,
      reason: "no_token",
      detail: e?.message || "couldn't resolve push token",
    };
  }
  if (!expoToken) return { ok: false, reason: "no_token" };

  // 4. POST to our backend
  try {
    await api.registerPushToken(authToken, expoToken);
  } catch (e: any) {
    return {
      ok: false,
      reason: "server_error",
      detail: e?.detail || e?.message,
    };
  }

  return { ok: true, tokenPrefix: expoToken.slice(0, 30) };
}

/** Older entry used by _layout's launch effect. Kept tolerant — it
 *  doesn't matter if it fails silently because the Settings test-push
 *  button now calls registerWithServer with full error reporting. */
export async function primeNotifications() {
  load();
  if (!notif) return;
  try {
    const p = await notif.getPermissionsAsync?.();
    if (p?.status !== "granted") {
      await notif.requestPermissionsAsync?.();
    }
  } catch {
    /* tolerate */
  }
}

/** Local notification (foreground-only safety net). The server-fired
 *  push is the canonical "ready" signal — this is just a backup in
 *  case the server's push didn't reach. */
export async function firePushReady(contactName: string) {
  load();
  if (!notif) return;
  if (AppState.currentState === "active") return;
  try {
    await notif.scheduleNotificationAsync({
      content: {
        title: "Your reply is ready ✓",
        body: `5 replies for ${contactName} · tap to copy`,
        data: { contact: contactName },
      },
      trigger: null,
    });
  } catch {
    /* tolerate */
  }
}
