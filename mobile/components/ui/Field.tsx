// Input field with mockup-style focus ring (mint accent + soft glow).

import { useState } from "react";
import { TextInput, TextInputProps, View } from "react-native";
import { theme } from "../../lib/theme";

type Props = TextInputProps & {
  fullWidth?: boolean;
};

export function Field({ style, fullWidth = true, ...rest }: Props) {
  const [focused, setFocused] = useState(false);

  return (
    <View
      style={{
        // Soft glow ring when focused (faked via outer wrap, since RN
        // doesn't support box-shadow on iOS pre-Reanimated)
        borderRadius: theme.radii.md + 2,
        padding: focused ? 2 : 0,
        backgroundColor: focused ? theme.accentDim : "transparent",
        width: fullWidth ? "100%" : undefined,
      }}
    >
      <TextInput
        placeholderTextColor={theme.dimmer}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        {...rest}
        style={[
          {
            backgroundColor: theme.surface,
            borderRadius: theme.radii.md,
            borderWidth: 1,
            borderColor: focused ? theme.accent : theme.border,
            paddingHorizontal: theme.spacing.lg,
            paddingVertical: 14,
            color: theme.text,
            fontSize: theme.fontSizes.md,
          },
          style,
        ]}
      />
    </View>
  );
}
