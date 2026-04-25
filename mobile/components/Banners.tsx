// Sticky top banners for transient app states.
// All three follow the same anatomy: thin pill-strip below the top bar,
// colored top border, label + optional action.

import { ActivityIndicator, Text, View } from "react-native";
import { Pressable } from "./ui";
import { theme } from "../lib/theme";

export function NoInternetBanner({ onRetry }: { onRetry?: () => void }) {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: 10,
        backgroundColor: "rgba(255,71,87,0.10)",
        borderTopWidth: 2,
        borderTopColor: theme.error,
        borderBottomWidth: 1,
        borderBottomColor: theme.border,
      }}
    >
      <Text
        style={{
          color: theme.error,
          fontSize: theme.fontSizes.sm,
          fontWeight: theme.fontWeights.semibold,
          flex: 1,
        }}
      >
        No connection — replies need internet
      </Text>
      {onRetry ? (
        <Pressable onPress={onRetry}>
          <Text
            style={{
              color: theme.error,
              fontSize: theme.fontSizes.sm,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            Retry
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function ServerDownBanner({ onRefresh }: { onRefresh?: () => void }) {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: 10,
        backgroundColor: theme.surface2,
        borderBottomWidth: 1,
        borderBottomColor: theme.border,
      }}
    >
      <View
        style={{
          width: 8,
          height: 8,
          borderRadius: 4,
          backgroundColor: theme.error,
        }}
      />
      <Text
        style={{
          color: theme.dim,
          fontSize: theme.fontSizes.sm,
          fontWeight: theme.fontWeights.semibold,
          flex: 1,
        }}
      >
        Wingman is down for maintenance
      </Text>
      {onRefresh ? (
        <Pressable onPress={onRefresh}>
          <Text
            style={{
              color: theme.accent,
              fontSize: theme.fontSizes.sm,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            Refresh
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function TimeoutBanner() {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: 10,
        backgroundColor: "rgba(234,179,8,0.10)",
        borderTopWidth: 2,
        borderTopColor: theme.gold,
        borderBottomWidth: 1,
        borderBottomColor: theme.border,
      }}
    >
      <ActivityIndicator color={theme.gold} size="small" />
      <Text
        style={{
          color: theme.gold,
          fontSize: theme.fontSizes.sm,
          fontWeight: theme.fontWeights.semibold,
          flex: 1,
        }}
      >
        Taking longer than usual…
      </Text>
    </View>
  );
}
