// Persisted "default mode" the user chose last (Fast vs Pro).
// SecureStore-backed so it survives sign-outs/cold starts.
//
// Pro mode is paid-only (with a small free trial). The store doesn't
// enforce that — the API does. The toggle UI hints at the gate when
// the user is on free tier.

import * as SecureStore from "expo-secure-store";
import { useEffect, useState } from "react";
import { GenerationMode } from "./api";

const KEY = "wingman_default_mode";

let memMode: GenerationMode | null = null;
const listeners = new Set<(m: GenerationMode) => void>();

async function load(): Promise<GenerationMode> {
  if (memMode) return memMode;
  try {
    const v = (await SecureStore.getItemAsync(KEY)) as GenerationMode | null;
    memMode = v === "pro" ? "pro" : "fast";
  } catch {
    memMode = "fast";
  }
  return memMode;
}

export async function setMode(m: GenerationMode) {
  memMode = m;
  try {
    await SecureStore.setItemAsync(KEY, m);
  } catch {
    /* ignore */
  }
  listeners.forEach((fn) => fn(m));
}

export function useMode(): [GenerationMode, (m: GenerationMode) => void] {
  const [m, setLocal] = useState<GenerationMode>(memMode || "fast");

  useEffect(() => {
    if (memMode === null) {
      load().then(setLocal);
    }
    const fn = (next: GenerationMode) => setLocal(next);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);

  return [m, (next) => void setMode(next)];
}
