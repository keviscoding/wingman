// Tiny shared store for the "onboarding has been seen" flag so the
// AuthGate can react when it flips, without prop-drilling or a full
// state library.
//
// SecureStore is the persistent backing — `seen` here is just an
// in-memory mirror that drives renders.

import * as SecureStore from "expo-secure-store";
import { useEffect, useState } from "react";

const KEY = "wingman_onboarding_seen";

let memSeen: boolean | null = null;
const listeners = new Set<(seen: boolean) => void>();

export async function loadSeen(): Promise<boolean> {
  if (memSeen !== null) return memSeen;
  try {
    const v = await SecureStore.getItemAsync(KEY);
    memSeen = v === "1";
  } catch {
    memSeen = false;
  }
  return memSeen;
}

export async function markSeen() {
  memSeen = true;
  try {
    await SecureStore.setItemAsync(KEY, "1");
  } catch {
    /* no-op */
  }
  listeners.forEach((fn) => fn(true));
}

export function useOnboardingSeen(): {
  seen: boolean | null; // null while loading
  refresh: () => Promise<void>;
} {
  const [seen, setSeen] = useState<boolean | null>(memSeen);

  useEffect(() => {
    if (memSeen === null) {
      loadSeen().then(setSeen);
    }
    const fn = (v: boolean) => setSeen(v);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);

  return {
    seen,
    refresh: async () => {
      memSeen = null;
      const v = await loadSeen();
      setSeen(v);
    },
  };
}
