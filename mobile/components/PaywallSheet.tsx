// Paywall — modal sheet that slides up from the bottom.
//
// UX shape (as of v0.2):
//   • Header copy + close
//   • Tier toggle:  [ Pro ] [ Pro Max ]   ← Pro Max default (highest LTV)
//   • Bullet list for the selected tier
//   • Billing toggle: [ Weekly ] [ Yearly ]   ← Yearly default (anchors value)
//   • One focused price card (price + savings tag)
//   • Subscribe CTA — shows "Subscribe — $89.99/yr" when offering loaded
//   • Restore · Privacy · Terms
//
// Why this shape:
//   - 4 flat cards confuse users; segmenting the choice into two
//     binary decisions (tier, then period) reduces cognitive load
//     and lifts conversion.
//   - Pro Max + Yearly is the highest-revenue combo, so it's the
//     default selection.
//   - When RC's offering is null (sideloaded build, Play Billing not
//     wired up, or sync delay), we surface a real error instead of
//     a silently-disabled button.

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

type Tier = "pro" | "pro_max";
type Period = "weekly" | "yearly";

function planIdFor(tier: Tier, period: Period): PlanId {
  if (tier === "pro_max") return period === "yearly" ? "pro_max_yearly" : "pro_max_weekly";
  return period === "yearly" ? "pro_yearly" : "pro_weekly";
}

const TIER_COPY: Record<Tier, { title: string; tagline: string; bullets: string[] }> = {
  pro: {
    title: "Pro",
    tagline: "Premium AI for the replies that matter.",
    bullets: [
      "20 Pro replies/day · the closer when one reply changes the chat",
      "Unlimited Quick replies",
      "Save chats, lock context, copy in one tap",
    ],
  },
  pro_max: {
    title: "Pro Max",
    tagline: "For people who text more than they sleep.",
    bullets: [
      "100 Pro replies/day · 5× the volume",
      "Priority queue · your replies skip the line",
      "Early access to new features and models",
    ],
  },
};

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
  cta,
  upsellMode = false,
}: Props) {
  const { refreshMe } = useAuth();
  const [tier, setTier] = useState<Tier>("pro_max");
  const [period, setPeriod] = useState<Period>("yearly");
  const [offering, setOffering] = useState<PurchasesOffering | null>(null);
  const [offeringError, setOfferingError] = useState<string | null>(null);
  const [loadingOfferings, setLoadingOfferings] = useState(false);
  const [purchasing, setPurchasing] = useState(false);
  const translate = useRef(new Animated.Value(Dimensions.get("window").height)).current;
  const scrim = useRef(new Animated.Value(0)).current;

  const selectedPlanId = planIdFor(tier, period);

  // Helper to (re)fetch the RC offering. Surfaces a structured error
  // string so the UI can tell the user *why* prices aren't showing.
  const loadOfferings = useMemo(
    () => async () => {
      setLoadingOfferings(true);
      setOfferingError(null);
      try {
        const o = await iap.fetchOfferings();
        if (!o) {
          setOffering(null);
          setOfferingError(
            "Couldn't load store prices. Make sure you installed Muzo from the Play Store internal testing link and that you're added as a license tester.",
          );
        } else if (!o.availablePackages || o.availablePackages.length === 0) {
          setOffering(null);
          setOfferingError(
            "No subscription plans configured. Try restarting the app — if this persists, contact support.",
          );
        } else {
          setOffering(o);
        }
      } catch (e: any) {
        setOffering(null);
        setOfferingError(e?.message || "Couldn't reach the store.");
      } finally {
        setLoadingOfferings(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    void (async () => {
      if (!cancelled) await loadOfferings();
    })();
    return () => {
      cancelled = true;
    };
  }, [visible, loadOfferings]);

  // Reset to defaults whenever the sheet opens. Pro Max + Yearly is
  // the default — except in upsellMode (Pro→Pro Max) where the user
  // is already Pro, so we land on Pro Max + Yearly too.
  useEffect(() => {
    if (visible) {
      setTier("pro_max");
      setPeriod("yearly");
    }
  }, [visible, upsellMode]);

  // Resolve the RC package for a given PlanId. We match through
  // multiple strategies because RC + Play Billing v5+ can surface
  // package/product identifiers in several formats:
  //   - offering.weekly / offering.annual (predefined $rc_* slots)
  //   - pkg.identifier === "pro_max_weekly" (Custom packages we
  //     created in RC dashboard)
  //   - pkg.product.identifier matches our PlanId
  //   - pkg.product.identifier starts with our PlanId (Play subs
  //     can return "pro_weekly:weekly" — productId:basePlanId)
  // Order matters — predefined slots first since they're the most
  // canonical mapping.
  //
  // Declared up here BEFORE the consumers (debugSummary,
  // noMatchingPackages) because useMemo factories run synchronously
  // during render — out-of-order declaration trips a TDZ
  // ReferenceError that crashes the whole component.
  const findPackage = useMemo(
    () => (planId: PlanId): PurchasesPackage | null => {
      if (!offering) return null;
      const all = offering.availablePackages || [];
      // Predefined slot accessors for $rc_weekly / $rc_annual
      if (planId === "pro_weekly" && offering.weekly) return offering.weekly;
      if (planId === "pro_yearly" && offering.annual) return offering.annual;
      // Custom packages in RC: identifier matches PlanId directly
      const byPkgId = all.find((p) => p.identifier === planId);
      if (byPkgId) return byPkgId;
      // Custom packages with `_annual` slug instead of `_yearly`
      if (planId === "pro_max_yearly") {
        const byAnnual = all.find((p) => p.identifier === "pro_max_annual");
        if (byAnnual) return byAnnual;
      }
      // Match on product identifier (exact)
      const byProduct = all.find((p) => p.product.identifier === planId);
      if (byProduct) return byProduct;
      // Match on product identifier with base plan suffix
      // (e.g. "pro_weekly:weekly")
      const byProductPrefix = all.find((p) =>
        p.product.identifier.startsWith(`${planId}:`),
      );
      if (byProductPrefix) return byProductPrefix;
      return null;
    },
    [offering],
  );

  // Build a human-readable summary of what RC returned so the user
  // (or us, debugging on a real device) can see exactly which packages
  // are available — useful when nothing renders prices but the
  // offering loaded.
  const debugSummary = useMemo(() => {
    if (!offering) return null;
    const lines: string[] = [];
    lines.push(`offering=${offering.identifier}`);
    lines.push(`pkgs=${offering.availablePackages.length}`);
    for (const p of offering.availablePackages) {
      lines.push(
        `· ${p.identifier} → ${p.product.identifier} (${p.product.priceString || "no price"})`,
      );
    }
    return lines.join("\n");
  }, [offering]);

  // Detect the trickier failure mode: offering loaded with packages
  // but none match any of our 4 PlanIds. This usually means the RC
  // dashboard package identifiers / linked products don't match what
  // we expect. Surface debug info so we can fix the dashboard
  // without redeploying.
  const noMatchingPackages = useMemo(() => {
    if (!offering) return false;
    const ids: PlanId[] = [
      "pro_weekly",
      "pro_yearly",
      "pro_max_weekly",
      "pro_max_yearly",
    ];
    return !ids.some((id) => findPackage(id) !== null);
  }, [offering, findPackage]);

  const selectedPackage = useMemo<PurchasesPackage | null>(
    () => findPackage(selectedPlanId),
    [findPackage, selectedPlanId],
  );

  // Look up both billing periods for the active tier so we can show
  // savings. weeklyPkg.price * 52 vs yearlyPkg.price gives the % off.
  const weeklyPkg = useMemo(
    () => findPackage(planIdFor(tier, "weekly")),
    [findPackage, tier],
  );
  const yearlyPkg = useMemo(
    () => findPackage(planIdFor(tier, "yearly")),
    [findPackage, tier],
  );

  // Compute savings for the yearly card based on weekly price * 52.
  const yearlySavingsPct = useMemo(() => {
    const weekly = weeklyPkg?.product.price;
    const yearly = yearlyPkg?.product.price;
    if (!weekly || !yearly) return null;
    const equivAnnual = weekly * 52;
    if (equivAnnual <= 0) return null;
    const pct = Math.round(((equivAnnual - yearly) / equivAnnual) * 100);
    return pct > 0 ? pct : null;
  }, [weeklyPkg, yearlyPkg]);

  const handleSubscribe = async () => {
    if (purchasing) return;
    if (!selectedPackage) {
      Alert.alert(
        "Subscriptions unavailable",
        offeringError ||
          "Couldn't load subscription options. Check your connection and try again, or restart the app.",
      );
      return;
    }
    setPurchasing(true);
    const outcome = await iap.purchasePackage(selectedPackage);
    setPurchasing(false);
    if (outcome.ok) {
      try {
        await refreshMe();
      } catch {
        /* non-fatal */
      }
      onSubscribe?.(selectedPlanId);
      onDismiss();
    } else if ("cancelled" in outcome && outcome.cancelled) {
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
      : "Pro and Pro Max unlock the high-quality AI mode and unlimited Quick replies.");

  const tierCopy = TIER_COPY[tier];
  const ctaPriceSuffix = selectedPackage?.product.priceString
    ? ` — ${selectedPackage.product.priceString}${period === "yearly" ? "/yr" : "/wk"}`
    : "";
  const ctaLabel = purchasing
    ? "Processing…"
    : (cta ?? "Subscribe") + ctaPriceSuffix;

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
        <View style={{ alignItems: "center", paddingTop: 8, paddingBottom: 4 }}>
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
          {/* Header */}
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

          {/* Tier toggle */}
          <SegmentedToggle
            value={tier}
            onChange={setTier}
            options={[
              { value: "pro", label: "Pro" },
              { value: "pro_max", label: "Pro Max", badge: "POPULAR" },
            ]}
          />

          {/* Bullets for the selected tier */}
          <View style={{ gap: 8 }}>
            <Text
              style={{
                color: theme.text,
                fontSize: theme.fontSizes.lg,
                fontWeight: theme.fontWeights.bold,
              }}
            >
              {tierCopy.title}
            </Text>
            <Text
              style={{
                color: theme.dim,
                fontSize: theme.fontSizes.md,
                lineHeight: theme.fontSizes.md * theme.lineHeights.body,
              }}
            >
              {tierCopy.tagline}
            </Text>
            <View style={{ gap: 6, marginTop: 6 }}>
              {tierCopy.bullets.map((b, i) => (
                <View key={i} style={{ flexDirection: "row", gap: 8 }}>
                  <Text style={{ color: theme.accent, fontSize: 14 }}>✓</Text>
                  <Text
                    style={{
                      flex: 1,
                      color: theme.text,
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

          {/* Billing period — two side-by-side cards */}
          <View style={{ gap: 8 }}>
            <Text
              style={{
                color: theme.dim,
                fontSize: 11,
                fontWeight: theme.fontWeights.bold,
                letterSpacing: theme.tracking.label,
                textTransform: "uppercase",
              }}
            >
              Choose your billing
            </Text>
            <View style={{ flexDirection: "row", gap: 10 }}>
              <PeriodCard
                label="Weekly"
                priceString={weeklyPkg?.product.priceString}
                periodSuffix="/wk"
                selected={period === "weekly"}
                onSelect={() => setPeriod("weekly")}
              />
              <PeriodCard
                label="Yearly"
                priceString={yearlyPkg?.product.priceString}
                periodSuffix="/yr"
                selected={period === "yearly"}
                onSelect={() => setPeriod("yearly")}
                tag={yearlySavingsPct ? `SAVE ${yearlySavingsPct}%` : "BEST VALUE"}
              />
            </View>
          </View>

          {/* Diagnostic banner — shown when:
              1. RC didn't return an offering at all, OR
              2. RC returned an offering but our PlanIds don't match
                 any package's identifier/product (dashboard config bug). */}
          {(offeringError && !offering) || noMatchingPackages ? (
            <View
              style={{
                backgroundColor: theme.surface,
                borderColor: theme.gold,
                borderWidth: 1,
                borderRadius: theme.radii.md,
                padding: theme.spacing.md,
                gap: 6,
              }}
            >
              <Text
                style={{
                  color: theme.text,
                  fontSize: theme.fontSizes.sm,
                  fontWeight: theme.fontWeights.semibold,
                }}
              >
                Can't load prices yet
              </Text>
              <Text
                style={{
                  color: theme.dim,
                  fontSize: theme.fontSizes.sm,
                  lineHeight: theme.fontSizes.sm * theme.lineHeights.body,
                }}
              >
                {offeringError ??
                  "Subscription plans loaded but none match the expected products. The RevenueCat dashboard needs a config fix — see details below."}
              </Text>
              {debugSummary ? (
                <Text
                  selectable
                  style={{
                    color: theme.dim,
                    fontSize: 11,
                    fontFamily: "Courier",
                    lineHeight: 16,
                    marginTop: 4,
                  }}
                >
                  {debugSummary}
                </Text>
              ) : null}
              <Pressable onPress={loadOfferings}>
                <Text
                  style={{
                    color: theme.accent,
                    fontSize: theme.fontSizes.sm,
                    fontWeight: theme.fontWeights.semibold,
                    marginTop: 4,
                  }}
                >
                  {loadingOfferings ? "Retrying…" : "Tap to retry"}
                </Text>
              </Pressable>
            </View>
          ) : null}

          <Text
            style={{
              color: theme.dimmer,
              fontSize: 12,
              textAlign: "center",
              lineHeight: 18,
            }}
          >
            Cancel anytime in your store · auto-renews
          </Text>

          <PrimaryButton
            label={ctaLabel}
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

function SegmentedToggle<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (next: T) => void;
  options: { value: T; label: string; badge?: string }[];
}) {
  return (
    <View
      style={{
        flexDirection: "row",
        backgroundColor: theme.surface,
        borderColor: theme.border,
        borderWidth: 1,
        borderRadius: theme.radii.pill,
        padding: 4,
      }}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <Pressable
            key={o.value}
            onPress={() => onChange(o.value)}
            style={{ flex: 1 }}
          >
            <View
              style={{
                paddingVertical: 10,
                paddingHorizontal: 12,
                borderRadius: theme.radii.pill,
                backgroundColor: active ? theme.accent : "transparent",
                alignItems: "center",
                flexDirection: "row",
                justifyContent: "center",
                gap: 6,
              }}
            >
              <Text
                style={{
                  color: active ? theme.bg : theme.text,
                  fontSize: theme.fontSizes.md,
                  fontWeight: theme.fontWeights.bold,
                }}
              >
                {o.label}
              </Text>
              {o.badge ? (
                <View
                  style={{
                    backgroundColor: active ? theme.bg : theme.accent,
                    borderRadius: theme.radii.pill,
                    paddingHorizontal: 6,
                    paddingVertical: 2,
                  }}
                >
                  <Text
                    style={{
                      color: active ? theme.accent : theme.bg,
                      fontSize: 9,
                      fontWeight: theme.fontWeights.bold,
                      letterSpacing: theme.tracking.label,
                    }}
                  >
                    {o.badge}
                  </Text>
                </View>
              ) : null}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

function PeriodCard({
  label,
  priceString,
  periodSuffix,
  selected,
  onSelect,
  tag,
}: {
  label: string;
  priceString?: string;
  periodSuffix: string;
  selected: boolean;
  onSelect: () => void;
  tag?: string;
}) {
  return (
    <Pressable onPress={onSelect} style={{ flex: 1 }}>
      <View
        style={{
          position: "relative",
          backgroundColor: selected ? theme.accentDim : theme.surface,
          borderColor: selected ? theme.accent : theme.border,
          borderWidth: selected ? 2 : 1,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.md,
          gap: 4,
        }}
      >
        {tag ? (
          <View
            style={{
              position: "absolute",
              top: -10,
              right: 10,
              backgroundColor: selected ? theme.accent : theme.surface2,
              borderColor: selected ? "transparent" : theme.accent,
              borderWidth: selected ? 0 : 1,
              borderRadius: theme.radii.pill,
              paddingHorizontal: 8,
              paddingVertical: 4,
            }}
          >
            <Text
              style={{
                color: selected ? theme.bg : theme.accent,
                fontSize: 9,
                fontWeight: theme.fontWeights.bold,
                letterSpacing: theme.tracking.label,
              }}
            >
              {tag}
            </Text>
          </View>
        ) : null}
        <Text
          style={{
            color: theme.dim,
            fontSize: 11,
            fontWeight: theme.fontWeights.bold,
            letterSpacing: theme.tracking.label,
            textTransform: "uppercase",
          }}
        >
          {label}
        </Text>
        <Text
          style={{
            color: selected ? theme.accent : theme.text,
            fontSize: theme.fontSizes.lg,
            fontWeight: theme.fontWeights.bold,
          }}
        >
          {priceString ?? "—"}
          <Text
            style={{
              color: theme.dim,
              fontSize: theme.fontSizes.sm,
              fontWeight: theme.fontWeights.medium,
            }}
          >
            {priceString ? periodSuffix : ""}
          </Text>
        </Text>
      </View>
    </Pressable>
  );
}
