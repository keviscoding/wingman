// Wrapper that gives every tappable element the same press feedback
// (subtle scale + opacity) used across the app — keeps the whole thing
// feeling native without needing to wire it up at every call site.

import { ReactNode } from "react";
import {
  Pressable as RNPressable,
  PressableProps,
  StyleProp,
  ViewStyle,
} from "react-native";
import { theme } from "../../lib/theme";

type Props = Omit<PressableProps, "style" | "children"> & {
  style?: StyleProp<ViewStyle>;
  children: ReactNode;
};

export function Pressable({ style, children, ...rest }: Props) {
  return (
    <RNPressable
      hitSlop={6}
      {...rest}
      style={({ pressed }) => [
        style,
        pressed && {
          opacity: theme.press.opacity,
          transform: [{ scale: theme.press.scale }],
        },
      ]}
    >
      {children}
    </RNPressable>
  );
}
