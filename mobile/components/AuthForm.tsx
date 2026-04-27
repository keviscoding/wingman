// Shared sign-up / login form. Matches WINGMAN UI/AuthScreen.jsx:
//   - radial mint glow at top
//   - 28px wordmark
//   - hero headline + subline
//   - field stack with focus ring
//   - primary button + mode-switch link
//   - bottom legal row

import { Link } from "expo-router";
import { ReactNode } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Field } from "./ui/Field";
import { PrimaryButton, TextLink } from "./ui/Buttons";
import { theme } from "../lib/theme";

type Props = {
  mode: "signup" | "login";
  email: string;
  setEmail: (s: string) => void;
  password: string;
  setPassword: (s: string) => void;
  name?: string;
  setName?: (s: string) => void;
  loading: boolean;
  error: string | null;
  onSubmit: () => void;
  forgotPasswordSlot?: ReactNode;
};

export function AuthForm({
  mode,
  email,
  setEmail,
  password,
  setPassword,
  name,
  setName,
  loading,
  error,
  onSubmit,
  forgotPasswordSlot,
}: Props) {
  const isSignup = mode === "signup";

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg }}>
      {/* Radial mint glow at top */}
      <View
        pointerEvents="none"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 320,
          backgroundColor: theme.bg,
        }}
      >
        <View
          style={{
            flex: 1,
            backgroundColor: theme.accent,
            opacity: 0.08,
            borderBottomLeftRadius: 1000,
            borderBottomRightRadius: 1000,
            transform: [{ scaleX: 2 }],
          }}
        />
      </View>

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView
          contentContainerStyle={{ flexGrow: 1 }}
          keyboardShouldPersistTaps="handled"
        >
          <View
            style={{
              paddingHorizontal: theme.spacing.xl,
              paddingTop: 48,
              gap: theme.spacing.xxl,
            }}
          >
            <Text
              style={{
                color: theme.accent,
                fontSize: theme.fontSizes.xxl,
                fontWeight: theme.fontWeights.bold,
                letterSpacing: theme.tracking.display,
              }}
            >
              Muzo
            </Text>

            <View style={{ gap: theme.spacing.sm }}>
              <Text
                style={{
                  color: theme.text,
                  fontSize: theme.fontSizes.xxl,
                  fontWeight: theme.fontWeights.bold,
                  letterSpacing: theme.tracking.display,
                  lineHeight:
                    theme.fontSizes.xxl * theme.lineHeights.tight,
                }}
              >
                {isSignup ? "Better replies, every time." : "Welcome back."}
              </Text>
              <Text
                style={{
                  color: theme.dim,
                  fontSize: theme.fontSizes.md,
                  lineHeight:
                    theme.fontSizes.md * theme.lineHeights.body,
                }}
              >
                {isSignup
                  ? "Generate 10 replies free. No credit card."
                  : "Pick up where you left off."}
              </Text>
            </View>

            <View style={{ gap: theme.spacing.md }}>
              <Field
                placeholder="you@email.com"
                value={email}
                onChangeText={setEmail}
                keyboardType="email-address"
                autoCapitalize="none"
                autoComplete="email"
                autoCorrect={false}
              />
              <Field
                placeholder="Password (8+ chars)"
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoComplete={isSignup ? "new-password" : "password"}
              />
              {isSignup && setName ? (
                <Field
                  placeholder="Display name (optional)"
                  value={name || ""}
                  onChangeText={setName}
                  autoCapitalize="words"
                />
              ) : null}
            </View>

            {error ? (
              <Text
                style={{
                  color: theme.error,
                  fontSize: theme.fontSizes.sm,
                  marginTop: -theme.spacing.lg,
                }}
              >
                {error}
              </Text>
            ) : null}

            <View style={{ gap: theme.spacing.md + 2 }}>
              <PrimaryButton
                label={isSignup ? "Create account" : "Log in"}
                onPress={onSubmit}
                loading={loading}
              />
              <View
                style={{
                  alignItems: "center",
                  flexDirection: "row",
                  justifyContent: "center",
                  gap: 4,
                }}
              >
                <Text
                  style={{
                    color: theme.dim,
                    fontSize: theme.fontSizes.md,
                  }}
                >
                  {isSignup ? "Have an account? " : "New here? "}
                </Text>
                <Link
                  href={isSignup ? "/(auth)/login" : "/(auth)/signup"}
                  replace
                >
                  <Text
                    style={{
                      color: theme.accent,
                      fontSize: theme.fontSizes.md,
                      fontWeight: theme.fontWeights.semibold,
                    }}
                  >
                    {isSignup ? "Log in" : "Sign up"}
                  </Text>
                </Link>
              </View>
              {!isSignup && forgotPasswordSlot ? (
                <View style={{ alignItems: "center" }}>
                  {forgotPasswordSlot}
                </View>
              ) : null}
            </View>
          </View>

          <View style={{ flex: 1 }} />

          <View
            style={{
              paddingHorizontal: theme.spacing.xl,
              paddingTop: theme.spacing.lg,
              paddingBottom: theme.spacing.xl,
              alignItems: "center",
            }}
          >
            <Text
              style={{
                color: theme.dimmer,
                fontSize: 12,
                lineHeight: 18,
                textAlign: "center",
              }}
            >
              By continuing you agree to the{" "}
              <Text
                style={{
                  color: theme.dim,
                  fontWeight: theme.fontWeights.semibold,
                }}
              >
                Terms of Service
              </Text>
              {" and "}
              <Text
                style={{
                  color: theme.dim,
                  fontWeight: theme.fontWeights.semibold,
                }}
              >
                Privacy Policy
              </Text>
              .
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
