// Chat list — every screenshot the user uploads becomes a saved chat
// keyed by the contact alias the model extracted. Sorted by recency.
// Tap to open detail / regenerate. Long-press to delete.

import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, ApiError, ChatSummary } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useUnseenChats } from "../lib/genQueue";
import { theme } from "../lib/theme";
import {
  Pressable,
  PrimaryButton,
  TopBar,
  Pill,
} from "../components/ui";
import { Avatar } from "../components/Avatar";

function formatLastActivity(secs: number): string {
  if (!secs) return "";
  const now = Date.now() / 1000;
  const d = now - secs;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  if (d < 86400 * 30) return `${Math.floor(d / 86400)}d ago`;
  return `${Math.floor(d / (86400 * 30))}mo ago`;
}

export default function ChatsScreen() {
  const { token } = useAuth();
  const router = useRouter();
  const unseen = useUnseenChats();
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (silent = false) => {
      if (!token) return;
      if (!silent) setLoading(true);
      setError(null);
      try {
        const r = await api.listChats(token);
        setChats(r.chats || []);
      } catch (e: any) {
        const detail = e instanceof ApiError ? e.detail : e?.message || "error";
        setError(detail);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [token],
  );

  useFocusEffect(
    useCallback(() => {
      load(true);
    }, [load]),
  );

  const onRefresh = () => {
    setRefreshing(true);
    load(true);
  };

  const onDelete = (chat: ChatSummary) => {
    Alert.alert("Delete chat?", `"${chat.contact}" — this can't be undone.`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          if (!token) return;
          try {
            await api.deleteChat(token, chat.id);
            setChats((cs) => cs.filter((c) => c.id !== chat.id));
          } catch (e: any) {
            Alert.alert(
              "Couldn't delete",
              e instanceof ApiError ? e.detail : "Try again.",
            );
          }
        },
      },
    ]);
  };

  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: theme.bg }}>
      <TopBar
        mode="stack"
        title="Your chats"
        onBack={() => router.back()}
        right={
          chats.length > 0 ? (
            <Text
              style={{
                color: theme.dim,
                fontSize: theme.fontSizes.sm,
              }}
            >
              {chats.length}
            </Text>
          ) : null
        }
      />

      {loading && !refreshing ? (
        <View style={{ marginTop: 80, alignItems: "center" }}>
          <ActivityIndicator color={theme.accent} size="large" />
        </View>
      ) : error ? (
        <ErrorBlock message={error} onRetry={() => load()} />
      ) : chats.length === 0 ? (
        <EmptyState onCapture={() => router.replace("/")} />
      ) : (
        <ScrollView
          contentContainerStyle={{ paddingBottom: 32 }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={theme.accent}
            />
          }
        >
          {chats.map((c) => (
            <ChatRow
              key={c.id}
              chat={c}
              hasUnseen={unseen.has(c.id)}
              onOpen={() =>
                router.push({
                  pathname: "/chat/[id]",
                  params: { id: c.id, contact: c.contact },
                })
              }
              onDelete={() => onDelete(c)}
            />
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function ChatRow({
  chat,
  hasUnseen,
  onOpen,
  onDelete,
}: {
  chat: ChatSummary;
  hasUnseen: boolean;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const lastPrefix = chat.last_speaker === "me" ? "You: " : "";
  return (
    <Pressable onPress={onOpen} onLongPress={onDelete}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: theme.spacing.md,
          paddingHorizontal: theme.spacing.lg,
          paddingVertical: theme.spacing.md + 2,
          borderBottomWidth: 1,
          borderBottomColor: theme.border,
        }}
      >
        <Avatar size={44} showDot={hasUnseen} />
        <View style={{ flex: 1, gap: theme.spacing.xs }}>
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              gap: theme.spacing.sm,
            }}
          >
            <Text
              style={{
                color: theme.text,
                fontSize: theme.fontSizes.lg,
                fontWeight: theme.fontWeights.bold,
                flex: 1,
              }}
              numberOfLines={1}
            >
              {chat.contact || "Unknown"}
            </Text>
            {chat.has_replies ? <Pill label="Replies" /> : null}
          </View>
          {chat.last_text ? (
            <Text
              style={{
                color: theme.dim,
                fontSize: 14,
              }}
              numberOfLines={1}
            >
              {lastPrefix}
              {chat.last_text}
            </Text>
          ) : null}
          <Text
            style={{
              color: theme.dimmer,
              fontSize: theme.fontSizes.sm,
            }}
          >
            {chat.msg_count} msg{chat.msg_count === 1 ? "" : "s"} ·{" "}
            {formatLastActivity(chat.last_activity_at)}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}

function EmptyState({ onCapture }: { onCapture: () => void }) {
  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: theme.spacing.xxl,
        gap: theme.spacing.lg,
      }}
    >
      <ChatsIllustration />
      <View style={{ alignItems: "center", gap: theme.spacing.sm, maxWidth: 280 }}>
        <Text
          style={{
            color: theme.text,
            fontSize: theme.fontSizes.xl,
            fontWeight: theme.fontWeights.bold,
            textAlign: "center",
          }}
        >
          No chats yet
        </Text>
        <Text
          style={{
            color: theme.dim,
            fontSize: theme.fontSizes.md,
            lineHeight: theme.fontSizes.md * theme.lineHeights.body,
            textAlign: "center",
          }}
        >
          Capture a chat and Wingman saves your replies here for later.
        </Text>
      </View>
      <View style={{ width: "100%" }}>
        <PrimaryButton label="Capture a chat" onPress={onCapture} />
      </View>
    </View>
  );
}

function ChatsIllustration() {
  return (
    <View
      style={{
        width: 120,
        height: 120,
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
      }}
    >
      {[0, 1, 2].map((i) => (
        <View
          key={i}
          style={{
            width: "100%",
            height: 22,
            borderRadius: 6,
            borderWidth: 1.5,
            borderColor: theme.border,
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: 10,
            gap: 8,
          }}
        >
          <View
            style={{
              width: 10,
              height: 10,
              borderRadius: 5,
              borderWidth: 1.5,
              borderColor: theme.border,
            }}
          />
        </View>
      ))}
    </View>
  );
}

function ErrorBlock({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <View
      style={{
        marginTop: 60,
        alignItems: "center",
        paddingHorizontal: theme.spacing.lg,
        gap: theme.spacing.md,
      }}
    >
      <Text
        style={{
          color: theme.error,
          fontSize: theme.fontSizes.md,
          textAlign: "center",
        }}
      >
        Couldn't load chats: {message}
      </Text>
      <Pressable onPress={onRetry}>
        <Text
          style={{
            color: theme.accent,
            fontWeight: theme.fontWeights.semibold,
            fontSize: theme.fontSizes.md,
          }}
        >
          Retry
        </Text>
      </Pressable>
    </View>
  );
}
