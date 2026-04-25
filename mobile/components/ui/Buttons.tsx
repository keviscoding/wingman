// PrimaryButton / SecondaryButton / TextLink — single source of truth.
// Match the mockups' shape, spacing, weight, and press feedback.

import { ReactNode } from "react";
import { ActivityIndicator, Text, View, ViewStyle, StyleProp } from "react-native";
import { Pressable } from "./Pressable";
import { theme } from "../../lib/theme";

type ButtonProps = {
  label?: string;
  onPress?: () => void;
  disabled?: boolean;
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
  children?: ReactNode; // optional override (e.g. icon + text)
};

export function PrimaryButton({
  label,
  onPress,
  disabled,
  loading,
  style,
  children,
}: ButtonProps) {
  return (
    <Pressable
      onPress={disabled || loading ? undefined : onPress}
      style={[
        {
          backgroundColor: theme.accent,
          borderRadius: theme.radii.lg,
          paddingVertical: 14,
          paddingHorizontal: theme.spacing.lg,
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "row",
          minHeight: 48,
          opacity: disabled ? 0.4 : 1,
        },
        style,
      ]}
    >
      {loading ? (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: theme.spacing.sm,
          }}
        >
          <ActivityIndicator color={theme.bg} size="small" />
          <Text
            style={{
              color: theme.bg,
              fontSize: theme.fontSizes.md,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            {label || "Loading…"}
          </Text>
        </View>
      ) : children ? (
        children
      ) : (
        <Text
          style={{
            color: theme.bg,
            fontSize: theme.fontSizes.md,
            fontWeight: theme.fontWeights.bold,
            letterSpacing: 0.1,
          }}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

export function SecondaryButton({ label, onPress, disabled, style }: ButtonProps) {
  return (
    <Pressable
      onPress={disabled ? undefined : onPress}
      style={[
        {
          backgroundColor: "transparent",
          borderRadius: theme.radii.lg,
          borderWidth: 1,
          borderColor: theme.accent,
          paddingVertical: 14,
          paddingHorizontal: theme.spacing.lg,
          alignItems: "center",
          justifyContent: "center",
          minHeight: 48,
          opacity: disabled ? 0.4 : 1,
        },
        style,
      ]}
    >
      <Text
        style={{
          color: theme.accent,
          fontSize: theme.fontSizes.md,
          fontWeight: theme.fontWeights.bold,
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

type TextLinkProps = {
  label: string;
  onPress?: () => void;
  color?: string;
  size?: number;
};

export function TextLink({ label, onPress, color, size }: TextLinkProps) {
  return (
    <Pressable onPress={onPress}>
      <Text
        style={{
          color: color || theme.dim,
          fontSize: size || theme.fontSizes.md,
          fontWeight: theme.fontWeights.semibold,
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}
