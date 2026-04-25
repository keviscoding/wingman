// Lazy NetInfo wrapper.
//
// `@react-native-community/netinfo` requires a native module. In a stale
// dev-client APK (built before we added the dep) the module is null and
// calling it crashes the JS bridge. We soft-require it here so the app
// keeps working — the no-internet banner just won't show until the user
// installs a fresh APK that includes the module.
//
// Smarter "online" signal: NetInfo's isInternetReachable does an active
// probe that sometimes returns false RIGHT after the app foregrounds,
// even when the network is fine. To avoid flashing a misleading "No
// connection" banner we only flag offline when isConnected === false
// (the radio-level signal) AND it stays that way for >= 4 seconds.

import { useEffect, useRef, useState } from "react";

let netInfoMod: any = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  netInfoMod = require("@react-native-community/netinfo")?.default;
} catch {
  netInfoMod = null;
}

const OFFLINE_DEBOUNCE_MS = 4000;

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(true);
  const offlineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!netInfoMod) return;
    let unsubscribe: (() => void) | undefined;
    try {
      unsubscribe = netInfoMod.addEventListener((state: any) => {
        const connected = !!state.isConnected;
        if (connected) {
          // Online — clear any pending "go offline" timer + flip true.
          if (offlineTimerRef.current) {
            clearTimeout(offlineTimerRef.current);
            offlineTimerRef.current = null;
          }
          setOnline(true);
          return;
        }
        // Disconnected — debounce. If we're still offline after 4s,
        // THEN show the banner. Stops the false-positive flash on
        // foreground transitions.
        if (offlineTimerRef.current) return;
        offlineTimerRef.current = setTimeout(() => {
          setOnline(false);
          offlineTimerRef.current = null;
        }, OFFLINE_DEBOUNCE_MS);
      });
    } catch {
      // Native module installed but threw on init — bail silently.
      return;
    }
    return () => {
      if (offlineTimerRef.current) {
        clearTimeout(offlineTimerRef.current);
        offlineTimerRef.current = null;
      }
      unsubscribe?.();
    };
  }, []);

  return online;
}

export function refetchNetwork() {
  if (!netInfoMod) return;
  try {
    netInfoMod.fetch();
  } catch {
    /* ignore */
  }
}
