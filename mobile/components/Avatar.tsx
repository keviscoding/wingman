// Round avatar with a stylized female silhouette. Used in the chats
// list and chat detail screens. Accepts an optional `uri` for the
// future user-uploaded picture feature; falls back to the silhouette.

import { Image } from "expo-image";
import { View } from "react-native";
import { theme } from "../lib/theme";

type Props = {
  size?: number;
  uri?: string | null;
  // Optional dot overlay (top-right) for "unseen replies" indicator.
  showDot?: boolean;
};

export function Avatar({ size = 44, uri, showDot }: Props) {
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: theme.surface2,
        borderWidth: 1,
        borderColor: theme.border,
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        position: "relative",
      }}
    >
      {uri ? (
        <Image
          source={{ uri }}
          style={{ width: size, height: size }}
          contentFit="cover"
        />
      ) : (
        <Silhouette size={size} />
      )}
      {showDot ? (
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
  // Female-presenting outline rendered as plain Views — no SVG dep,
  // scales cleanly with the parent. Hair is a soft arc over the head.
  const head = size * 0.28;
  const hair = size * 0.42;
  const shoulders = size * 0.74;
  const center = size / 2;
  return (
    <View
      style={{
        width: size,
        height: size,
        backgroundColor: "transparent",
      }}
    >
      {/* Hair ring (soft arc behind the head) */}
      <View
        style={{
          position: "absolute",
          top: size * 0.12,
          left: (size - hair) / 2,
          width: hair,
          height: hair,
          borderRadius: hair / 2,
          backgroundColor: "rgba(102,224,180,0.18)",
        }}
      />
      {/* Head */}
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
      {/* Shoulders / body — bottom rounded rectangle clipped by overflow */}
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
      {/* Subtle hair lock left + right */}
      <View
        style={{
          position: "absolute",
          top: size * 0.16,
          left: center - hair / 2 + 1,
          width: hair * 0.18,
          height: hair * 0.55,
          borderRadius: 999,
          backgroundColor: "rgba(102,224,180,0.18)",
        }}
      />
      <View
        style={{
          position: "absolute",
          top: size * 0.16,
          right: center - hair / 2 + 1,
          width: hair * 0.18,
          height: hair * 0.55,
          borderRadius: 999,
          backgroundColor: "rgba(102,224,180,0.18)",
        }}
      />
    </View>
  );
}
