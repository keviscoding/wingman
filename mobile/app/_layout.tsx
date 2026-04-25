import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { AppState, View } from "react-native";
import { GenerationDock } from "../components/GenerationDock";
import { PaywallSheet } from "../components/PaywallSheet";
import { AuthProvider, useAuth } from "../lib/auth";
import { useOnboardingSeen } from "../lib/onboardingState";
import { checkAndApplyUpdate } from "../lib/otaCheck";
import { dismissPaywall, usePaywallSignal } from "../lib/paywallStore";
import { api } from "../lib/api";
import { getExpoPushToken, primeNotifications } from "../lib/pushNotify";
import { theme } from "../lib/theme";

function AuthGate() {
  const { token, loading } = useAuth();
  const { seen } = useOnboardingSeen();
  const segments = useSegments();
  const router = useRouter();

  // Active OTA poll — runs once on app launch, then on every
  // foreground transition. If a new JS bundle is published, we
  // download + reloadAsync inside this hook. No "second restart"
  // dance, no perpetually-one-version-behind state.
  useEffect(() => {
    checkAndApplyUpdate();
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") checkAndApplyUpdate();
    });
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (loading || seen === null) return;
    const top = segments[0];
    const inAuthFlow = top === "(auth)";
    const onOnboarding = top === "onboarding";
    const needsOnboarding = !seen;

    if (!token && !inAuthFlow) {
      router.replace("/(auth)/login");
      return;
    }
    if (token) {
      if (needsOnboarding && !onOnboarding) {
        router.replace("/onboarding");
        return;
      }
      if (!needsOnboarding && (inAuthFlow || onOnboarding)) {
        router.replace("/");
      }
    }
  }, [token, loading, segments, router, seen]);

  // Once a user is signed in and onboarded:
  //   1. Ask for notification permission
  //   2. Get the Expo push token
  //   3. POST it to our backend so the server can fire pushes when
  //      generations complete, even with JS suspended in background.
  // Runs once per launch — no harm if it re-runs.
  useEffect(() => {
    if (!(token && seen)) return;
    let cancelled = false;
    (async () => {
      await primeNotifications();
      const expoToken = await getExpoPushToken();
      if (cancelled || !expoToken) return;
      try {
        await api.registerPushToken(token, expoToken);
      } catch {
        /* swallow — server can be unreachable; we'll re-register next launch */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, seen]);

  return null;
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <View style={{ flex: 1, backgroundColor: theme.bg }}>
        <StatusBar style="light" />
        <AuthGate />
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: theme.bg },
            animation: "fade",
          }}
        />
        {/* Mounted at root so they persist across screen transitions. */}
        <GenerationDock />
        <RootPaywall />
      </View>
    </AuthProvider>
  );
}

function RootPaywall() {
  const reason = usePaywallSignal();
  return (
    <PaywallSheet
      visible={!!reason}
      onDismiss={dismissPaywall}
      onSubscribe={dismissPaywall}
      pretitle={reason === "pro_locked_free" ? "PRO TRIAL USED" : undefined}
      title={
        reason === "pro_locked_free"
          ? "Out of Pro generations"
          : reason === "daily_cap_free"
            ? "Daily limit reached"
            : reason === "lifetime_trial_exhausted"
              ? "Free trial complete"
              : "Upgrade to Pro"
      }
      subtitle={
        reason === "pro_locked_free"
          ? "Pro is paid-only after the 2 free trials. Upgrade to keep going."
          : reason === "daily_cap_free"
            ? "Free users get a few replies per day. Upgrade to remove the cap."
            : reason === "lifetime_trial_exhausted"
              ? "You've used all free generations. Upgrade for unlimited."
              : "Get unlimited replies, both Fast and Pro modes. Cancel anytime."
      }
    />
  );
}
