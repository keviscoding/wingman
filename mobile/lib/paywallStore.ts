// Tiny store that lets ANY screen / hook / queue job ask the paywall
// sheet to open. The sheet itself lives once at the root layout and
// subscribes here.
//
// Why a module-level store and not Context: the queue runs background
// async work (`runJob`) that has no React tree to traverse. A
// pub/sub keeps the API trivial: `openPaywall("pro_locked_free")`.

import { useEffect, useState } from "react";

type PaywallReason =
  | "pro_locked_free"
  | "daily_cap_free"
  | "lifetime_trial_exhausted"
  | "manual";

let openedReason: PaywallReason | null = null;
const listeners = new Set<(r: PaywallReason | null) => void>();

export function openPaywall(reason: PaywallReason = "manual") {
  openedReason = reason;
  listeners.forEach((fn) => fn(reason));
}

export function dismissPaywall() {
  openedReason = null;
  listeners.forEach((fn) => fn(null));
}

export function usePaywallSignal(): PaywallReason | null {
  const [r, setR] = useState<PaywallReason | null>(openedReason);
  useEffect(() => {
    const fn = (next: PaywallReason | null) => setR(next);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);
  return r;
}
