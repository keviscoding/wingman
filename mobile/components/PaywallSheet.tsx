// Paywall — modal sheet that slides up from the bottom.
//
// Shown when a generation request returns 402 (free trial / daily cap),
// when a Pro user qualifies for the Pro Max upsell, or when the user
// explicitly taps "Upgrade".
//
// Two product lines, each with weekly + yearly billing:
//   • Pro      — pro_weekly        / pro_yearly
//   • Pro Max  — pro_max_weekly    / pro_max_yearly
//
// Yearly options anchor as the "smart deal." Pro Max weekly is the
// default selected card (highest revenue, most popular per industry).
//
// Purchase flow: when the user taps the CTA, we fetch the matching
// RevenueCat package from the current Offering and trigger the native
// Play purchase sheet. On success the backend webhook updates
// users.plan and we refresh /me so the UI flips to subscribed state.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Animated,
  Dimensions,
  Easing,
  Linking,
  Pressable as RNPressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import type { PurchasesOffering, PurchasesPackage } from "react-native-purchases";
import { Pressable, PrimaryButton, TextLink } from "./ui";
import { theme } from "../lib/theme";
import * as iap from "../lib/iap";
import { useAuth } from "../lib/auth";

export type PlanId =
  | "pro_weekly"
  | "pro_yearly"
  | "pro_max_weekly"
  | "pro_max_yearly";

type Plan = {
  id: PlanId;
  tier: "pro" | "pro_max";
  title: string;
  /** One-line tagline shown under the title (the hero copy). */
  tagline: string;
  /** 1-2 supporting lines under the tagline. Kept short — paywall
   *  cards lose conversion when crammed with bullets. */
  bullets: string[];
  tag?: string;
  highlight?: boolean;
};

// Pricing intentionally NOT in the Plan objects. Apple/Google show
// the localized price in the native purchase sheet, and we want
// flexibility to A/B test prices without redeploying. The card
// communicates VALUE; the store sheet communicates PRICE.

const PLANS: Plan[] = [
  {
    id: "pro_weekly",
    tier: "pro",
    title: "Pro",
    tagline: "Premium AI. For the replies that matter.",
    bullets: [
      "The closer — use it when one reply changes the chat",
      "20 Pro replies/day · billed weekly",
    ],
  },
  {
    id: "pro_yearly",
    tier: "pro",
    title: "Pro · Yearly",
    tagline: "Same Pro. Half the price.",
    bullets: ["Everything in Pro", "Save 50% vs weekly"],
    tag: "SAVE 50%",
  },
  {
    id: "pro_max_weekly",
    tier: "pro_max",
    title: "Pro Max",
    tagline: "For people who text more than they sleep.",
    bullets: [
      "100 Pro replies/day · priority queue · early access",
      "Billed weekly",
    ],
    tag: "MOST POPULAR",
    highlight: true,
  },
  {
    id: "pro_max_yearly",
    tier: "pro_max",
    title: "Pro Max · Yearly",
    tagline: "All Pro Max. Almost half off.",
    bullets: ["Everything in Pro Max", "Save ~45% vs weekly"],
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
  const { refreshMe } = useAuth();
  const defaultPlan: PlanId = upsellMode ? "pro_max_yearly" : "pro_max_weekly";
  const [selected, setSelected] = useState<PlanId>(defaultPlan);
  const [offering, setOffering] = useState<PurchasesOffering | null>(null);
  const [purchasing, setPurchasing] = useState(false);
  const translate = useRef(new Animated.Value(Dimensions.get("window").height)).current;
  const scrim = useRef(new Animated.Value(0)).current;

  // Fetch RevenueCat offerings once when the sheet first becomes
  // visible. We stash the whole Offering and resolve the matching
  // package on subscribe by product identifier (pro_weekly,
  // pro_max_yearly, etc.).
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    iap
      .fetchOfferings()
      .then((o) => {
        if (!cancelled) setOffering(o);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [visible]);

  // Look up the RC package for whatever PlanId is currently selected.
  // We match on the Play product identifier (the Plan.id is the
  // product ID we created in Play Console).
  const selectedPackage = useMemo<PurchasesPackage | null>(() => {
    if (!offering) return null;
    return (
      offering.availablePackages.find(
        (p) => p.product.identifier === selected,
      ) ?? null
    );
  }, [offering, selected]);

  const handleSubscribe = async () => {
    if (purchasing) return;
    if (!selectedPackage) {
      Alert.alert(
        "Subscription unavailable",
        "Couldn't load subscription options. Check your connection and try again, or restart the app.",
      );
      return;
    }
    setPurchasing(true);
    const outcome = await iap.purchasePackage(selectedPackage);
    setPurchasing(false);
    if (outcome.ok) {
      // Refresh /me so the UI flips to the new plan immediately.
      // Server-side, RC's webhook has already (or is about to) set
      // users.plan = 'pro' | 'pro_max'.
      try {
        await refreshMe();
      } catch {
        // Non-fatal — even if /me refresh fails, the next call will
        // pick up the new plan.
      }
      onSubscribe?.(selected);
      onDismiss();
    } else if ("cancelled" in outcome && outcome.cancelled) {
      // User backed out of the Play sheet. Stay on the paywall, no toast.
      return;
    } else {
      Alert.alert(
        "Purchase failed",
        outcome.error || "Something went wrong. No charges were made.",
      );
    }
  };

  const handleRestore = async () => {
    const info = await iap.restorePurchases();
    if (info && Object.keys(info.entitlements.active).length > 0) {
      try {
        await refreshMe();
      } catch {
        /* ignore */
      }
      Alert.alert("Restored", "Your subscription has been restored.");
      onDismiss();
    } else {
      Alert.alert("Nothing to restore", "No active subscription found for this account.");
    }
  };

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
            label={purchasing ? "Processing…" : cta}
            onPress={handleSubscribe}
            disabled={purchasing || !selectedPackage}
          />

          <View
            style={{
              flexDirection: "row",
              justifyContent: "center",
              gap: theme.spacing.lg,
            }}
          >
            <TextLink label="Restore" onPress={handleRestore} size={theme.fontSizes.sm} />
            <TextLink
              label="Privacy"
              onPress={() =>
                Linking.openURL("https://cliprr.io/muzo/privacy.html")
              }
              size={theme.fontSizes.sm}
            />
            <TextLink
              label="Terms"
              onPress={() =>
                Linking.openURL("https://cliprr.io/muzo/terms.html")
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
            fontSize: theme.fontSizes.md,
            fontWeight: theme.fontWeights.semibold,
            lineHeight: theme.fontSizes.md * theme.lineHeights.body,
          }}
        >
          {plan.tagline}
        </Text>

        <View style={{ gap: 4, marginTop: 2 }}>
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
