import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { AppState, View } from "react-native";
import { GenerationDock } from "../components/GenerationDock";
import { PaywallSheet } from "../components/PaywallSheet";
import { AuthProvider, useAuth } from "../lib/auth";
import { useOnboardingSeen } from "../lib/onboardingState";
import { checkAndApplyUpdate } from "../lib/otaCheck";
import {
  dismissPaywall,
  isUpsellReason,
  usePaywallSignal,
} from "../lib/paywallStore";
import { registerWithServer } from "../lib/pushNotify";
import * as iap from "../lib/iap";
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
    // Boot RevenueCat once on app mount. Idempotent — auth.loadMe
    // calls iap.identify(user_id) once we know who's signed in.
    iap.boot().catch(() => {});
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

  // Once a user is signed in: chain permission → Expo token → backend.
  // registerWithServer is tolerant; failures resolve cleanly. The
  // Settings 'Send test notification' button will retry with detailed
  // error reporting if this background attempt didn't take.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      const r = await registerWithServer(token);
      if (cancelled) return;
      if (__DEV__ && !r.ok) {
        console.warn("[push] register failed:", r.reason, r.detail);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

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
  const upsell = isUpsellReason(reason);

  let pretitle: string | undefined;
  let title: string | undefined;
  let subtitle: string | undefined;

  switch (reason) {
    case "pro_locked_free":
      pretitle = "PRO TRIAL USED";
      title = "Out of Pro generations";
      subtitle = "Pro is paid-only after the free trials. Upgrade to keep going.";
      break;
    case "daily_cap_free":
      title = "Daily limit reached";
      subtitle = "Free users get 5 replies a day. Upgrade to remove the cap.";
      break;
    case "lifetime_trial_exhausted":
      title = "Free trial complete";
      subtitle = "You've used all free generations. Upgrade for unlimited.";
      break;
    case "daily_cap_paid_pro":
      pretitle = "PRO DAILY CAP";
      title = "You're a power user";
      subtitle =
        "You've used today's 30 Pro generations. Pro Max unlocks 100/day plus priority queue.";
      break;
    case "pro_max_upsell":
      pretitle = "POWER USER";
      title = "Ready for Pro Max?";
      subtitle =
        "You've been hitting the Pro daily cap. Pro Max gives you 100 Pro replies a day, priority queue, and early features.";
      break;
    default:
      title = undefined;
      subtitle = undefined;
  }

  return (
    <PaywallSheet
      visible={!!reason}
      onDismiss={dismissPaywall}
      onSubscribe={dismissPaywall}
      pretitle={pretitle}
      title={title}
      subtitle={subtitle}
      upsellMode={upsell}
    />
  );
}
