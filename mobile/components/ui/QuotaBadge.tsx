// Renders the "Free · 7 left" / "Pro · 12/200" badge that lives in the
// home top bar.

import { Text } from "react-native";
import { theme } from "../../lib/theme";

type Me = {
  is_subscribed?: boolean;
  lifetime_used?: number;
  free_lifetime_trial?: number;
  daily_used?: number;
  free_daily_limit?: number;
  paid_daily_limit?: number;
} | null;

export function QuotaBadge({ me }: { me: Me }) {
  if (!me) return null;
  const label = quotaLabel(me);
  return (
    <Text
      style={{
        color: theme.dim,
        fontSize: theme.fontSizes.sm,
        fontWeight: theme.fontWeights.semibold,
      }}
    >
      {label}
    </Text>
  );
}

function quotaLabel(me: NonNullable<Me>): string {
  if (me.is_subscribed) return `Pro · ${me.daily_used ?? 0}/${me.paid_daily_limit ?? 200}`;
  const trial = (me.free_lifetime_trial ?? 10) - (me.lifetime_used ?? 0);
  if (trial > 0) return `Free · ${trial} trial left`;
  return `Free · ${me.daily_used ?? 0}/${me.free_daily_limit ?? 3} today`;
}
