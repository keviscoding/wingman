// Chat list — every screenshot a user uploads becomes a saved chat
// keyed by the contact alias the model extracted.
//
// New layout (matches WINGMAN UI / wingman CHATS LOOK UPDATE):
//   - Top bar with total-unread pill + count
//   - Search input under the top bar
//   - Bucketed sections: Today / Earlier this week / Older
//   - Each row: tinted-monogram avatar (replies-ready ring + unread
//     badge), name + source pill, "You: ..." preview, msgs count +
//     last-copied angle indicator

import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, ApiError, ChatSummary } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useUnseenChats } from "../lib/genQueue";
import { theme, Angle } from "../lib/theme";
import { Pressable, PrimaryButton, TopBar } from "../components/ui";
import { Avatar } from "../components/Avatar";
import { SourceBadge } from "../components/SourceBadge";

const TODAY_S = 24 * 3600;
const WEEK_S = 7 * 24 * 3600;

function formatLastActivity(secs: number): string {
  if (!secs) return "";
  const now = Date.now() / 1000;
  const d = now - secs;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < TODAY_S) return `${Math.floor(d / 3600)}h ago`;
  if (d < WEEK_S) return `${Math.floor(d / TODAY_S)}d ago`;
  if (d < WEEK_S * 4) return `${Math.floor(d / WEEK_S)}w ago`;
  return `${Math.floor(d / (TODAY_S * 30))}mo ago`;
}

const VALID_ANGLES: Angle[] = ["BOLD", "PLAYFUL", "SEXUAL", "SINCERE", "CURIOUS"];

function normalizeAngle(label?: string | null): Angle | null {
  if (!label) return null;
  const upper = label.toUpperCase();
  if (VALID_ANGLES.includes(upper as Angle)) return upper as Angle;
  return null;
}

export default function ChatsScreen() {
  const { token } = useAuth();
  const router = useRouter();
  const unseen = useUnseenChats();
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

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

  // Filter + bucket the chats. Memoised so pull-to-refresh / search
  // typing aren't O(n*m) the whole list.
  const { today, week, older, totalUnread } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? chats.filter(
          (c) =>
            c.contact.toLowerCase().includes(q) ||
            (c.last_text || "").toLowerCase().includes(q),
        )
      : chats;
    const now = Date.now() / 1000;
    const today: ChatSummary[] = [];
    const week: ChatSummary[] = [];
    const older: ChatSummary[] = [];
    let totalUnread = 0;
    for (const c of filtered) {
      const age = now - (c.last_activity_at || 0);
      if (age < TODAY_S) today.push(c);
      else if (age < WEEK_S) week.push(c);
      else older.push(c);
      if (unseen.has(c.id)) totalUnread += 1;
    }
    return { today, week, older, totalUnread };
  }, [chats, query, unseen]);

  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: theme.bg }}>
      <TopBar
        mode="stack"
        title="Your chats"
        onBack={() => router.back()}
        right={
          chats.length > 0 ? (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              {totalUnread > 0 ? (
                <View
                  style={{
                    backgroundColor: theme.accent,
                    paddingHorizontal: 7,
                    paddingVertical: 3,
                    borderRadius: theme.radii.pill,
                  }}
                >
                  <Text
                    style={{
                      color: theme.bg,
                      fontSize: 11,
                      fontWeight: theme.fontWeights.bold,
                      letterSpacing: 0.4,
                    }}
                  >
                    {totalUnread} new
                  </Text>
                </View>
              ) : null}
              <Text
                style={{
                  color: theme.dim,
                  fontSize: theme.fontSizes.sm,
                  fontWeight: theme.fontWeights.semibold,
                }}
              >
                {chats.length}
              </Text>
            </View>
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
          keyboardShouldPersistTaps="handled"
        >
          <SearchBar value={query} onChange={setQuery} />

          {today.length > 0 ? (
            <ChatGroup
              label="Today"
              chats={today}
              unseen={unseen}
              onOpen={(c) =>
                router.push({
                  pathname: "/chat/[id]",
                  params: { id: c.id, contact: c.contact },
                })
              }
              onDelete={onDelete}
            />
          ) : null}
          {week.length > 0 ? (
            <ChatGroup
              label="Earlier this week"
              chats={week}
              unseen={unseen}
              onOpen={(c) =>
                router.push({
                  pathname: "/chat/[id]",
                  params: { id: c.id, contact: c.contact },
                })
              }
              onDelete={onDelete}
            />
          ) : null}
          {older.length > 0 ? (
            <ChatGroup
              label="Older"
              chats={older}
              unseen={unseen}
              onOpen={(c) =>
                router.push({
                  pathname: "/chat/[id]",
                  params: { id: c.id, contact: c.contact },
                })
              }
              onDelete={onDelete}
            />
          ) : null}

          {today.length + week.length + older.length === 0 && query.trim() ? (
            <View style={{ padding: theme.spacing.xxl, alignItems: "center" }}>
              <Text style={{ color: theme.dim, fontSize: theme.fontSizes.md }}>
                No chats match "{query}"
              </Text>
            </View>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

/* ───────────── Building blocks ───────────── */

function SearchBar({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <View style={{ paddingHorizontal: theme.spacing.lg, paddingTop: theme.spacing.md, paddingBottom: 4 }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 10,
          paddingHorizontal: 14,
          paddingVertical: 10,
          borderRadius: 12,
          backgroundColor: theme.surface,
          borderWidth: 1,
          borderColor: theme.border,
        }}
      >
        <SearchGlyph />
        <TextInput
          value={value}
          onChangeText={onChange}
          placeholder="Search names or chats"
          placeholderTextColor={theme.dimmer}
          style={{
            flex: 1,
            color: theme.text,
            fontSize: theme.fontSizes.md,
            padding: 0,
          }}
          returnKeyType="search"
        />
        {value.length > 0 ? (
          <Pressable onPress={() => onChange("")}>
            <Text style={{ color: theme.dim, fontSize: 14 }}>✕</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

function SearchGlyph() {
  return (
    <View
      style={{
        width: 14,
        height: 14,
        borderWidth: 1.5,
        borderColor: theme.dim,
        borderRadius: 7,
      }}
    />
  );
}

function ChatGroup({
  label,
  chats,
  unseen,
  onOpen,
  onDelete,
}: {
  label: string;
  chats: ChatSummary[];
  unseen: Set<string>;
  onOpen: (c: ChatSummary) => void;
  onDelete: (c: ChatSummary) => void;
}) {
  return (
    <View style={{ marginTop: 12 }}>
      <View
        style={{
          paddingHorizontal: 22,
          paddingTop: 8,
          paddingBottom: 6,
        }}
      >
        <Text
          style={{
            color: theme.dim,
            fontSize: 11,
            fontWeight: theme.fontWeights.bold,
            letterSpacing: theme.tracking.label,
            textTransform: "uppercase",
          }}
        >
          {label}
        </Text>
      </View>
      <View
        style={{
          marginHorizontal: theme.spacing.lg,
          backgroundColor: theme.surface,
          borderWidth: 1,
          borderColor: theme.border,
          borderRadius: theme.radii.lg,
          overflow: "hidden",
        }}
      >
        {chats.map((c, i) => (
          <ChatRow
            key={c.id}
            chat={c}
            isLast={i === chats.length - 1}
            hasUnseen={unseen.has(c.id)}
            onOpen={() => onOpen(c)}
            onDelete={() => onDelete(c)}
          />
        ))}
      </View>
    </View>
  );
}

function ChatRow({
  chat,
  isLast,
  hasUnseen,
  onOpen,
  onDelete,
}: {
  chat: ChatSummary;
  isLast: boolean;
  hasUnseen: boolean;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const lastPrefix = chat.last_speaker === "me" ? "You: " : "";
  const angle = normalizeAngle(chat.last_copied_angle);
  const angleColor = angle ? theme.angle[angle] : null;

  return (
    <Pressable onPress={onOpen} onLongPress={onDelete}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 12,
          paddingHorizontal: 14,
          paddingVertical: 14,
          borderBottomWidth: isLast ? 0 : 1,
          borderBottomColor: theme.border,
        }}
      >
        <Avatar
          size={44}
          name={chat.contact}
          readyRing={chat.has_replies}
          unreadCount={hasUnseen ? 1 : undefined}
        />

        <View style={{ flex: 1, gap: 3 }}>
          {/* Top row: name + source pill on left, when on right */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 8,
            }}
          >
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 7,
                flex: 1,
                minWidth: 0,
              }}
            >
              <Text
                style={{
                  fontSize: 16,
                  fontWeight: theme.fontWeights.bold,
                  color: theme.text,
                  flexShrink: 1,
                }}
                numberOfLines={1}
              >
                {chat.contact || "Unknown"}
              </Text>
              {chat.source ? <SourceBadge source={chat.source} /> : null}
            </View>
            <Text
              style={{
                color: theme.dimmer,
                fontSize: 12,
                fontWeight: theme.fontWeights.medium,
              }}
            >
              {formatLastActivity(chat.last_activity_at)}
            </Text>
          </View>

          {/* Preview */}
          {chat.last_text ? (
            <Text
              style={{
                color: hasUnseen ? theme.text : theme.dim,
                fontSize: 14,
                lineHeight: 19,
                fontWeight: hasUnseen
                  ? theme.fontWeights.medium
                  : theme.fontWeights.regular,
              }}
              numberOfLines={1}
            >
              {lastPrefix ? (
                <Text
                  style={{
                    color: theme.dimmer,
                    fontWeight: theme.fontWeights.semibold,
                  }}
                >
                  {lastPrefix}
                </Text>
              ) : null}
              {chat.last_text}
            </Text>
          ) : null}

          {/* Bottom row: msg count + last copied angle / replies-ready */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              marginTop: 2,
            }}
          >
            <Text
              style={{
                color: theme.dimmer,
                fontSize: 12,
                fontWeight: theme.fontWeights.medium,
              }}
            >
              {chat.msg_count} msg{chat.msg_count === 1 ? "" : "s"}
            </Text>

            {chat.has_replies && angle && angleColor ? (
              <>
                <Text style={{ color: theme.dimmer }}>·</Text>
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 5,
                  }}
                >
                  <View
                    style={{
                      width: 5,
                      height: 5,
                      borderRadius: 3,
                      backgroundColor: angleColor,
                    }}
                  />
                  <Text
                    style={{
                      fontSize: 10,
                      fontWeight: theme.fontWeights.bold,
                      letterSpacing: theme.tracking.label,
                      color: angleColor,
                    }}
                  >
                    {angle}
                  </Text>
                </View>
                <Text
                  style={{
                    color: theme.dimmer,
                    fontSize: 11,
                  }}
                >
                  last copied
                </Text>
              </>
            ) : chat.has_replies ? (
              <>
                <Text style={{ color: theme.dimmer }}>·</Text>
                <Text
                  style={{
                    fontSize: 10,
                    fontWeight: theme.fontWeights.bold,
                    letterSpacing: theme.tracking.label,
                    color: theme.accent,
                  }}
                >
                  5 REPLIES READY
                </Text>
              </>
            ) : null}
          </View>
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
      <View
        style={{
          width: 124,
          height: 124,
          alignItems: "center",
          justifyContent: "center",
          gap: 6,
          padding: 8,
        }}
      >
        {[0, 1, 2, 3].map((i) => (
          <View
            key={i}
            style={{
              width: 90,
              height: 14,
              borderRadius: 7,
              backgroundColor:
                i % 2 === 0 ? theme.surface2 : "rgba(102,224,180,0.18)",
              alignSelf: i % 2 === 0 ? "flex-start" : "flex-end",
            }}
          />
        ))}
      </View>
      <View style={{ alignItems: "center", gap: theme.spacing.sm, maxWidth: 280 }}>
        <Text
          style={{
            color: theme.text,
            fontSize: theme.fontSizes.xl,
            fontWeight: theme.fontWeights.bold,
            textAlign: "center",
            letterSpacing: theme.tracking.tight,
          }}
        >
          Nothing here yet
        </Text>
        <Text
          style={{
            color: theme.dim,
            fontSize: theme.fontSizes.md,
            lineHeight: theme.fontSizes.md * theme.lineHeights.body,
            textAlign: "center",
          }}
        >
          Capture a chat — Muzo saves the conversation and your replies for later.
        </Text>
      </View>
      <View style={{ width: "100%", maxWidth: 320 }}>
        <PrimaryButton label="Capture a chat" onPress={onCapture} />
      </View>
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
