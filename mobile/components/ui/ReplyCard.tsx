// Reply card — the most-used component. 5 of these stack on the Home and
// Chat detail screens. Tapping copies the reply text and flashes the
// border accent for ~800ms (the only animation in the app).

import * as Clipboard from "expo-clipboard";
import { useEffect, useRef, useState } from "react";
import { Animated, Easing, Text, View } from "react-native";
import { Pressable } from "./Pressable";
import { Angle, theme } from "../../lib/theme";

type Props = {
  angle: Angle;
  text: string;
  why?: string;
  onCopy?: (label: Angle, text: string) => void;
};

export function ReplyCard({ angle, text, why, onCopy }: Props) {
  const [copied, setCopied] = useState(false);
  const flash = useRef(new Animated.Value(0)).current;
  const angleColor = theme.angle[angle];

  useEffect(() => {
    if (!copied) return;
    Animated.sequence([
      Animated.timing(flash, {
        toValue: 1,
        duration: 120,
        easing: Easing.out(Easing.quad),
        useNativeDriver: false,
      }),
      Animated.timing(flash, {
        toValue: 0,
        duration: 800,
        easing: Easing.out(Easing.quad),
        useNativeDriver: false,
      }),
    ]).start();
    const t = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(t);
  }, [copied, flash]);

  const onTap = async () => {
    await Clipboard.setStringAsync(text);
    setCopied(true);
    onCopy?.(angle, text);
  };

  const borderColor = flash.interpolate({
    inputRange: [0, 1],
    outputRange: [theme.border, theme.accent],
  });

  return (
    <Pressable onPress={onTap}>
      <Animated.View
        style={{
          backgroundColor: theme.surface,
          borderRadius: theme.radii.lg,
          borderWidth: 1,
          borderColor,
          padding: theme.spacing.lg,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: theme.spacing.sm,
          }}
        >
          <Text
            style={{
              color: angleColor,
              fontSize: 11,
              fontWeight: theme.fontWeights.bold,
              letterSpacing: theme.tracking.label,
              textTransform: "uppercase",
            }}
          >
            {angle}
          </Text>
          <Text
            style={{
              color: copied ? theme.accent : theme.dimmer,
              fontSize: theme.fontSizes.sm,
              fontWeight: copied
                ? theme.fontWeights.semibold
                : theme.fontWeights.regular,
            }}
          >
            {copied ? "Copied ✓" : "Tap to copy"}
          </Text>
        </View>
        <Text
          style={{
            color: theme.text,
            fontSize: theme.fontSizes.lg,
            lineHeight: theme.fontSizes.lg * theme.lineHeights.reply,
          }}
        >
          {text}
        </Text>
        {why ? (
          <Text
            style={{
              color: theme.dim,
              fontSize: theme.fontSizes.sm,
              fontStyle: "italic",
              marginTop: theme.spacing.xs + 2,
            }}
          >
            {why}
          </Text>
        ) : null}
      </Animated.View>
    </Pressable>
  );
}
