// Find recent screenshots from the device library. Returns a discriminated
// union so the UI can render specific states (permission denied, no
// screenshots yet, found one) without guessing from error strings.

import * as MediaLibrary from "expo-media-library";
import { Platform } from "react-native";

export type RecentScreenshot = {
  id: string;
  uri: string;            // file:// or content:// URI usable with FormData
  filename: string;
  createdAt: number;      // epoch ms
  ageSeconds: number;
};

export type ScreenshotResult =
  | { status: "ok"; screenshot: RecentScreenshot }
  | { status: "permission_denied" }
  | { status: "no_screenshot" };


/**
 * Robust resolver for the user's most recent screenshot.
 *
 *   • Tries the "Screenshots" album first (cleanest on Android).
 *   • Falls back to scanning the last 60 photos and filename-matching
 *     anything that looks like a screenshot. Catches edge cases on
 *     Android (sub-album names) and iOS (.mediaSubtype path).
 *   • Returns the FRESHEST match regardless of age — the UI decides
 *     whether to act on it (showing a "5 min ago" hint is more useful
 *     than silently rejecting it).
 */
export async function getMostRecentScreenshot(): Promise<ScreenshotResult> {
  // 1. Permission gate. Photo only — don't ask for audio/video.
  // KNOWN LIMITATION: in Expo Go, the bundled expo-media-library
  // native module crashes if AUDIO isn't in the host AndroidManifest,
  // even when we explicitly scope to photos via granularPermissions.
  // We can't fix this without a custom dev build (EAS). For now,
  // catch + return "permission_denied" so the UI falls back to the
  // standard ImagePicker (which Expo Go supports cleanly).
  let perm: MediaLibrary.PermissionResponse;
  try {
    perm = await MediaLibrary.getPermissionsAsync(false, ["photo"]);
    if (!perm.granted) {
      perm = await MediaLibrary.requestPermissionsAsync(false, ["photo"]);
    }
  } catch (err: any) {
    // Treat any native MediaLibrary failure as "no auto-detect" so the
    // app stays functional via manual pick. Logged so we can debug.
    if (__DEV__) {
      console.warn("[screenshot] MediaLibrary unavailable:", err?.message);
    }
    return { status: "permission_denied" };
  }
  if (!perm.granted) {
    return { status: "permission_denied" };
  }

  // 2. Strategy A: dedicated Screenshots album
  let candidates: MediaLibrary.Asset[] = [];
  try {
    const album = await MediaLibrary.getAlbumAsync("Screenshots");
    if (album) {
      const r = await MediaLibrary.getAssetsAsync({
        album,
        first: 1,
        sortBy: [[MediaLibrary.SortBy.creationTime, false]],
        mediaType: "photo",
      });
      candidates = r.assets;
    }
  } catch {
    /* fall through */
  }

  // 3. Strategy B: scan recent photos, filter by filename pattern.
  // Helps on devices where the Screenshots album doesn't exist as a
  // first-class concept (e.g. some custom Android skins, iCloud iOS).
  if (candidates.length === 0) {
    try {
      const r = await MediaLibrary.getAssetsAsync({
        first: 60,
        sortBy: [[MediaLibrary.SortBy.creationTime, false]],
        mediaType: "photo",
      });
      candidates = r.assets.filter((a) =>
        /screenshot|screen[_-]?shot|screen[_-]?capture/i.test(a.filename),
      );
    } catch {
      /* nothing to recover from — return no_screenshot */
    }
  }

  // 4. Strategy C (last resort): just take the most recent photo of
  //    any kind. This catches devices where the screenshot filename
  //    doesn't match our pattern. The UI shows the timestamp + name
  //    so the user can confirm.
  if (candidates.length === 0) {
    try {
      const r = await MediaLibrary.getAssetsAsync({
        first: 1,
        sortBy: [[MediaLibrary.SortBy.creationTime, false]],
        mediaType: "photo",
      });
      candidates = r.assets;
    } catch {
      /* still nothing */
    }
  }

  const top = candidates[0];
  if (!top) {
    return { status: "no_screenshot" };
  }

  // iOS sometimes returns a ph:// URI that fetch() can't read; resolve
  // to a localUri when needed. Android's URI is already usable.
  let uri = top.uri;
  if (Platform.OS === "ios") {
    try {
      const info = await MediaLibrary.getAssetInfoAsync(top);
      if (info?.localUri) uri = info.localUri;
    } catch {
      /* fall back to .uri */
    }
  }

  const ageSeconds = Math.max(0, Math.floor((Date.now() - top.creationTime) / 1000));
  return {
    status: "ok",
    screenshot: {
      id: top.id,
      uri,
      filename: top.filename,
      createdAt: top.creationTime,
      ageSeconds,
    },
  };
}


/** Human-readable "X seconds ago" for the home-screen hint. */
export function formatAge(ageSeconds: number): string {
  if (ageSeconds < 5) return "just now";
  if (ageSeconds < 60) return `${ageSeconds}s ago`;
  if (ageSeconds < 3600) return `${Math.floor(ageSeconds / 60)}m ago`;
  if (ageSeconds < 86400) return `${Math.floor(ageSeconds / 3600)}h ago`;
  return `${Math.floor(ageSeconds / 86400)}d ago`;
}
