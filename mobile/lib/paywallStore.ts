// Tiny store that lets ANY screen / hook / queue job ask the paywall
// sheet to open. The sheet itself lives once at the root layout and
// subscribes here.

import { useEffect, useState } from "react";

export type PaywallReason =
  | "pro_locked_free"           // free user tried Pro after trial used up
  | "daily_cap_free"             // free user hit daily Quick cap
  | "lifetime_trial_exhausted"   // free user out of lifetime trials entirely
  | "daily_cap_paid_pro"         // Pro subscriber hit Pro daily cap → suggest Pro Max
  | "pro_max_upsell"             // server-detected upsell signal
  | "device_already_used"        // secondary account on this device — must subscribe
  | "manual";                    // user tapped Upgrade in settings

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

/** Returns true when the paywall reason indicates we should preselect
 *  Pro Max (whale upsell) instead of the default Pro tier. */
export function isUpsellReason(r: PaywallReason | null): boolean {
  return r === "pro_max_upsell" || r === "daily_cap_paid_pro";
}
