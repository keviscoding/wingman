// Single source of truth for backend URL.
//
// Resolution order:
//   1. EXPO_PUBLIC_API_URL env var (set in EAS or local .env at build time)
//   2. In production builds → hardcoded PROD_URL fallback
//   3. In dev builds → LAN IP / localhost
//
// The PROD_URL fallback exists so a production EAS build that
// accidentally ships without EXPO_PUBLIC_API_URL still hits the real
// backend instead of localhost. (We learned this the hard way once —
// the first internal test build went out without the env var and every
// device showed "Can't reach the server.")

import Constants from "expo-constants";
import { Platform } from "react-native";

const PROD_URL = "https://lionfish-app-m49pf.ondigitalocean.app";

function defaultDevUrl(): string {
  // Try to grab the dev machine's LAN IP from Expo's host info, so
  // running on a physical Android phone Just Works without manually
  // editing this file every time we restart.
  const hostUri =
    (Constants.expoConfig as any)?.hostUri ||
    (Constants.manifest as any)?.debuggerHost ||
    (Constants.manifest2 as any)?.extra?.expoGo?.debuggerHost;
  if (typeof hostUri === "string") {
    const host = hostUri.split(":")[0];
    if (host && host !== "localhost") {
      return `http://${host}:8000`;
    }
  }
  // Android emulator routes 10.0.2.2 → host loopback. iOS simulator can use localhost.
  return Platform.OS === "android" ? "http://10.0.2.2:8000" : "http://localhost:8000";
}

function resolveBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL?.trim();
  if (fromEnv) return fromEnv;
  // __DEV__ is true in JS dev mode, false in release builds. We rely
  // on this so production binaries always hit the live backend.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const isDev = typeof __DEV__ !== "undefined" ? (__DEV__ as boolean) : false;
  return isDev ? defaultDevUrl() : PROD_URL;
}

export const API_URL: string = resolveBaseUrl();

export const APP_NAME = "Muzo";
