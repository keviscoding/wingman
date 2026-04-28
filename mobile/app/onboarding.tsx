// Onboarding — 4-screen swipeable carousel shown once on first launch.
//
// Goals (in order of importance):
//   1. Hook the user's pain in the first 2 seconds (slide 1)
//   2. Show the loop in concrete terms (slide 2)
//   3. Tease the upgrade pitch without being pushy (slide 3)
//   4. Hand-hold to the first action (slide 4 → home)
//
// All transitions are animated (fade + horizontal slide) for that
// "this app cost actual money" feel. Industry standard for premium
// consumer apps.

import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
  Animated,
  Dimensions,
  Easing,
  Image,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Pressable, PrimaryButton } from "../components/ui";
import { markSeen } from "../lib/onboardingState";
import { theme } from "../lib/theme";

const { width: SCREEN_W } = Dimensions.get("window");

type Slide = {
  pretitle?: string;
  h: string;
  s: string;
  body: () => React.ReactNode;
};

export default function OnboardingScreen() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const fade = useRef(new Animated.Value(1)).current;
  const slide = useRef(new Animated.Value(0)).current;

  const slides: Slide[] = [
    {
      pretitle: "MUZO",
      h: "Reply like you mean it.",
      s: "The texting cheat code your friends won't tell you about.",
      body: () => <BrandHero />,
    },
    {
      h: "Stop staring at the screen.",
      s: "Drop a screenshot of any chat — Muzo writes the perfect reply in seconds.",
      body: () => <FlowDiagram />,
    },
    {
      pretitle: "QUICK · PRO",
      h: "Two modes. One unfair edge.",
      s: "Quick keeps the convo moving. Pro is the closer — for replies that decide things.",
      body: () => <ModePreview />,
    },
    {
      h: "Tap to copy. Paste. Win.",
      s: "10 free replies on signup. No card.",
      body: () => <CopyDemo />,
    },
  ];

  const last = step === slides.length - 1;
  const current = slides[step];

  // Animate transitions when step changes — fade out, swap, fade in.
  const goTo = (next: number) => {
    if (next === step) return;
    const dir = next > step ? -1 : 1; // slide content in opposite direction
    Animated.parallel([
      Animated.timing(fade, {
        toValue: 0,
        duration: 140,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }),
      Animated.timing(slide, {
        toValue: dir * 30,
        duration: 140,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }),
    ]).start(() => {
      setStep(next);
      slide.setValue(-dir * 30);
      Animated.parallel([
        Animated.timing(fade, {
          toValue: 1,
          duration: 220,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(slide, {
          toValue: 0,
          duration: 220,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
      ]).start();
    });
  };

  const finish = async () => {
    await markSeen();
    router.replace("/");
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg }}>
      {/* Radial mint glow at top — subtle brand atmosphere */}
      <View
        pointerEvents="none"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 360,
        }}
      >
        <View
          style={{
            flex: 1,
            backgroundColor: theme.accent,
            opacity: 0.12,
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

      <Animated.View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          paddingHorizontal: theme.spacing.xxl,
          gap: theme.spacing.xxl,
          opacity: fade,
          transform: [{ translateX: slide }],
        }}
      >
        {current.body()}
        <View
          style={{
            alignItems: "center",
            gap: theme.spacing.md,
            maxWidth: SCREEN_W - 64,
          }}
        >
          {current.pretitle ? (
            <Text
              style={{
                color: theme.accent,
                fontSize: 11,
                fontWeight: theme.fontWeights.bold,
                letterSpacing: theme.tracking.label,
              }}
            >
              {current.pretitle}
            </Text>
          ) : null}
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
            {current.h}
          </Text>
          <Text
            style={{
              color: theme.dim,
              fontSize: theme.fontSizes.md,
              lineHeight: theme.fontSizes.md * theme.lineHeights.reply,
              textAlign: "center",
            }}
          >
            {current.s}
          </Text>
        </View>
      </Animated.View>

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
                width: i === step ? 24 : 6,
                height: 6,
                borderRadius: 3,
                backgroundColor: i === step ? theme.accent : theme.dimmer,
              }}
            />
          ))}
        </View>
        <PrimaryButton
          label={last ? "Get started" : "Next"}
          onPress={() => (last ? finish() : goTo(step + 1))}
        />
      </View>
    </SafeAreaView>
  );
}

/* ───────────── Illustrations ───────────── */

function BrandHero() {
  // The Muzo wordmark + chameleon. Sets the brand identity in the
  // first split-second of onboarding.
  return (
    <View
      style={{
        width: 220,
        height: 220,
        borderRadius: 32,
        backgroundColor: "#000",
        alignItems: "center",
        justifyContent: "center",
        borderWidth: 1,
        borderColor: theme.border,
        shadowColor: theme.accent,
        shadowOpacity: 0.25,
        shadowRadius: 24,
        shadowOffset: { width: 0, height: 8 },
      }}
    >
      <Image
        source={require("../assets/icon.png")}
        style={{ width: 200, height: 200, borderRadius: 28 }}
        resizeMode="contain"
      />
    </View>
  );
}

function FlowDiagram() {
  // Screenshot → arrow → 5 reply suggestions.
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.lg }}>
      <View
        style={{
          width: 90,
          height: 140,
          backgroundColor: theme.surface,
          borderRadius: 14,
          borderWidth: 1,
          borderColor: theme.border,
          padding: 8,
          gap: 4,
        }}
      >
        <Bar w="80%" />
        <Bar w="60%" />
        <Bar w="90%" alignEnd accent />
        <Bar w="70%" />
        <Bar w="50%" alignEnd accent />
      </View>
      <Text style={{ color: theme.accent, fontSize: theme.fontSizes.xxl }}>→</Text>
      <View style={{ gap: 5 }}>
        {[0, 1, 2, 3, 4].map((i) => (
          <View
            key={i}
            style={{
              width: 90,
              height: 22,
              backgroundColor: i === 1 ? theme.accentDim : theme.surface,
              borderRadius: 6,
              borderWidth: 1,
              borderColor: i === 1 ? theme.accent : theme.border,
            }}
          />
        ))}
      </View>
    </View>
  );
}

function ModePreview() {
  // Pill toggle showing Quick / Pro segments — same component
  // language as the live home screen, just non-interactive here.
  return (
    <View style={{ alignItems: "center", gap: theme.spacing.lg }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          backgroundColor: theme.surface2,
          borderRadius: theme.radii.pill,
          padding: 4,
          borderWidth: 1,
          borderColor: theme.border,
        }}
      >
        <View
          style={{
            paddingHorizontal: 18,
            paddingVertical: 8,
            borderRadius: theme.radii.pill,
            backgroundColor: theme.surface,
          }}
        >
          <Text
            style={{
              color: theme.text,
              fontSize: 13,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            Quick
          </Text>
        </View>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            paddingHorizontal: 18,
            paddingVertical: 8,
          }}
        >
          <Text
            style={{
              color: theme.accent,
              fontSize: 13,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            Pro
          </Text>
          <View
            style={{
              backgroundColor: theme.accent,
              paddingHorizontal: 6,
              paddingVertical: 1,
              borderRadius: theme.radii.pill,
            }}
          >
            <Text
              style={{
                color: theme.bg,
                fontSize: 9,
                fontWeight: theme.fontWeights.bold,
                letterSpacing: theme.tracking.label,
              }}
            >
              CLOSER
            </Text>
          </View>
        </View>
      </View>
      <View style={{ alignItems: "center", gap: 6 }}>
        <Text
          style={{
            color: theme.dim,
            fontSize: 13,
            textAlign: "center",
            maxWidth: 260,
          }}
        >
          Quick — instant, free daily.
        </Text>
        <Text
          style={{
            color: theme.dim,
            fontSize: 13,
            textAlign: "center",
            maxWidth: 260,
          }}
        >
          Pro — for the messages that matter.
        </Text>
      </View>
    </View>
  );
}

function CopyDemo() {
  return (
    <View
      style={{
        width: 240,
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
          THE REFRAME
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
      <Text style={{ color: theme.text, fontSize: 13, lineHeight: 18 }}>
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
        height: 12,
        width: w as any,
        borderRadius: 6,
        backgroundColor: accent ? theme.accentDim : theme.surface2,
        alignSelf: alignEnd ? "flex-end" : "flex-start",
      }}
    />
  );
}
