// Round avatar.
//
// Three rendering modes (in priority order):
//   1. uri          → user-uploaded photo
//   2. name + tint  → mint-themed monogram with deterministic per-name color
//   3. silhouette   → final fallback when no name available
//
// Optional decorations:
//   - showDot       → small accent dot top-right ("unread / fresh replies")
//   - readyRing     → mint outline ring around the whole avatar
//                     (used when this contact has cached replies waiting)
//   - unreadCount   → numeric badge top-right ("3" style)

import { Image } from "expo-image";
import { Text, View } from "react-native";
import { initials, nameTint } from "../lib/chatTint";
import { theme } from "../lib/theme";

type Props = {
  size?: number;
  uri?: string | null;
  name?: string | null;
  showDot?: boolean;
  readyRing?: boolean;
  unreadCount?: number;
};

export function Avatar({
  size = 44,
  uri,
  name,
  showDot,
  readyRing,
  unreadCount,
}: Props) {
  const hasName = !!name && name.trim().length > 0;
  const tint = hasName ? nameTint(name as string) : null;
  const initialsText = hasName ? initials(name as string) : "";

  return (
    <View
      style={{
        width: size,
        height: size,
        position: "relative",
      }}
    >
      {/* Replies-ready ring sits OUTSIDE the avatar to avoid clipping */}
      {readyRing ? (
        <View
          style={{
            position: "absolute",
            top: -3,
            left: -3,
            right: -3,
            bottom: -3,
            borderRadius: (size + 6) / 2,
            borderWidth: 1.5,
            borderColor: theme.accent,
            opacity: 0.55,
          }}
        />
      ) : null}

      <View
        style={{
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: tint ? tint.bg : theme.surface2,
          borderWidth: 1,
          borderColor: theme.border,
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        {uri ? (
          <Image
            source={{ uri }}
            style={{ width: size, height: size }}
            contentFit="cover"
          />
        ) : initialsText ? (
          <Text
            style={{
              color: tint ? tint.fg : theme.text,
              fontSize: size < 32 ? 11 : 16,
              fontWeight: theme.fontWeights.bold,
              letterSpacing: -0.2,
            }}
          >
            {initialsText}
          </Text>
        ) : (
          <Silhouette size={size} />
        )}
      </View>

      {/* Numeric unread badge — overrides plain dot */}
      {unreadCount && unreadCount > 0 ? (
        <View
          style={{
            position: "absolute",
            top: -2,
            right: -2,
            minWidth: 18,
            height: 18,
            paddingHorizontal: 5,
            borderRadius: 9,
            backgroundColor: theme.accent,
            alignItems: "center",
            justifyContent: "center",
            borderWidth: 2,
            borderColor: theme.bg,
          }}
        >
          <Text
            style={{
              color: theme.bg,
              fontSize: 11,
              fontWeight: theme.fontWeights.bold,
              lineHeight: 12,
            }}
          >
            {unreadCount}
          </Text>
        </View>
      ) : showDot ? (
        <View
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            width: 12,
            height: 12,
            borderRadius: 6,
            backgroundColor: theme.accent,
            borderWidth: 2,
            borderColor: theme.bg,
          }}
        />
      ) : null}
    </View>
  );
}

function Silhouette({ size }: { size: number }) {
  // Light fallback for when neither uri nor name is available.
  // Same shape as before — kept understated.
  const head = size * 0.28;
  const shoulders = size * 0.74;
  return (
    <View style={{ width: size, height: size }}>
      <View
        style={{
          position: "absolute",
          top: size * 0.18,
          left: (size - head) / 2,
          width: head,
          height: head,
          borderRadius: head / 2,
          backgroundColor: theme.dim,
        }}
      />
      <View
        style={{
          position: "absolute",
          left: (size - shoulders) / 2,
          top: size * 0.55,
          width: shoulders,
          height: shoulders,
          borderRadius: shoulders / 2,
          backgroundColor: theme.dim,
        }}
      />
    </View>
  );
}
