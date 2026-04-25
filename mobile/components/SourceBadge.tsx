// Small pill that shows the chat platform (Hinge / Tinder / WhatsApp /
// etc.). Uses a stylized glyph instead of a real logo to avoid trademark
// issues. The `source` field is optional on chats — only renders when
// the backend attaches a guessed platform during screenshot extraction.

import { Text, View } from "react-native";
import { theme } from "../lib/theme";

export type ChatSource =
  | "hinge"
  | "tinder"
  | "bumble"
  | "imessage"
  | "whatsapp"
  | "instagram"
  | "snapchat"
  | "telegram"
  | "discord"
  | "unknown";

const LABELS: Record<ChatSource, string> = {
  hinge: "Hinge",
  tinder: "Tinder",
  bumble: "Bumble",
  imessage: "iMessage",
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  snapchat: "Snapchat",
  telegram: "Telegram",
  discord: "Discord",
  unknown: "Chat",
};

export function SourceBadge({
  source,
  size = "default",
}: {
  source?: ChatSource | string | null;
  size?: "default" | "sm";
}) {
  if (!source || source === "unknown") return null;
  const label = LABELS[source as ChatSource] || source;
  const fs = size === "sm" ? 10 : 11;
  const py = size === "sm" ? 1 : 2;
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: 6,
        paddingVertical: py,
        borderRadius: 6,
        backgroundColor: theme.surface2,
        borderWidth: 1,
        borderColor: theme.border,
      }}
    >
      <Glyph source={source as ChatSource} />
      <Text
        style={{
          color: theme.dim,
          fontSize: fs,
          fontWeight: theme.fontWeights.semibold,
        }}
      >
        {label}
      </Text>
    </View>
  );
}

function Glyph({ source }: { source: ChatSource }) {
  // Plain-shape glyphs rendered with Views — no SVG dep, no trademark risk.
  const c = theme.dim;
  switch (source) {
    case "hinge":
      // Cleanish "H"
      return (
        <View style={{ width: 8, height: 8, flexDirection: "row", gap: 1 }}>
          <View style={{ width: 1.5, height: 8, backgroundColor: c }} />
          <View
            style={{
              flex: 1,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <View
              style={{
                width: "100%",
                height: 1.5,
                backgroundColor: c,
              }}
            />
          </View>
          <View style={{ width: 1.5, height: 8, backgroundColor: c }} />
        </View>
      );
    case "tinder":
    case "bumble":
      // Filled diamond (bumble) or rounded shape (tinder approximation)
      return (
        <View
          style={{
            width: 8,
            height: 8,
            backgroundColor: c,
            borderRadius: source === "tinder" ? 4 : 1,
            transform: source === "bumble" ? [{ rotate: "45deg" }] : [],
          }}
        />
      );
    case "imessage":
    case "whatsapp":
    case "telegram":
    case "discord":
      // Speech bubble — rounded square with corner notch hint
      return (
        <View
          style={{
            width: 8,
            height: 8,
            borderRadius: 2,
            backgroundColor: c,
          }}
        />
      );
    case "instagram":
      // Camera-ish square with center
      return (
        <View
          style={{
            width: 8,
            height: 8,
            borderWidth: 1.5,
            borderColor: c,
            borderRadius: 2,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <View
            style={{
              width: 2.5,
              height: 2.5,
              borderRadius: 1.5,
              backgroundColor: c,
            }}
          />
        </View>
      );
    case "snapchat":
      return (
        <View
          style={{
            width: 8,
            height: 8,
            backgroundColor: c,
            borderRadius: 4,
          }}
        />
      );
    default:
      return (
        <View
          style={{
            width: 6,
            height: 6,
            borderRadius: 3,
            backgroundColor: c,
          }}
        />
      );
  }
}
