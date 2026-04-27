// Paywall — modal sheet that slides up from the bottom.
//
// Shown when a generation request returns 402 (free trial / daily cap),
// when a Pro user qualifies for the Pro Max upsell, or when the user
// explicitly taps "Upgrade".
//
// Two product lines:
//   • Pro      $14.99/mo  or  $89.99/yr  ← standard subscriber
//   • Pro Max  $29.99/mo  or  $199.99/yr ← whale tier, near-unlimited
//
// Yearly is highlighted as the default selection because it has by far
// the best LTV (lower churn, fewer billing-cycle cancel decisions).
//
// IAP wiring will go through RevenueCat — for now this is the visual
// scaffold that fires `onSubscribe(planId)` so we can swap in
// `Purchases.purchasePackage(...)` later without touching the UI.

import { useEffect, useRef, useState } from "react";
import {
  Animated,
  Dimensions,
  Easing,
  Linking,
  Pressable as RNPressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { Pressable, PrimaryButton, TextLink } from "./ui";
import { theme } from "../lib/theme";

export type PlanId =
  | "pro_monthly"
  | "pro_yearly"
  | "pro_max_monthly"
  | "pro_max_yearly";

type Plan = {
  id: PlanId;
  tier: "pro" | "pro_max";
  title: string;
  price: string;
  perMonth?: string; // for yearly plans, show effective monthly price
  bullets: string[];
  tag?: string;
  highlight?: boolean;
};

const PLANS: Plan[] = [
  {
    id: "pro_monthly",
    tier: "pro",
    title: "Pro",
    price: "$14.99 / mo",
    bullets: ["Unlimited Quick replies", "30 Pro replies / day", "Push notifications"],
  },
  {
    id: "pro_yearly",
    tier: "pro",
    title: "Pro · Yearly",
    price: "$89.99 / yr",
    perMonth: "$7.50 / mo",
    bullets: ["Everything in Pro", "Save 50% vs monthly"],
    tag: "SAVE 50%",
  },
  {
    id: "pro_max_monthly",
    tier: "pro_max",
    title: "Pro Max",
    price: "$29.99 / mo",
    bullets: [
      "Everything in Pro",
      "100 Pro replies / day (effectively unlimited)",
      "Priority queue — faster generations",
      "Early access to new features",
    ],
    tag: "POWER USER",
    highlight: true,
  },
  {
    id: "pro_max_yearly",
    tier: "pro_max",
    title: "Pro Max · Yearly",
    price: "$199.99 / yr",
    perMonth: "$16.66 / mo",
    bullets: ["Everything in Pro Max", "Save ~45% vs monthly"],
    tag: "BEST VALUE",
  },
];

type Props = {
  visible: boolean;
  onDismiss: () => void;
  onSubscribe?: (planId: PlanId) => void;
  pretitle?: string;
  title?: string;
  subtitle?: string;
  cta?: string;
  /** When true, default the selection to Pro Max — used when a
   *  Pro subscriber is being upsold to Pro Max. */
  upsellMode?: boolean;
};

export function PaywallSheet({
  visible,
  onDismiss,
  onSubscribe,
  pretitle,
  title,
  subtitle,
  cta = "Start 7-day free trial",
  upsellMode = false,
}: Props) {
  const defaultPlan: PlanId = upsellMode ? "pro_max_yearly" : "pro_yearly";
  const [selected, setSelected] = useState<PlanId>(defaultPlan);
  const translate = useRef(new Animated.Value(Dimensions.get("window").height)).current;
  const scrim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (visible) setSelected(defaultPlan);
  }, [visible, defaultPlan]);

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

  const headerTitle =
    title ??
    (upsellMode ? "Ready for Pro Max?" : "Upgrade to keep generating");
  const headerSubtitle =
    subtitle ??
    (upsellMode
      ? "You've been hitting the Pro daily cap. Pro Max gives you 100 Pro replies a day, priority queue, and early features."
      : "Pro unlocks unlimited Quick replies and the high-quality Pro mode.");

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
          maxHeight: "92%",
          backgroundColor: theme.bg,
          borderTopLeftRadius: theme.radii.xl,
          borderTopRightRadius: theme.radii.xl,
          borderTopWidth: 1,
          borderTopColor: theme.border,
          transform: [{ translateY: translate }],
        }}
      >
        {/* drag handle */}
        <View
          style={{
            alignItems: "center",
            paddingTop: 8,
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

        <ScrollView
          contentContainerStyle={{
            padding: theme.spacing.lg,
            paddingTop: theme.spacing.md,
            paddingBottom: theme.spacing.xxl,
            gap: theme.spacing.lg,
          }}
          showsVerticalScrollIndicator={false}
        >
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
                {headerTitle}
              </Text>
              <Text
                style={{
                  color: theme.dim,
                  fontSize: theme.fontSizes.md,
                  lineHeight: theme.fontSizes.md * theme.lineHeights.body,
                }}
              >
                {headerSubtitle}
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
            7-day free trial · cancel anytime in your store · auto-renews
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
              onPress={() =>
                Linking.openURL("https://cliprr.io/wingman/privacy.html")
              }
              size={theme.fontSizes.sm}
            />
            <TextLink
              label="Terms"
              onPress={() =>
                Linking.openURL("https://cliprr.io/wingman/terms.html")
              }
              size={theme.fontSizes.sm}
            />
          </View>
        </ScrollView>
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
  const isHighlight = !!plan.highlight;
  return (
    <Pressable onPress={onSelect}>
      <View
        style={{
          position: "relative",
          backgroundColor: isHighlight ? theme.accentDim : theme.surface,
          borderWidth: selected ? 2 : 1,
          borderColor: selected
            ? theme.accent
            : isHighlight
              ? theme.accent
              : theme.border,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.lg,
          gap: theme.spacing.sm,
        }}
      >
        {plan.tag ? (
          <View
            style={{
              position: "absolute",
              top: -10,
              right: 14,
              backgroundColor: isHighlight ? theme.accent : theme.surface2,
              borderColor: isHighlight ? "transparent" : theme.accent,
              borderWidth: isHighlight ? 0 : 1,
              borderRadius: theme.radii.pill,
              paddingHorizontal: 8,
              paddingVertical: 4,
            }}
          >
            <Text
              style={{
                color: isHighlight ? theme.bg : theme.accent,
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
          <View style={{ alignItems: "flex-end" }}>
            <Text
              style={{
                color: selected ? theme.accent : theme.text,
                fontSize: theme.fontSizes.lg,
                fontWeight: theme.fontWeights.bold,
              }}
            >
              {plan.price}
            </Text>
            {plan.perMonth ? (
              <Text
                style={{
                  color: theme.dimmer,
                  fontSize: theme.fontSizes.sm,
                  fontWeight: theme.fontWeights.medium,
                }}
              >
                {plan.perMonth}
              </Text>
            ) : null}
          </View>
        </View>

        <View style={{ gap: 4 }}>
          {plan.bullets.map((b, i) => (
            <View key={i} style={{ flexDirection: "row", gap: 8 }}>
              <Text style={{ color: theme.accent, fontSize: 13 }}>•</Text>
              <Text
                style={{
                  flex: 1,
                  color: theme.dim,
                  fontSize: theme.fontSizes.sm,
                  lineHeight: theme.fontSizes.sm * theme.lineHeights.body,
                }}
              >
                {b}
              </Text>
            </View>
          ))}
        </View>
      </View>
    </Pressable>
  );
}
