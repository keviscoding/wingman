// Paywall — modal sheet that slides up from the bottom.
// Shown when a generation request returns 402 (free trial / daily cap)
// or when the user explicitly taps "Upgrade".
//
// Plans + IAP wiring will go through RevenueCat — for now this is the
// visual scaffold that fires `onSubscribe(planId)` so we can swap in
// `Purchases.purchasePackage(...)` later without UI changes.

import { useEffect, useRef, useState } from "react";
import {
  Animated,
  Dimensions,
  Easing,
  Linking,
  Pressable as RNPressable,
  Text,
  View,
} from "react-native";
import { Pressable, PrimaryButton, TextLink } from "./ui";
import { theme } from "../lib/theme";

type Plan = {
  id: "weekly" | "monthly" | "yearly";
  title: string;
  price: string;
  sub: string;
  tag?: string;
};

const PLANS: Plan[] = [
  { id: "weekly", title: "Weekly", price: "$4.99 / wk", sub: "Quick boost" },
  {
    id: "monthly",
    title: "Monthly",
    price: "$14.99 / mo",
    sub: "Most popular",
    tag: "MOST POPULAR",
  },
  {
    id: "yearly",
    title: "Yearly",
    price: "$89 / yr",
    sub: "Save 50% vs monthly",
    tag: "SAVE 50%",
  },
];

type Props = {
  visible: boolean;
  onDismiss: () => void;
  onSubscribe?: (planId: Plan["id"]) => void;
  // Optional alternate header copy (e.g. paywall during generation)
  pretitle?: string;
  title?: string;
  subtitle?: string;
  cta?: string;
};

export function PaywallSheet({
  visible,
  onDismiss,
  onSubscribe,
  pretitle,
  title = "Out of free replies",
  subtitle = "Upgrade to keep generating. Cancel anytime.",
  cta = "Start free trial",
}: Props) {
  const [selected, setSelected] = useState<Plan["id"]>("monthly");
  const translate = useRef(new Animated.Value(Dimensions.get("window").height)).current;
  const scrim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (visible) {
      Animated.parallel([
        Animated.timing(translate, {
          toValue: 0,
          duration: theme.motion.slow,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(scrim, {
          toValue: 1,
          duration: theme.motion.slow,
          useNativeDriver: true,
        }),
      ]).start();
    } else {
      Animated.parallel([
        Animated.timing(translate, {
          toValue: Dimensions.get("window").height,
          duration: theme.motion.base,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(scrim, {
          toValue: 0,
          duration: theme.motion.base,
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [visible, translate, scrim]);

  if (!visible) return null;

  return (
    <View
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 100,
      }}
      pointerEvents={visible ? "auto" : "none"}
    >
      <Animated.View
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "rgba(0,0,0,0.7)",
          opacity: scrim,
        }}
      >
        <RNPressable onPress={onDismiss} style={{ flex: 1 }} />
      </Animated.View>

      <Animated.View
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: theme.bg,
          borderTopLeftRadius: theme.radii.xl,
          borderTopRightRadius: theme.radii.xl,
          borderTopWidth: 1,
          borderTopColor: theme.border,
          padding: theme.spacing.lg,
          paddingTop: theme.spacing.md,
          paddingBottom: theme.spacing.xxl,
          gap: theme.spacing.lg,
          transform: [{ translateY: translate }],
        }}
      >
        {/* drag handle */}
        <View
          style={{
            alignItems: "center",
            paddingTop: 4,
            paddingBottom: 4,
          }}
        >
          <View
            style={{
              width: 40,
              height: 4,
              borderRadius: 2,
              backgroundColor: theme.dimmer,
            }}
          />
        </View>

        <View
          style={{
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "flex-start",
          }}
        >
          <View style={{ flex: 1, gap: theme.spacing.xs }}>
            {pretitle ? (
              <Text
                style={{
                  fontSize: 11,
                  fontWeight: theme.fontWeights.bold,
                  letterSpacing: theme.tracking.label,
                  color: theme.accent,
                }}
              >
                {pretitle}
              </Text>
            ) : null}
            <Text
              style={{
                color: theme.text,
                fontSize: theme.fontSizes.xl,
                fontWeight: theme.fontWeights.bold,
                letterSpacing: theme.tracking.tight,
              }}
            >
              {title}
            </Text>
            <Text
              style={{
                color: theme.dim,
                fontSize: theme.fontSizes.md,
                lineHeight: theme.fontSizes.md * theme.lineHeights.body,
              }}
            >
              {subtitle}
            </Text>
          </View>
          <Pressable onPress={onDismiss}>
            <Text
              style={{
                color: theme.dim,
                fontSize: 22,
                fontWeight: theme.fontWeights.bold,
                paddingHorizontal: 4,
              }}
            >
              ⌄
            </Text>
          </Pressable>
        </View>

        <View style={{ gap: 10 }}>
          {PLANS.map((p) => (
            <PlanCard
              key={p.id}
              plan={p}
              selected={selected === p.id}
              onSelect={() => setSelected(p.id)}
            />
          ))}
        </View>

        <Text
          style={{
            color: theme.dimmer,
            fontSize: 12,
            textAlign: "center",
            lineHeight: 18,
          }}
        >
          Includes 7-day free trial · cancel anytime in your store
        </Text>

        <PrimaryButton
          label={cta}
          onPress={() => onSubscribe?.(selected) ?? onDismiss()}
        />

        <View
          style={{
            flexDirection: "row",
            justifyContent: "center",
            gap: theme.spacing.lg,
          }}
        >
          <TextLink label="Restore" onPress={() => {}} size={theme.fontSizes.sm} />
          <TextLink
            label="Privacy"
            onPress={() => Linking.openURL("https://wingman.app/privacy")}
            size={theme.fontSizes.sm}
          />
          <TextLink
            label="Terms"
            onPress={() => Linking.openURL("https://wingman.app/terms")}
            size={theme.fontSizes.sm}
          />
        </View>
      </Animated.View>
    </View>
  );
}

function PlanCard({
  plan,
  selected,
  onSelect,
}: {
  plan: Plan;
  selected: boolean;
  onSelect: () => void;
}) {
  const isPopular = plan.tag === "MOST POPULAR";
  return (
    <Pressable onPress={onSelect}>
      <View
        style={{
          position: "relative",
          backgroundColor: theme.surface,
          borderWidth: selected ? 2 : 1,
          borderColor: selected ? theme.accent : theme.border,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.lg,
          gap: theme.spacing.xs,
        }}
      >
        {plan.tag ? (
          <View
            style={{
              position: "absolute",
              top: -10,
              right: 14,
              backgroundColor: isPopular ? theme.accent : theme.surface2,
              borderColor: isPopular ? "transparent" : theme.accent,
              borderWidth: isPopular ? 0 : 1,
              borderRadius: theme.radii.pill,
              paddingHorizontal: 8,
              paddingVertical: 4,
            }}
          >
            <Text
              style={{
                color: isPopular ? theme.bg : theme.accent,
                fontSize: 10,
                fontWeight: theme.fontWeights.bold,
                letterSpacing: theme.tracking.label,
              }}
            >
              {plan.tag}
            </Text>
          </View>
        ) : null}
        <View
          style={{
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "baseline",
          }}
        >
          <Text
            style={{
              color: theme.text,
              fontSize: theme.fontSizes.lg,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            {plan.title}
          </Text>
          <Text
            style={{
              color: selected ? theme.accent : theme.text,
              fontSize: theme.fontSizes.lg,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            {plan.price}
          </Text>
        </View>
        <Text style={{ color: theme.dim, fontSize: theme.fontSizes.sm }}>
          {plan.sub}
        </Text>
      </View>
    </Pressable>
  );
}
