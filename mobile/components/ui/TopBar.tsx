// Standard top bar used on every primary screen.
// Two layout modes:
//   1. Wordmark on the left + right-side meta (Home screen)
//   2. Back link on the left + centered title (chats list, chat detail, settings)

import { ReactNode } from "react";
import { Text, View } from "react-native";
import { Pressable } from "./Pressable";
import { theme } from "../../lib/theme";

type Props =
  | {
      // Home-style: wordmark on the left
      mode?: "home";
      right?: ReactNode;
    }
  | {
      // Stack-style: back link + title
      mode: "stack";
      title: string;
      onBack?: () => void;
      right?: ReactNode;
    };

export function TopBar(props: Props) {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        height: theme.layout.topBarH,
        paddingHorizontal: theme.spacing.lg,
        borderBottomWidth: 1,
        borderBottomColor: theme.border,
      }}
    >
      {props.mode === "stack" ? (
        <>
          <Pressable onPress={props.onBack}>
            <Text
              style={{
                color: theme.accent,
                fontSize: theme.fontSizes.md,
                fontWeight: theme.fontWeights.semibold,
              }}
            >
              ← Back
            </Text>
          </Pressable>
          <Text
            style={{
              color: theme.text,
              fontSize: theme.fontSizes.lg,
              fontWeight: theme.fontWeights.bold,
              marginLeft: theme.spacing.lg,
              flex: 1,
            }}
            numberOfLines={1}
          >
            {props.title}
          </Text>
          {props.right ? (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
              {props.right}
            </View>
          ) : null}
        </>
      ) : (
        <>
          <Text
            style={{
              color: theme.text,
              fontSize: theme.fontSizes.lg,
              fontWeight: theme.fontWeights.bold,
              letterSpacing: theme.tracking.display,
            }}
          >
            Muzo
          </Text>
          <View style={{ flex: 1 }} />
          {props.right ? (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 14,
              }}
            >
              {props.right}
            </View>
          ) : null}
        </>
      )}
    </View>
  );
}
