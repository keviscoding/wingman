// Renders the small quota status pill that lives in the home top bar.
//
// Shape per tier:
//   Free                   → "Free · 22 trial left"        (during lifetime trial)
//   Free (post-trial)      → "Free · 2/5 today"
//   Pro                    → "Pro"                         (no count — feels unconstrained)
//   Pro Max                → "Pro Max"                     (whale tier; even cleaner)
//
// We deliberately don't show running counters on paid tiers — even
// though Pro has a 30/day Pro cap, surfacing the count creates
// quota anxiety that breaks the addictive flow. The cap is just a
// soft guardrail; the upsell signal handles the rest.

import { Text } from "react-native";
import { theme } from "../../lib/theme";

type Me = {
  is_subscribed?: boolean;
  plan?: "free" | "pro" | "pro_max" | string;
  lifetime_used?: number;
  free_lifetime_trial?: number;
  daily_used?: number;
  free_daily_limit?: number;
  paid_daily_limit?: number;
} | null;

export function QuotaBadge({ me }: { me: Me }) {
  if (!me) return null;
  const label = quotaLabel(me);
  const accentColor =
    me.plan === "pro_max"
      ? theme.accent
      : me.plan === "pro"
        ? theme.accent
        : theme.dim;
  return (
    <Text
      style={{
        color: accentColor,
        fontSize: theme.fontSizes.sm,
        fontWeight:
          me.plan === "pro" || me.plan === "pro_max"
            ? theme.fontWeights.bold
            : theme.fontWeights.semibold,
      }}
    >
      {label}
    </Text>
  );
}

function quotaLabel(me: NonNullable<Me>): string {
  if (me.plan === "pro_max" && me.is_subscribed) return "Pro Max";
  if (me.plan === "pro" && me.is_subscribed) return "Pro";
  // Free tier
  const trial = (me.free_lifetime_trial ?? 25) - (me.lifetime_used ?? 0);
  if (trial > 0) return `Free · ${trial} trial left`;
  return `Free · ${me.daily_used ?? 0}/${me.free_daily_limit ?? 5} today`;
}
