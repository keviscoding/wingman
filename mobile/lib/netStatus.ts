// Lazy NetInfo wrapper.
//
// `@react-native-community/netinfo` requires a native module. In a stale
// dev-client APK (built before we added the dep) the module is null and
// calling it crashes the JS bridge. We soft-require it here so the app
// keeps working — the no-internet banner just won't show until the user
// installs a fresh APK that includes the module.

import { useEffect, useState } from "react";

type NetState = { online: boolean };

let netInfoMod: any = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  netInfoMod = require("@react-native-community/netinfo")?.default;
} catch {
  netInfoMod = null;
}

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    if (!netInfoMod) return;
    try {
      const sub = netInfoMod.addEventListener((state: any) => {
        const reachable =
          state.isInternetReachable === null ? true : !!state.isInternetReachable;
        setOnline(!!state.isConnected && reachable);
      });
      return () => sub();
    } catch {
      // Native module installed but threw on init — bail silently.
      return;
    }
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
