// Chat detail — REPLIES section + CONVERSATION section.
// Replies persist server-side after every quick-capture so the user can
// regenerate fresh replies anytime without re-uploading the screenshot.

import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, ApiError, ReplyOption } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { markChatSeen, useUnseenChats } from "../../lib/genQueue";
import { openPaywall } from "../../lib/paywallStore";
import { takeCachedResult } from "../../lib/recentResult";
import { theme, Angle } from "../../lib/theme";
import {
  Pressable,
  PrimaryButton,
  ReplyCard,
  TopBar,
} from "../../components/ui";
import { Avatar } from "../../components/Avatar";
import { ModeToggle } from "../../components/ModeToggle";
import { NewScreenshotBanner } from "../../components/NewScreenshotBanner";
import { useMode } from "../../lib/modeStore";

type ChatDetail = {
  id: string;
  contact: string;
  messages: { speaker: "me" | "them"; text: string }[];
  replies: ReplyOption[];
  read?: string;
  advice?: string;
  /** User-pinned context that auto-merges into every regen +
   *  follow-up screenshot for this chat. */
  locked_context?: string;
  locked_context_enabled?: boolean;
};

export default function ChatDetailScreen() {
  const { id, contact } = useLocalSearchParams<{
    id: string;
    contact?: string;
  }>();
  const { token } = useAuth();
  const router = useRouter();
  // "Other chats have fresh replies" indicator on the back button —
  // hide ourselves from the count so it only shows other-chat dots.
  const unseen = useUnseenChats();
  const otherUnseenCount = id
    ? Array.from(unseen).filter((cid) => cid !== id).length
    : unseen.size;

  // Pull the freshly-generated result from the in-memory cache for an
  // instant first paint when navigating from home → quick-capture →
  // here. The next render's API fetch then refreshes if needed.
  const initial = id ? takeCachedResult(id) : null;
  const [data, setData] = useState<ChatDetail | null>(
    initial
      ? {
          id: initial.id,
          contact: initial.contact,
          messages: initial.messages,
          replies: initial.replies,
          read: initial.read,
          advice: initial.advice,
        }
      : null,
  );
  const [loading, setLoading] = useState(!initial);
  const [regenerating, setRegenerating] = useState(false);
  const [extra, setExtra] = useState("");
  const [showExtra, setShowExtra] = useState(false);
  // Locked context — pinned to this chat, auto-merges into every
  // regen + follow-up screenshot so the user types it once.
  const [lockedDraft, setLockedDraft] = useState("");
  const [lockedSaved, setLockedSaved] = useState(false);
  const [showLocked, setShowLocked] = useState(false);
  const [savingLock, setSavingLock] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useMode();

  const load = useCallback(
    async (opts?: { background?: boolean }) => {
      if (!token || !id) return;
      // When background=true we don't show a spinner because the
      // cached result is already on screen — we're only refreshing
      // server-side fields like locked_context that the cache doesn't
      // carry.
      const background = !!opts?.background;
      if (!background) {
        setLoading(true);
      }
      setError(null);
      try {
        const r = await api.getChat(token, id);
        setData(r);
        // Hydrate the locked-context inputs from the server response.
        // Hydrating these from the server is the WHOLE reason we still
        // hit the network even when the cached capture-result already
        // populated `data` — the in-memory cache only carries
        // messages/replies and would otherwise leave the lock UI
        // looking empty even when the user has one saved.
        if (typeof r?.locked_context === "string") {
          setLockedDraft(r.locked_context);
          setLockedSaved(!!r.locked_context_enabled);
          if (r.locked_context_enabled) setShowLocked(true);
        }
      } catch (e: any) {
        if (!background) {
          setError(e instanceof ApiError ? e.detail : e?.message || "error");
        }
        // On background refresh failures we silently keep the cached
        // data — better UX than flashing an error over working content.
      } finally {
        if (!background) setLoading(false);
      }
    },
    [token, id],
  );

  // Always fetch on mount. If we already have cached data (from a
  // fresh capture), do it as a background refresh so the user sees
  // an instant first paint AND the server-only fields (locked_context,
  // locked_context_enabled) get populated.
  useEffect(() => {
    if (data) {
      void load({ background: true });
    } else {
      void load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Mark this chat as seen the moment we open it — clears the dot.
  useEffect(() => {
    if (id) markChatSeen(id);
  }, [id]);

  const onRegenerate = async () => {
    if (!token || !id || regenerating) return;
    setRegenerating(true);
    try {
      const r = await api.regenerate(token, id, extra, mode);
      setData((prev) =>
        prev
          ? {
              ...prev,
              replies: r.replies || [],
              read: r.read || "",
              advice: r.advice || "",
            }
          : prev,
      );
      setExtra("");
      setShowExtra(false);
    } catch (e: any) {
      const detail = e instanceof ApiError ? e.detail : "request_failed";
      if (
        detail === "pro_locked_free" ||
        detail === "daily_cap_free" ||
        detail === "lifetime_trial_exhausted"
      ) {
        openPaywall(detail);
      } else {
        Alert.alert("Couldn't regenerate", prettyDetail(detail));
      }
    } finally {
      setRegenerating(false);
    }
  };

  const prettyDetail = (d: string) => {
    if (d === "no_replies_produced")
      return "Couldn't read that screenshot clearly. Try a sharper one.";
    if (d === "chat_not_found")
      return "This chat is no longer available.";
    if (d === "generation_failed")
      return "Generation hit a snag. Try again — different chats sometimes succeed where one stalls.";
    if (d.startsWith("network:") || /network/i.test(d))
      return "Couldn't reach Muzo. Check your connection and try again.";
    if (d === "request_failed") return "Server hiccup. Try again in a sec.";
    return d;
  };

  const trackCopy = (label: string, text: string) => {
    if (token && id) {
      api.copyReply(token, id, label, text).catch(() => {});
    }
  };

  const onSaveLocked = async () => {
    if (!token || !id || savingLock) return;
    setSavingLock(true);
    try {
      const trimmed = lockedDraft.trim();
      const r = await api.setLockedContext(token, id, trimmed, true);
      setLockedDraft(r.locked_context);
      setLockedSaved(r.locked_context_enabled);
    } catch (e: any) {
      const detail = e instanceof ApiError ? e.detail : "request_failed";
      Alert.alert("Couldn't save", prettyDetail(detail));
    } finally {
      setSavingLock(false);
    }
  };

  const onClearLocked = async () => {
    if (!token || !id || savingLock) return;
    setSavingLock(true);
    try {
      await api.setLockedContext(token, id, "", false);
      setLockedDraft("");
      setLockedSaved(false);
    } catch {
      // Swallow — clearing is non-critical.
    } finally {
      setSavingLock(false);
    }
  };

  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: theme.bg }}>
      <TopBar
        mode="stack"
        title={data?.contact || contact || "Chat"}
        onBack={() => router.back()}
        right={
          otherUnseenCount > 0 ? (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                backgroundColor: theme.accentDim,
                borderColor: theme.accent,
                borderWidth: 1,
                borderRadius: theme.radii.pill,
                paddingHorizontal: 8,
                paddingVertical: 3,
              }}
            >
              <View
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 3,
                  backgroundColor: theme.accent,
                }}
              />
              <Text
                style={{
                  color: theme.accent,
                  fontSize: 11,
                  fontWeight: theme.fontWeights.bold,
                  letterSpacing: theme.tracking.label,
                }}
              >
                {otherUnseenCount} READY
              </Text>
            </View>
          ) : null
        }
      />

      <NewScreenshotBanner />

      <ScrollView
        contentContainerStyle={{
          padding: theme.spacing.lg,
          paddingBottom: 80,
        }}
      >
        {/* Contact identity strip — avatar + name. Sets up nicely
            for the future user-uploaded profile photo feature. */}
        {data ? (
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: theme.spacing.md,
              marginBottom: theme.spacing.lg,
            }}
          >
            <Avatar size={48} />
            <View style={{ flex: 1 }}>
              <Text
                style={{
                  color: theme.text,
                  fontSize: theme.fontSizes.lg,
                  fontWeight: theme.fontWeights.bold,
                }}
                numberOfLines={1}
              >
                {data.contact}
              </Text>
              <Text
                style={{
                  color: theme.dim,
                  fontSize: theme.fontSizes.sm,
                }}
              >
                {data.messages.length} msg
                {data.messages.length === 1 ? "" : "s"}
              </Text>
            </View>
          </View>
        ) : null}
        {loading ? (
          <View style={{ marginTop: 80, alignItems: "center" }}>
            <ActivityIndicator color={theme.accent} size="large" />
          </View>
        ) : error ? (
          <View
            style={{
              alignItems: "center",
              gap: theme.spacing.md,
              marginTop: 40,
              paddingHorizontal: theme.spacing.lg,
            }}
          >
            <Text
              style={{
                color: theme.error,
                fontSize: theme.fontSizes.md,
                textAlign: "center",
              }}
            >
              {prettyDetail(error)}
            </Text>
            <Pressable onPress={() => load(true)}>
              <Text
                style={{
                  color: theme.accent,
                  fontSize: theme.fontSizes.md,
                  fontWeight: theme.fontWeights.semibold,
                }}
              >
                Retry
              </Text>
            </Pressable>
          </View>
        ) : data ? (
          <View style={{ gap: theme.spacing.lg }}>
            {/* REPLIES SECTION */}
            <View style={{ gap: theme.spacing.md }}>
              <View
                style={{
                  flexDirection: "row",
                  justifyContent: "space-between",
                  alignItems: "center",
                  paddingHorizontal: 4,
                }}
              >
                <SectionLabel>Replies</SectionLabel>
                <SectionLabel dim>
                  {data.replies.length || 0} options
                </SectionLabel>
              </View>

              {regenerating ? (
                <View
                  style={{
                    backgroundColor: theme.accentDim,
                    borderTopWidth: 2,
                    borderTopColor: theme.accent,
                    borderBottomWidth: 1,
                    borderBottomColor: theme.border,
                    borderRadius: theme.radii.md,
                    padding: theme.spacing.lg,
                    flexDirection: "row",
                    alignItems: "center",
                    gap: theme.spacing.md,
                  }}
                >
                  <ActivityIndicator color={theme.accent} />
                  <Text
                    style={{
                      color: theme.accent,
                      fontWeight: theme.fontWeights.semibold,
                      flex: 1,
                    }}
                  >
                    Generating fresh replies…
                  </Text>
                </View>
              ) : data.replies.length === 0 ? (
                <Text
                  style={{
                    color: theme.dim,
                    fontSize: theme.fontSizes.md,
                  }}
                >
                  No replies yet — tap "Regenerate" below.
                </Text>
              ) : (
                data.replies.map((r, idx) => (
                  <ReplyCard
                    key={`${r.label}-${idx}`}
                    angle={normalizeAngle(r.label)}
                    text={r.text}
                    why={r.why}
                    onCopy={trackCopy}
                  />
                ))
              )}

              {(data.read || data.advice) && (
                <View
                  style={{
                    backgroundColor: theme.surface2,
                    borderRadius: theme.radii.md + 2,
                    padding: theme.spacing.md + 2,
                    gap: theme.spacing.xs,
                  }}
                >
                  {data.read ? (
                    <Text style={{ color: theme.text, fontSize: 14, lineHeight: 20 }}>
                      <Text
                        style={{
                          color: theme.dim,
                          fontWeight: theme.fontWeights.bold,
                        }}
                      >
                        Read:{" "}
                      </Text>
                      {data.read}
                    </Text>
                  ) : null}
                  {data.advice ? (
                    <Text style={{ color: theme.text, fontSize: 14, lineHeight: 20 }}>
                      <Text
                        style={{
                          color: theme.dim,
                          fontWeight: theme.fontWeights.bold,
                        }}
                      >
                        Move:{" "}
                      </Text>
                      {data.advice}
                    </Text>
                  ) : null}
                </View>
              )}

              {/* Locked context — pinned to the chat. Auto-merges into
                  every regen + follow-up screenshot for this contact. */}
              <Pressable onPress={() => setShowLocked((s) => !s)}>
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "space-between",
                    backgroundColor: lockedSaved ? theme.accentDim : theme.surface,
                    borderWidth: 1,
                    borderColor: lockedSaved ? theme.accent : theme.border,
                    borderRadius: theme.radii.md,
                    paddingHorizontal: theme.spacing.md + 2,
                    paddingVertical: 10,
                  }}
                >
                  <Text
                    style={{
                      color: lockedSaved ? theme.accent : theme.dim,
                      fontSize: 14,
                      fontWeight: theme.fontWeights.semibold,
                    }}
                  >
                    {lockedSaved ? "🔒 Locked context · saved" : "🔒 Lock context for this chat"}
                  </Text>
                  <Text
                    style={{
                      color: lockedSaved ? theme.accent : theme.dimmer,
                      fontSize: 12,
                    }}
                  >
                    {showLocked ? "Close" : lockedSaved ? "Edit" : "Optional"}
                  </Text>
                </View>
              </Pressable>

              {showLocked ? (
                <View style={{ gap: theme.spacing.sm }}>
                  <TextInput
                    placeholder="e.g. she's the climber from Hinge, vegan, allergic to cats"
                    placeholderTextColor={theme.dimmer}
                    value={lockedDraft}
                    onChangeText={setLockedDraft}
                    multiline
                    style={{
                      backgroundColor: theme.surface,
                      borderRadius: theme.radii.md,
                      borderWidth: 1,
                      borderColor: theme.border,
                      color: theme.text,
                      fontSize: theme.fontSizes.md,
                      padding: theme.spacing.md,
                      minHeight: 80,
                      textAlignVertical: "top",
                    }}
                  />
                  <Text
                    style={{
                      color: theme.dimmer,
                      fontSize: 12,
                      lineHeight: 18,
                    }}
                  >
                    Saved here, auto-applied to every reply Muzo writes for
                    this chat — including new screenshots of the same conversation.
                  </Text>
                  <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
                    <View style={{ flex: 1 }}>
                      <PrimaryButton
                        label={
                          savingLock
                            ? "Saving…"
                            : lockedSaved
                              ? "Update"
                              : "Save & lock"
                        }
                        onPress={onSaveLocked}
                        disabled={savingLock || !lockedDraft.trim()}
                      />
                    </View>
                    {lockedSaved ? (
                      <Pressable onPress={onClearLocked}>
                        <View
                          style={{
                            paddingHorizontal: theme.spacing.md,
                            paddingVertical: 12,
                            borderRadius: theme.radii.md,
                            borderWidth: 1,
                            borderColor: theme.border,
                          }}
                        >
                          <Text
                            style={{
                              color: theme.dim,
                              fontSize: 14,
                              fontWeight: theme.fontWeights.semibold,
                            }}
                          >
                            Clear
                          </Text>
                        </View>
                      </Pressable>
                    ) : null}
                  </View>
                </View>
              ) : null}

              <Pressable onPress={() => setShowExtra((s) => !s)}>
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "space-between",
                    backgroundColor: theme.surface,
                    borderWidth: 1,
                    borderColor: theme.border,
                    borderRadius: theme.radii.md,
                    paddingHorizontal: theme.spacing.md + 2,
                    paddingVertical: 10,
                  }}
                >
                  <Text
                    style={{
                      color: theme.dim,
                      fontSize: 14,
                      fontWeight: theme.fontWeights.semibold,
                    }}
                  >
                    + Add extra context (one-time)
                  </Text>
                  <Text style={{ color: theme.dimmer, fontSize: 12 }}>
                    {showExtra ? "Close" : "Optional"}
                  </Text>
                </View>
              </Pressable>

              {showExtra ? (
                <TextInput
                  placeholder="e.g. she just got back from a trip"
                  placeholderTextColor={theme.dimmer}
                  value={extra}
                  onChangeText={setExtra}
                  multiline
                  style={{
                    backgroundColor: theme.surface,
                    borderRadius: theme.radii.md,
                    borderWidth: 1,
                    borderColor: theme.border,
                    color: theme.text,
                    fontSize: theme.fontSizes.md,
                    padding: theme.spacing.md,
                    minHeight: 80,
                    textAlignVertical: "top",
                  }}
                />
              ) : null}

              {/* Mode + regenerate row — toggle on the left, primary
                  button on the right so the mode is obvious before tap. */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: theme.spacing.md,
                }}
              >
                <ModeToggle mode={mode} onChange={setMode} size="sm" />
                <View style={{ flex: 1 }}>
                  <PrimaryButton
                    label={
                      mode === "pro" ? "Regenerate (Pro)" : "Regenerate"
                    }
                    onPress={onRegenerate}
                    loading={regenerating}
                  />
                </View>
              </View>
            </View>

            {/* CONVERSATION SECTION */}
            <View style={{ gap: theme.spacing.md }}>
              <View style={{ paddingHorizontal: 4 }}>
                <SectionLabel>
                  Conversation · {data.messages.length} msg
                  {data.messages.length === 1 ? "" : "s"}
                </SectionLabel>
              </View>
              <View
                style={{
                  backgroundColor: theme.surface,
                  borderWidth: 1,
                  borderColor: theme.border,
                  borderRadius: theme.radii.lg,
                  padding: theme.spacing.md + 2,
                  gap: 6,
                }}
              >
                {data.messages.map((m, idx) => (
                  <Bubble key={idx} side={m.speaker}>
                    {m.text}
                  </Bubble>
                ))}
              </View>
            </View>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function SectionLabel({
  children,
  dim,
}: {
  children: React.ReactNode;
  dim?: boolean;
}) {
  return (
    <Text
      style={{
        fontSize: 11,
        fontWeight: theme.fontWeights.bold,
        letterSpacing: theme.tracking.label,
        textTransform: "uppercase",
        color: dim ? theme.dimmer : theme.dim,
      }}
    >
      {children}
    </Text>
  );
}

function Bubble({
  side,
  children,
}: {
  side: "me" | "them";
  children: React.ReactNode;
}) {
  const me = side === "me";
  return (
    <View
      style={{
        alignSelf: me ? "flex-end" : "flex-start",
        maxWidth: "85%",
        backgroundColor: me ? theme.accentDim : theme.surface2,
        borderRadius: 18,
        borderBottomRightRadius: me ? 6 : 18,
        borderBottomLeftRadius: me ? 18 : 6,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
      }}
    >
      <Text
        style={{
          color: me ? theme.accent : theme.text,
          fontSize: theme.fontSizes.md,
          lineHeight: theme.fontSizes.md * theme.lineHeights.body,
        }}
      >
        {children}
      </Text>
    </View>
  );
}

const VALID_ANGLES: Angle[] = ["BOLD", "PLAYFUL", "SEXUAL", "SINCERE", "CURIOUS"];

function normalizeAngle(label: string): Angle {
  const upper = label.toUpperCase();
  if (VALID_ANGLES.includes(upper as Angle)) return upper as Angle;
  if (upper.includes("BOLD") || upper.includes("DIRECT")) return "BOLD";
  if (upper.includes("PLAY") || upper.includes("FUN")) return "PLAYFUL";
  if (upper.includes("SEX") || upper.includes("FLIRT")) return "SEXUAL";
  if (upper.includes("SINC") || upper.includes("WARM")) return "SINCERE";
  if (upper.includes("CURI") || upper.includes("ASK")) return "CURIOUS";
  return "PLAYFUL";
}
