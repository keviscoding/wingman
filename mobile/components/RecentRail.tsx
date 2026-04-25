// Horizontal scrolling rail of recent chats — sits on the home screen
// just under the top bar in idle states (Permission, Ready, Error).
// Hidden during Generating so attention stays on the spinner.
//
// Each card: monogram + when, name + 2-line preview, replies-ready
// ring, optional unread badge.

import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { Pressable } from "./ui";
import { Avatar } from "./Avatar";
import { api, ChatSummary } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useUnseenChats } from "../lib/genQueue";
import { theme } from "../lib/theme";

type Props = {
  onSeeAll: () => void;
  onOpenChat: (chat: ChatSummary) => void;
};

const TODAY_S = 24 * 3600;

function shortAge(secs: number): string {
  if (!secs) return "";
  const now = Date.now() / 1000;
  const d = now - secs;
  if (d < 60) return "now";
  if (d < 3600) return `${Math.floor(d / 60)}m`;
  if (d < TODAY_S) return `${Math.floor(d / 3600)}h`;
  if (d < TODAY_S * 7) return `${Math.floor(d / TODAY_S)}d`;
  return `${Math.floor(d / (TODAY_S * 7))}w`;
}

export function RecentRail({ onSeeAll, onOpenChat }: Props) {
  const { token } = useAuth();
  const unseen = useUnseenChats();
  const [chats, setChats] = useState<ChatSummary[]>([]);

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

  if (chats.length === 0) return null;

  const top = chats.slice(0, 8);

  return (
    <View style={{ paddingTop: 14, paddingBottom: 6 }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "baseline",
          justifyContent: "space-between",
          paddingHorizontal: 20,
          paddingBottom: 10,
        }}
      >
        <Text
          style={{
            fontSize: 11,
            fontWeight: theme.fontWeights.bold,
            letterSpacing: theme.tracking.label,
            color: theme.dim,
            textTransform: "uppercase",
          }}
        >
          Recent chats
        </Text>
        <Pressable onPress={onSeeAll}>
          <Text
            style={{
              color: theme.accent,
              fontSize: 12,
              fontWeight: theme.fontWeights.semibold,
            }}
          >
            See all →
          </Text>
        </Pressable>
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: 16, gap: 10 }}
      >
        {top.map((c) => (
          <RecentCard
            key={c.id}
            chat={c}
            hasUnseen={unseen.has(c.id)}
            onPress={() => onOpenChat(c)}
          />
        ))}
        {/* "View all" hollow card */}
        <Pressable onPress={onSeeAll}>
          <View
            style={{
              width: 92,
              height: 116,
              borderRadius: 14,
              borderWidth: 1.5,
              borderColor: theme.border,
              borderStyle: "dashed",
              alignItems: "center",
              justifyContent: "center",
              padding: 8,
            }}
          >
            <Text
              style={{
                color: theme.dim,
                fontSize: 12,
                fontWeight: theme.fontWeights.semibold,
                textAlign: "center",
                lineHeight: 16,
              }}
            >
              View all{"\n"}chats
            </Text>
          </View>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function RecentCard({
  chat,
  hasUnseen,
  onPress,
}: {
  chat: ChatSummary;
  hasUnseen: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable onPress={onPress}>
      <View
        style={{
          width: 124,
          height: 116,
          borderRadius: 14,
          padding: 12,
          backgroundColor: theme.surface,
          borderWidth: 1,
          borderColor: theme.border,
          gap: 8,
          position: "relative",
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Avatar size={28} name={chat.contact} readyRing={chat.has_replies} />
          <Text
            style={{
              color: theme.dimmer,
              fontSize: 11,
              fontWeight: theme.fontWeights.medium,
            }}
          >
            {shortAge(chat.last_activity_at)}
          </Text>
        </View>
        <View style={{ gap: 2 }}>
          <Text
            style={{
              fontSize: 13,
              fontWeight: theme.fontWeights.bold,
              color: theme.text,
            }}
            numberOfLines={1}
          >
            {chat.contact}
          </Text>
          <Text
            style={{
              fontSize: 12,
              color: theme.dim,
              lineHeight: 16,
            }}
            numberOfLines={2}
          >
            {chat.last_text || "—"}
          </Text>
        </View>
        {hasUnseen ? (
          <View
            style={{
              position: "absolute",
              top: 8,
              right: 8,
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: theme.accent,
            }}
          />
        ) : null}
      </View>
    </Pressable>
  );
}
