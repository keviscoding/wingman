import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { View } from "react-native";
import { GenerationDock } from "../components/GenerationDock";
import { AuthProvider, useAuth } from "../lib/auth";
import { useOnboardingSeen } from "../lib/onboardingState";
import { theme } from "../lib/theme";

function AuthGate() {
  const { token, loading } = useAuth();
  const { seen } = useOnboardingSeen();
  const segments = useSegments();
  const router = useRouter();

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
        {/* Mounted at root so it persists across screen transitions. */}
        <GenerationDock />
      </View>
    </AuthProvider>
  );
}
