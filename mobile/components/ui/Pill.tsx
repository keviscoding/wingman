// Tiny letter-spaced uppercase badge — used for "REPLIES" tags,
// "MOST POPULAR" plan tags, "PRO" badges, etc.

import { Text, View, ViewStyle, StyleProp } from "react-native";
import { theme } from "../../lib/theme";

type Props = {
  label: string;
  variant?: "accent" | "outline" | "muted";
  style?: StyleProp<ViewStyle>;
};

export function Pill({ label, variant = "accent", style }: Props) {
  const styles =
    variant === "accent"
      ? {
          bg: theme.accentDim,
          fg: theme.accent,
          border: undefined,
        }
      : variant === "outline"
        ? {
            bg: theme.surface2,
            fg: theme.accent,
            border: theme.accent,
          }
        : {
            bg: theme.surface2,
            fg: theme.dim,
            border: undefined,
          };

  return (
    <View
      style={[
        {
          backgroundColor: styles.bg,
          borderColor: styles.border,
          borderWidth: styles.border ? 1 : 0,
          borderRadius: theme.radii.pill,
          paddingHorizontal: 8,
          paddingVertical: 3,
          alignSelf: "flex-start",
        },
        style,
      ]}
    >
      <Text
        style={{
          color: styles.fg,
          fontSize: 10,
          fontWeight: theme.fontWeights.bold,
          letterSpacing: theme.tracking.label,
          textTransform: "uppercase",
        }}
      >
        {label}
      </Text>
    </View>
  );
}
