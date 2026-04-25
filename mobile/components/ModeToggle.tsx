// Fast / Pro mode toggle. Pill-shaped with two segments — left (Fast)
// is the default. Right (Pro) is mint-accented and has a small "PRO"
// badge for free users to signal it's gated.
//
// We deliberately don't expose model names ("Gemini 3.1 Pro") in the
// UI — competitors would copy. Users just see "Fast" vs "Pro".

import { Text, View } from "react-native";
import { Pressable } from "./ui";
import { GenerationMode } from "../lib/api";
import { useAuth } from "../lib/auth";
import { theme } from "../lib/theme";

type Props = {
  mode: GenerationMode;
  onChange: (m: GenerationMode) => void;
  // Compact variant for headers / inline placement
  size?: "default" | "sm";
};

export function ModeToggle({ mode, onChange, size = "default" }: Props) {
  const { me } = useAuth();
  const isLocked = !!me && !me.is_subscribed && (me.pro_lifetime_used >= (me.free_pro_lifetime_trial ?? 2));
  const trialLeft = me
    ? Math.max(0, (me.free_pro_lifetime_trial ?? 2) - (me.pro_lifetime_used ?? 0))
    : 0;

  const px = size === "sm" ? 12 : 16;
  const py = size === "sm" ? 6 : 8;
  const fs = size === "sm" ? 12 : 13;

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        backgroundColor: theme.surface2,
        borderRadius: theme.radii.pill,
        padding: 3,
        borderWidth: 1,
        borderColor: theme.border,
      }}
    >
      <Segment
        active={mode === "fast"}
        onPress={() => onChange("fast")}
        px={px}
        py={py}
        fs={fs}
      >
        Fast
      </Segment>
      <Segment
        active={mode === "pro"}
        onPress={() => onChange("pro")}
        px={px}
        py={py}
        fs={fs}
        accent
        suffix={
          me?.is_subscribed
            ? null
            : isLocked
              ? <Pill text="UPGRADE" />
              : trialLeft > 0
                ? <Pill text={`${trialLeft} TRIAL`} />
                : null
        }
      >
        Pro
      </Segment>
    </View>
  );
}

function Segment({
  active,
  accent,
  onPress,
  children,
  suffix,
  px,
  py,
  fs,
}: {
  active: boolean;
  accent?: boolean;
  onPress: () => void;
  children: React.ReactNode;
  suffix?: React.ReactNode;
  px: number;
  py: number;
  fs: number;
}) {
  return (
    <Pressable onPress={onPress}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          backgroundColor: active
            ? accent
              ? theme.accent
              : theme.surface
            : "transparent",
          borderRadius: theme.radii.pill,
          paddingHorizontal: px,
          paddingVertical: py,
        }}
      >
        <Text
          style={{
            color: active ? (accent ? theme.bg : theme.text) : theme.dim,
            fontSize: fs,
            fontWeight: theme.fontWeights.bold,
            letterSpacing: 0.2,
          }}
        >
          {children}
        </Text>
        {suffix}
      </View>
    </Pressable>
  );
}

function Pill({ text }: { text: string }) {
  return (
    <View
      style={{
        backgroundColor: "rgba(0,0,0,0.25)",
        paddingHorizontal: 6,
        paddingVertical: 2,
        borderRadius: theme.radii.pill,
      }}
    >
      <Text
        style={{
          color: "#fff",
          fontSize: 9,
          fontWeight: theme.fontWeights.bold,
          letterSpacing: 0.6,
        }}
      >
        {text}
      </Text>
    </View>
  );
}
