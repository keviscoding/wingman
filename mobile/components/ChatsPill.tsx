// Avatar-stack pill that replaces the plain "Chats" link in the
// home top bar. Three overlapping monogram avatars + label + a small
// accent dot if any chat has unseen replies.

import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import { Pressable } from "./ui";
import { Avatar } from "./Avatar";
import { api, ChatSummary } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useUnseenChats } from "../lib/genQueue";
import { theme } from "../lib/theme";

type Props = {
  onPress: () => void;
};

export function ChatsPill({ onPress }: Props) {
  const { token } = useAuth();
  const unseen = useUnseenChats();
  const [chats, setChats] = useState<ChatSummary[]>([]);

  // Re-pull a tiny preview every time home regains focus. Cheap; the
  // server returns < 1 KB for the full list. Falls back silently on
  // error so a flaky connection doesn't break the home top bar.
  useFocusEffect(
    useCallback(() => {
      if (!token) return;
      let cancelled = false;
      api
        .listChats(token)
        .then((r) => {
          if (!cancelled) setChats(r.chats || []);
        })
        .catch(() => {});
      return () => {
        cancelled = true;
      };
    }, [token]),
  );

  const top3 = chats.slice(0, 3);
  const hasUnseen = unseen.size > 0;

  return (
    <Pressable onPress={onPress}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingLeft: 4,
          paddingRight: 10,
          paddingVertical: 4,
          borderRadius: theme.radii.pill,
          backgroundColor: theme.surface2,
          borderWidth: 1,
          borderColor: theme.border,
          position: "relative",
        }}
      >
        {top3.length > 0 ? (
          <View style={{ flexDirection: "row" }}>
            {top3.map((c, i) => (
              <View
                key={c.id}
                style={{
                  marginLeft: i === 0 ? 0 : -8,
                  borderRadius: 12,
                  borderWidth: 2,
                  borderColor: theme.surface2,
                  zIndex: top3.length - i,
                }}
              >
                <Avatar size={20} name={c.contact} />
              </View>
            ))}
          </View>
        ) : (
          // No chats yet — placeholder dot stack to keep layout steady
          <View
            style={{
              width: 24,
              height: 24,
              borderRadius: 12,
              backgroundColor: theme.surface,
              borderWidth: 1,
              borderColor: theme.border,
            }}
          />
        )}
        <Text
          style={{
            color: theme.text,
            fontSize: 13,
            fontWeight: theme.fontWeights.semibold,
          }}
        >
          Chats
        </Text>
        {hasUnseen ? (
          <View
            style={{
              position: "absolute",
              top: 4,
              right: 6,
              width: 7,
              height: 7,
              borderRadius: 4,
              backgroundColor: theme.accent,
              borderWidth: 2,
              borderColor: theme.surface2,
            }}
          />
        ) : null}
      </View>
    </Pressable>
  );
}
