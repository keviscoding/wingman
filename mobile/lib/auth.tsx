// Auth state held in a tiny context. Token persisted to SecureStore so
// the user stays logged in across app restarts.

import * as SecureStore from "expo-secure-store";
import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { api, AuthResponse, Me } from "./api";
import { openPaywall } from "./paywallStore";
import * as iap from "./iap";
import { clearSentryUser, identifySentryUser } from "./sentry";

type AuthState = {
  loading: boolean;        // true while we hydrate the persisted token
  token: string | null;
  me: Me | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, displayName?: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
};

const TOKEN_KEY = "wingman.auth.token";

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  // Once-per-session guard so we don't keep popping the upsell every
  // time /me refreshes. Reset when the user signs out.
  const upsellShown = useRef(false);

  const persist = useCallback(async (t: string | null) => {
    if (t) {
      await SecureStore.setItemAsync(TOKEN_KEY, t);
    } else {
      await SecureStore.deleteItemAsync(TOKEN_KEY);
    }
  }, []);

  const loadMe = useCallback(async (t: string) => {
    try {
      const m = await api.me(t);
      setMe(m);
      // Tell RevenueCat which user this device belongs to so purchases
      // follow the user across devices and platforms. No-op if RC
      // isn't initialised yet (boot() is called once at app mount).
      iap.identify(m.user_id).catch(() => {});
      identifySentryUser(m.user_id);
      // Server says this Pro user has been hammering the daily Pro
      // cap → surface the upsell once per session.
      if (m?.should_show_pro_max_upsell && !upsellShown.current) {
        upsellShown.current = true;
        openPaywall("pro_max_upsell");
      }
    } catch {
      // Token rejected — wipe so we go back to login
      await persist(null);
      setToken(null);
      setMe(null);
    }
  }, [persist]);

  // Hydrate on mount
  useEffect(() => {
    (async () => {
      try {
        const stored = await SecureStore.getItemAsync(TOKEN_KEY);
        if (stored) {
          setToken(stored);
          await loadMe(stored);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [loadMe]);

  const signIn = useCallback(async (email: string, password: string) => {
    const r: AuthResponse = await api.login(email, password);
    setToken(r.token);
    await persist(r.token);
    await loadMe(r.token);
  }, [persist, loadMe]);

  const signUp = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const r: AuthResponse = await api.signup(email, password, displayName);
      setToken(r.token);
      await persist(r.token);
      await loadMe(r.token);
    },
    [persist, loadMe],
  );

  const signOut = useCallback(async () => {
    await persist(null);
    setToken(null);
    setMe(null);
    upsellShown.current = false;
    // Forget this user in RC so the next login gets a clean identity.
    iap.forget().catch(() => {});
    clearSentryUser();
  }, [persist]);

  const refreshMe = useCallback(async () => {
    if (token) await loadMe(token);
  }, [token, loadMe]);

  return (
    <AuthContext.Provider
      value={{ loading, token, me, signIn, signUp, signOut, refreshMe }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
