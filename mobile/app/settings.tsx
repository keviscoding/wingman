// Settings — Account / Preferences / About sections.
// "Delete account" lives here and is required for store compliance.
// Tone slider sets a per-user default that biases reply generation.

import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Platform, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { registerWithServer } from "../lib/pushNotify";
import { theme } from "../lib/theme";
import { Pressable, TopBar } from "../components/ui";

export default function SettingsScreen() {
  const router = useRouter();
  const { me, signOut, token } = useAuth();

  const onTestPush = async () => {
    if (!token) return;

    // Try to send. If the server says we don't have a token, attempt
    // a fresh registration first then retry.
    const trySend = async () => {
      try {
        await api.testPush(token);
        Alert.alert(
          "Test sent",
          "If you don't see a notification within 5 seconds, check Settings → Apps → Wingman → Notifications.",
        );
        return true;
      } catch (e: any) {
        const detail = e instanceof ApiError ? e.detail : "request_failed";
        if (detail === "no_push_token_registered") return false;
        Alert.alert("Test failed", detail);
        return true; // don't retry on other errors
      }
    };

    const sent = await trySend();
    if (sent) return;

    // No token on server — register, then retry. Surface specific
    // failure modes so the user knows what to fix.
    const reg = await registerWithServer(token);
    if (!reg.ok) {
      const reason = reg.reason;
      const msg =
        reason === "module_missing"
          ? "Notifications aren't available in this build."
          : reason === "permission_denied"
            ? "Notifications permission is denied. Open Settings → Apps → Wingman → Notifications and enable, then try again."
            : reason === "no_token"
              ? `Couldn't get a push token from the OS${reg.detail ? ` (${reg.detail})` : ""}. This usually means Google Play Services is missing or push isn't supported on this device.`
              : `Server rejected the token registration${reg.detail ? `: ${reg.detail}` : ""}.`;
      Alert.alert("Couldn't enable push", msg, [
        reason === "permission_denied"
          ? { text: "Open settings", onPress: () => Linking.openSettings() }
          : { text: "OK" },
        { text: "Cancel", style: "cancel" },
      ]);
      return;
    }

    // Token registered — retry the test send.
    await trySend();
  };

  const onDeleteAccount = () => {
    Alert.alert(
      "Delete your account?",
      "This permanently removes your account, all chats, and all generated replies. We can't undo this.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            // Double-confirm — Play Store explicitly requires a
            // multi-step flow so deletion isn't a one-tap accident.
            Alert.alert(
              "Are you absolutely sure?",
              "This is permanent. Your account and all data will be erased immediately.",
              [
                { text: "Cancel", style: "cancel" },
                {
                  text: "Delete forever",
                  style: "destructive",
                  onPress: async () => {
                    if (!token) {
                      await signOut();
                      return;
                    }
                    try {
                      await api.deleteAccount(token);
                    } catch (e: any) {
                      const detail =
                        e instanceof ApiError ? e.detail : "request_failed";
                      // 401 = token already invalid (server-side
                      // delete must have already happened, or auth
                      // expired). Either way, sign out locally.
                      if (detail !== "invalid_or_expired_token") {
                        Alert.alert(
                          "Couldn't delete account",
                          "Server didn't confirm the delete. Try again, or contact kevis2busy@gmail.com.",
                        );
                        return;
                      }
                    }
                    // Always sign out client-side after a successful
                    // (or already-completed) delete.
                    await signOut();
                  },
                },
              ],
            );
          },
        },
      ],
    );
  };

  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: theme.bg }}>
      <TopBar mode="stack" title="Settings" onBack={() => router.back()} />

      <ScrollView
        contentContainerStyle={{
          padding: theme.spacing.lg,
          paddingBottom: 48,
          gap: theme.spacing.xl,
        }}
      >
        <Section label="Account">
          <Row label="Email" detail={me?.email || "—"} />
          <Row
            label="Display name"
            detail={me?.display_name || "—"}
            chevron
          />
          <Row
            label="Plan"
            detail={
              <Text
                style={{
                  color: me?.is_subscribed ? theme.accent : theme.dim,
                  fontWeight: theme.fontWeights.bold,
                }}
              >
                {me?.is_subscribed ? "Pro" : "Free"}
              </Text>
            }
            chevron
          />
          <Row
            label="Manage subscription"
            chevron
            onPress={() =>
              Linking.openURL(
                Platform.OS === "ios"
                  ? "https://apps.apple.com/account/subscriptions"
                  : "https://play.google.com/store/account/subscriptions",
              )
            }
          />
          <Row
            label="Delete account"
            danger
            onPress={onDeleteAccount}
            isLast
          />
        </Section>

        <Section label="Preferences">
          <Row label="Theme" detail="Dark" chevron />
          <ToneRow />
          <Row label="Save chats automatically" toggle on />
          <Row label="Haptic feedback" toggle on />
          <Row
            label="Send test notification"
            chevron
            onPress={onTestPush}
            isLast
          />
        </Section>

        <Section label="About">
          <Row
            label="Privacy Policy"
            chevron
            onPress={() => Linking.openURL("https://cliprr.io/wingman/privacy.html")}
          />
          <Row
            label="Terms of Service"
            chevron
            onPress={() => Linking.openURL("https://cliprr.io/wingman/terms.html")}
          />
          <Row
            label="Contact support"
            chevron
            onPress={() => Linking.openURL("mailto:contact@cliprr.io")}
          />
          <Row label="Version" detail="1.0.0 (build 1)" isLast />
        </Section>

        <Pressable onPress={signOut}>
          <Text
            style={{
              textAlign: "center",
              color: theme.dimmer,
              fontSize: theme.fontSizes.sm,
              padding: theme.spacing.sm,
            }}
          >
            Sign out
          </Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

/* ───────────── Building blocks ───────────── */

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <View style={{ gap: theme.spacing.sm }}>
      <Text
        style={{
          paddingHorizontal: 6,
          fontSize: 11,
          fontWeight: theme.fontWeights.bold,
          letterSpacing: theme.tracking.label,
          textTransform: "uppercase",
          color: theme.dim,
        }}
      >
        {label}
      </Text>
      <View
        style={{
          backgroundColor: theme.surface,
          borderWidth: 1,
          borderColor: theme.border,
          borderRadius: theme.radii.lg,
          overflow: "hidden",
        }}
      >
        {children}
      </View>
    </View>
  );
}

type RowProps = {
  label: string;
  detail?: React.ReactNode;
  chevron?: boolean;
  danger?: boolean;
  toggle?: boolean;
  on?: boolean;
  isLast?: boolean;
  onPress?: () => void;
};

function Row({
  label,
  detail,
  chevron,
  danger,
  toggle,
  on,
  isLast,
  onPress,
}: RowProps) {
  const content = (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: 14,
        borderBottomWidth: isLast ? 0 : 1,
        borderBottomColor: theme.border,
      }}
    >
      <Text
        style={{
          color: danger ? theme.error : theme.text,
          fontSize: theme.fontSizes.md,
          fontWeight: theme.fontWeights.medium,
        }}
      >
        {label}
      </Text>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: theme.spacing.sm,
        }}
      >
        {detail ? (
          typeof detail === "string" || typeof detail === "number" ? (
            <Text style={{ color: theme.dim, fontSize: 14 }}>{detail}</Text>
          ) : (
            detail
          )
        ) : null}
        {toggle ? <Toggle on={on} /> : null}
        {chevron ? <Chevron /> : null}
      </View>
    </View>
  );
  if (onPress) {
    return <Pressable onPress={onPress}>{content}</Pressable>;
  }
  return content;
}

function Chevron() {
  return (
    <Text
      style={{
        color: theme.dimmer,
        fontSize: 16,
        fontWeight: theme.fontWeights.bold,
      }}
    >
      ›
    </Text>
  );
}

function Toggle({ on }: { on?: boolean }) {
  return (
    <View
      style={{
        width: 42,
        height: 26,
        borderRadius: 13,
        backgroundColor: on ? theme.accent : theme.surface2,
        borderWidth: on ? 0 : 1,
        borderColor: theme.border,
        padding: 2,
        flexDirection: "row",
        justifyContent: on ? "flex-end" : "flex-start",
      }}
    >
      <View
        style={{
          width: 22,
          height: 22,
          borderRadius: 11,
          backgroundColor: "#fff",
        }}
      />
    </View>
  );
}

function ToneRow() {
  const [val, setVal] = useState(6);
  const label = val < 4 ? "Bold" : val < 7 ? "Balanced" : "Receptive";

  return (
    <View
      style={{
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: 14,
        borderBottomWidth: 1,
        borderBottomColor: theme.border,
        gap: 10,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <Text
          style={{
            color: theme.text,
            fontSize: theme.fontSizes.md,
            fontWeight: theme.fontWeights.medium,
          }}
        >
          Default tone
        </Text>
        <Text
          style={{
            color: theme.accent,
            fontSize: theme.fontSizes.sm,
            fontWeight: theme.fontWeights.semibold,
          }}
        >
          {label}
        </Text>
      </View>

      {/* Quick tap-to-set buckets while we don't have a real RN slider */}
      <View
        style={{
          flexDirection: "row",
          gap: 4,
        }}
      >
        {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => (
          <Pressable key={i} onPress={() => setVal(i)} style={{ flex: 1 }}>
            <View
              style={{
                height: 4,
                borderRadius: 2,
                backgroundColor: i <= val ? theme.accent : theme.surface2,
              }}
            />
          </Pressable>
        ))}
      </View>

      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
        }}
      >
        <Text
          style={{
            color: theme.dimmer,
            fontSize: 11,
            fontWeight: theme.fontWeights.semibold,
            letterSpacing: 0.4,
          }}
        >
          BOLD
        </Text>
        <Text
          style={{
            color: theme.dimmer,
            fontSize: 11,
            fontWeight: theme.fontWeights.semibold,
            letterSpacing: 0.4,
          }}
        >
          RECEPTIVE
        </Text>
      </View>
    </View>
  );
}
