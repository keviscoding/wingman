// Single source of truth for backend URL.
// Override at build time with EXPO_PUBLIC_API_URL.
// During dev, point at your local backend or an ngrok tunnel.

import Constants from "expo-constants";
import { Platform } from "react-native";

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

export const API_URL: string =
  process.env.EXPO_PUBLIC_API_URL?.trim() || defaultDevUrl();

export const APP_NAME = "Wingman";
