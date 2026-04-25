// 3-step swipeable onboarding carousel. Shown on first launch after sign-up.
// Persists a "seen" flag via SecureStore so we don't show it twice.

import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Pressable, PrimaryButton } from "../components/ui";
import { markSeen } from "../lib/onboardingState";
import { theme } from "../lib/theme";

export default function OnboardingScreen() {
  const router = useRouter();
  const [step, setStep] = useState(0);

  const slides = [
    {
      h: "Stuck on what to say?",
      s: "Wingman writes the perfect reply in 3 seconds.",
      body: <FrozenChat />,
    },
    {
      h: "Just take a screenshot",
      s: "We read your chat and generate 5 angles, instantly.",
      body: <FlowDiagram />,
    },
    {
      h: "Tap to copy. Paste. Win.",
      s: "10 free replies to start. No credit card.",
      body: <CopyDemo />,
    },
  ];
  const last = step === slides.length - 1;
  const slide = slides[step];

  const finish = async () => {
    // Persist + flip the in-memory flag so AuthGate re-renders and
    // routes us to "/" instead of bouncing back to onboarding.
    await markSeen();
    router.replace("/");
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg }}>
      {/* Radial mint glow */}
      <View
        pointerEvents="none"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 320,
        }}
      >
        <View
          style={{
            flex: 1,
            backgroundColor: theme.accent,
            opacity: 0.1,
            borderBottomLeftRadius: 1000,
            borderBottomRightRadius: 1000,
            transform: [{ scaleX: 2 }],
          }}
        />
      </View>

      <View
        style={{
          flexDirection: "row",
          justifyContent: "flex-end",
          paddingHorizontal: theme.spacing.xl,
          paddingTop: theme.spacing.lg,
        }}
      >
        <Pressable onPress={finish}>
          <Text
            style={{
              color: theme.dim,
              fontSize: theme.fontSizes.md,
              fontWeight: theme.fontWeights.semibold,
            }}
          >
            Skip
          </Text>
        </Pressable>
      </View>

      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          paddingHorizontal: theme.spacing.xxl,
          gap: theme.spacing.xxl,
        }}
      >
        {slide.body}
        <View style={{ alignItems: "center", gap: theme.spacing.md, maxWidth: 320 }}>
          <Text
            style={{
              color: theme.text,
              fontSize: theme.fontSizes.xxl,
              fontWeight: theme.fontWeights.bold,
              letterSpacing: theme.tracking.display,
              textAlign: "center",
              lineHeight: theme.fontSizes.xxl * theme.lineHeights.tight,
            }}
          >
            {slide.h}
          </Text>
          <Text
            style={{
              color: theme.dim,
              fontSize: theme.fontSizes.md,
              lineHeight: theme.fontSizes.md * theme.lineHeights.reply,
              textAlign: "center",
            }}
          >
            {slide.s}
          </Text>
        </View>
      </View>

      <View
        style={{
          paddingHorizontal: theme.spacing.xl,
          paddingBottom: theme.spacing.xxl,
          gap: theme.spacing.xl,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            justifyContent: "center",
            gap: theme.spacing.sm,
          }}
        >
          {slides.map((_, i) => (
            <View
              key={i}
              style={{
                width: i === step ? 20 : 6,
                height: 6,
                borderRadius: 3,
                backgroundColor: i === step ? theme.accent : theme.dimmer,
              }}
            />
          ))}
        </View>
        <PrimaryButton
          label={last ? "Get started" : "Next"}
          onPress={() => (last ? finish() : setStep(step + 1))}
        />
      </View>
    </SafeAreaView>
  );
}

/* ───────────── Illustrations ───────────── */

function FrozenChat() {
  return (
    <View
      style={{
        width: 200,
        padding: theme.spacing.md + 2,
        backgroundColor: theme.surface,
        borderRadius: theme.radii.lg,
        borderWidth: 1,
        borderColor: theme.border,
        gap: theme.spacing.sm,
      }}
    >
      <Bar w="70%" />
      <Bar w="85%" />
      <Bar w="50%" alignEnd accent />
      <View
        style={{
          height: 36,
          marginTop: theme.spacing.sm,
          borderWidth: 1.5,
          borderColor: theme.dimmer,
          borderStyle: "dashed",
          borderRadius: 8,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Text style={{ color: theme.dimmer, fontSize: 12 }}>typing…</Text>
      </View>
    </View>
  );
}

function FlowDiagram() {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.lg }}>
      <View
        style={{
          width: 80,
          height: 130,
          backgroundColor: theme.surface,
          borderRadius: 12,
          borderWidth: 1,
          borderColor: theme.border,
        }}
      />
      <Text style={{ color: theme.accent, fontSize: theme.fontSizes.xxl }}>→</Text>
      <View style={{ gap: 4 }}>
        {[0, 1, 2, 3, 4].map((i) => (
          <View
            key={i}
            style={{
              width: 80,
              height: 22,
              backgroundColor: theme.surface,
              borderRadius: 6,
              borderWidth: 1,
              borderColor: theme.border,
            }}
          />
        ))}
      </View>
    </View>
  );
}

function CopyDemo() {
  return (
    <View
      style={{
        width: 220,
        backgroundColor: theme.surface,
        borderWidth: 2,
        borderColor: theme.accent,
        borderRadius: 14,
        padding: theme.spacing.md,
        gap: 6,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
        }}
      >
        <Text
          style={{
            fontSize: 10,
            fontWeight: theme.fontWeights.bold,
            letterSpacing: theme.tracking.label,
            color: theme.angle.PLAYFUL,
          }}
        >
          PLAYFUL
        </Text>
        <Text
          style={{
            fontSize: 11,
            color: theme.accent,
            fontWeight: theme.fontWeights.semibold,
          }}
        >
          Copied ✓
        </Text>
      </View>
      <Text style={{ color: theme.text, fontSize: 13 }}>
        Busy is a personality trait now? Bold of you.
      </Text>
    </View>
  );
}

function Bar({
  w,
  alignEnd,
  accent,
}: {
  w: string;
  alignEnd?: boolean;
  accent?: boolean;
}) {
  return (
    <View
      style={{
        height: 16,
        width: w as any,
        borderRadius: 8,
        backgroundColor: accent ? theme.accentDim : theme.surface2,
        alignSelf: alignEnd ? "flex-end" : "flex-start",
      }}
    />
  );
}
