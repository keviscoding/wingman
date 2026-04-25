// Home / capture screen — primary interaction surface.
//
// State machine:
//   init                → check permissions / look for fresh screenshot
//   permission_denied   → friendly empty state with "Pick a screenshot"
//   ready               → fresh screenshot available, awaiting Generate tap
//   error               → friendly retry view
//
// Generation itself runs in the global queue (lib/genQueue.ts) so it
// survives navigation, can run in parallel, and is visible everywhere
// via the GenerationDock chips.
//
// Auto-fire: on each fresh foreground we check for a never-before-seen
// screenshot < 90s old. If so, enqueue immediately. Older or already-
// processed screenshots stay as a passive thumbnail.

import * as ImagePicker from "expo-image-picker";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  Linking,
  ScrollView,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "../lib/auth";
import {
  formatAge,
  getMostRecentScreenshot,
  RecentScreenshot,
} from "../lib/screenshot";
import { theme } from "../lib/theme";
import {
  Pressable,
  PrimaryButton,
  TextLink,
  TopBar,
  QuotaBadge,
} from "../components/ui";
import { NewScreenshotBanner } from "../components/NewScreenshotBanner";
import { ModeToggle } from "../components/ModeToggle";
import { ChatsPill } from "../components/ChatsPill";
import { RecentRail } from "../components/RecentRail";
import { enqueueJob, useRunningCount } from "../lib/genQueue";
import { useMode } from "../lib/modeStore";
import { setProcessedScreenshotId } from "../lib/screenshotWatcher";

type Phase =
  | { kind: "init" }
  | { kind: "permission_denied" }
  | { kind: "ready"; screenshot: RecentScreenshot | null }
  | { kind: "error"; message: string; screenshot: RecentScreenshot | null };

const AUTO_FIRE_MAX_AGE_S = 90;

export default function HomeScreen() {
  const { token, me, signOut, refreshMe } = useAuth();
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>({ kind: "init" });
  const runningCount = useRunningCount();
  const [mode, setMode] = useMode();
  const lastProcessedIdRef = useRef<string | null>(null);
  const scanInFlight = useRef(false);

  /* ─────────────── Scan for the most recent screenshot ─────────────── */

  const scan = useCallback(async (autoUpload: boolean): Promise<void> => {
    if (scanInFlight.current) return;
    scanInFlight.current = true;
    try {
      const r = await getMostRecentScreenshot();
      if (r.status === "permission_denied") {
        setPhase({ kind: "permission_denied" });
        return;
      }
      const found = r.status === "ok" ? r.screenshot : null;
      if (
        autoUpload &&
        found &&
        found.id !== lastProcessedIdRef.current &&
        found.ageSeconds <= AUTO_FIRE_MAX_AGE_S
      ) {
        startGeneration(found);
        // After auto-fire, surface the home as "ready" so the user can
        // queue another. The dock chip handles progress.
        setPhase({ kind: "ready", screenshot: found });
        return;
      }
      setPhase({ kind: "ready", screenshot: found });
    } finally {
      scanInFlight.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ─────────────── Enqueue a generation ─────────────── */
  // Fire-and-forget: hands off to the global queue and returns
  // immediately. The dock chip + push notification handle completion.

  const startGeneration = useCallback(
    (
      shot:
        | RecentScreenshot
        | { uri: string; filename: string; id: string | null },
    ) => {
      if (!token) return;
      const id = "id" in shot && shot.id ? shot.id : null;
      if (id) {
        lastProcessedIdRef.current = id;
        setProcessedScreenshotId(id);
      }
      enqueueJob({
        token,
        uri: shot.uri,
        filename: "filename" in shot ? shot.filename : null,
        screenshotId: id,
        mode,
        refreshMe,
      });
    },
    [token, refreshMe, mode],
  );

  /* ─────────────── Manual pick fallback ─────────────── */

  const pickManual = useCallback(async () => {
    const r = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsMultipleSelection: false,
      quality: 1,
    });
    if (r.canceled || !r.assets?.[0]) return;
    const a = r.assets[0];
    startGeneration({
      uri: a.uri,
      filename: a.fileName || "screenshot.jpg",
      id: a.assetId || null,
    });
  }, [startGeneration]);

  /* ─────────────── Triggers ─────────────── */
  //
  // Two and ONLY two triggers fire `scan(true)` (autoUpload=true):
  //   1. App launch (first home mount)
  //   2. App foreground transition (AppState 'active')
  //
  // Re-focusing the home screen via in-app navigation (e.g. back from
  // chats list) deliberately does NOT scan. Earlier we had a
  // useFocusEffect calling scan(false), which raced with the
  // AppState handler — focus would land first, claim the
  // scanInFlight lock, and the AppState scan would no-op. Net effect:
  // user came back to the app after taking a screenshot and saw the
  // 'New screenshot — Analyze?' banner instead of auto-fire.
  //
  // Removing the focus-scan fixes that race entirely. The home's
  // ready-state thumbnail is refreshed by the foreground AppState
  // scan anyway, so we lose nothing.

  useEffect(() => {
    scan(true);
  }, [scan]);

  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") scan(true);
    });
    return () => sub.remove();
  }, [scan]);

  /* ─────────────── Render ─────────────── */

  return (
    <SafeAreaView
      edges={["top"]}
      style={{ flex: 1, backgroundColor: theme.bg }}
    >
      <TopBar
        right={
          <>
            <QuotaBadge me={me} />
            <ChatsPill onPress={() => router.push("/chats")} />
            <Pressable onPress={() => router.push("/settings")}>
              <View
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 16,
                  backgroundColor: theme.surface2,
                  borderWidth: 1,
                  borderColor: theme.border,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Text
                  style={{
                    color: theme.dim,
                    fontSize: 16,
                    fontWeight: theme.fontWeights.bold,
                    lineHeight: 16,
                  }}
                >
                  ⋯
                </Text>
              </View>
            </Pressable>
          </>
        }
      />

      <NewScreenshotBanner />

      {/* Mode toggle — sits just under the top bar so it's the first
          thing the user notices when there's a screenshot ready. */}
      <View
        style={{
          alignItems: "center",
          paddingTop: theme.spacing.md,
          paddingBottom: theme.spacing.sm,
        }}
      >
        <ModeToggle mode={mode} onChange={setMode} />
      </View>

      <ScrollView
        contentContainerStyle={{
          flexGrow: 1,
          // Generous bottom padding so the floating dock chip never
          // overlaps the primary action button.
          paddingBottom: runningCount > 0 ? 160 : 80,
        }}
        keyboardShouldPersistTaps="handled"
      >
        {/* Recent chats rail — present on every idle state so users can
            jump back into a chat without leaving the home flow. */}
        {phase.kind !== "init" ? (
          <RecentRail
            onSeeAll={() => router.push("/chats")}
            onOpenChat={(c) =>
              router.push({
                pathname: "/chat/[id]",
                params: { id: c.id, contact: c.contact },
              })
            }
          />
        ) : null}

        {phase.kind === "init" && <InitView />}

        {phase.kind === "permission_denied" && (
          <PermissionView onPick={pickManual} onRetry={() => scan(false)} />
        )}

        {phase.kind === "ready" && (
          <ReadyView
            screenshot={phase.screenshot}
            onGenerate={() =>
              phase.screenshot && startGeneration(phase.screenshot)
            }
            onPickManual={pickManual}
            runningCount={runningCount}
          />
        )}

        {phase.kind === "error" && (
          <ErrorView
            message={phase.message}
            onRetry={() => scan(true)}
            onPickManual={pickManual}
          />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

/* ───────────── Subviews ───────────── */

function InitView() {
  return (
    <View style={{ marginTop: 80, alignItems: "center" }}>
      <ActivityIndicator color={theme.accent} size="large" />
    </View>
  );
}

function PermissionView({
  onPick,
  onRetry,
}: {
  onPick: () => void;
  onRetry: () => void;
}) {
  return (
    <View
      style={{
        alignItems: "center",
        paddingHorizontal: theme.spacing.xl,
        paddingTop: 48,
        gap: theme.spacing.xl,
      }}
    >
      <PhoneIllustration />
      <View style={{ alignItems: "center", gap: theme.spacing.sm, maxWidth: 300 }}>
        <Text
          style={{
            color: theme.text,
            fontSize: theme.fontSizes.xl,
            fontWeight: theme.fontWeights.bold,
            textAlign: "center",
            letterSpacing: theme.tracking.tight,
          }}
        >
          Take a screenshot of any chat
        </Text>
        <Text
          style={{
            color: theme.dim,
            fontSize: theme.fontSizes.md,
            lineHeight: theme.fontSizes.md * theme.lineHeights.body,
            textAlign: "center",
          }}
        >
          Wingman reads it instantly and writes 5 perfect replies.
        </Text>
      </View>
      <View style={{ width: "100%", gap: theme.spacing.md + 2 }}>
        <PrimaryButton label="Pick a screenshot" onPress={onPick} />
        <View style={{ alignItems: "center", marginTop: 4 }}>
          <TextLink label="↻ Try auto-detect again" onPress={onRetry} />
        </View>
        <View style={{ alignItems: "center" }}>
          <TextLink
            label="Open settings"
            onPress={() => Linking.openSettings()}
            color={theme.dimmer}
            size={theme.fontSizes.sm}
          />
        </View>
      </View>
    </View>
  );
}

function ReadyView({
  screenshot,
  onGenerate,
  onPickManual,
  runningCount,
}: {
  screenshot: RecentScreenshot | null;
  onGenerate: () => void;
  onPickManual: () => void;
  runningCount: number;
}) {
  if (!screenshot) {
    // Permission granted but no screenshot yet — encourage them to take one
    return (
      <View
        style={{
          alignItems: "center",
          paddingHorizontal: theme.spacing.xl,
          paddingTop: 64,
          gap: theme.spacing.lg,
        }}
      >
        <PhoneIllustration />
        <View style={{ alignItems: "center", gap: theme.spacing.sm, maxWidth: 300 }}>
          <Text
            style={{
              color: theme.text,
              fontSize: theme.fontSizes.xl,
              fontWeight: theme.fontWeights.bold,
              textAlign: "center",
            }}
          >
            Take a screenshot of any chat
          </Text>
          <Text
            style={{
              color: theme.dim,
              fontSize: theme.fontSizes.md,
              lineHeight: theme.fontSizes.md * theme.lineHeights.body,
              textAlign: "center",
            }}
          >
            Wingman reads it instantly and writes 5 perfect replies.
          </Text>
        </View>
        <View style={{ width: "100%" }}>
          <PrimaryButton label="Pick a screenshot" onPress={onPickManual} />
        </View>
      </View>
    );
  }
  return (
    <View
      style={{
        alignItems: "center",
        paddingHorizontal: theme.spacing.xl,
        paddingTop: theme.spacing.xxl,
        gap: theme.spacing.lg,
      }}
    >
      <Thumbnail uri={screenshot.uri} active />
      <View style={{ alignItems: "center", gap: theme.spacing.xs }}>
        <Text
          style={{
            color: theme.text,
            fontSize: theme.fontSizes.md,
            fontWeight: theme.fontWeights.semibold,
          }}
        >
          {formatAge(screenshot.ageSeconds)}
        </Text>
        <Text style={{ color: theme.dimmer, fontSize: theme.fontSizes.sm }}>
          From your library
        </Text>
      </View>
      <View style={{ width: "100%", gap: theme.spacing.md, marginTop: 4 }}>
        <PrimaryButton onPress={onGenerate}>
          <Text
            style={{
              color: theme.bg,
              fontSize: theme.fontSizes.md,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            {runningCount > 0
              ? `Queue another${runningCount > 1 ? ` (${runningCount} running)` : ""} →`
              : "Generate replies →"}
          </Text>
        </PrimaryButton>
        <View style={{ alignItems: "center" }}>
          <TextLink label="Pick a different screenshot" onPress={onPickManual} />
        </View>
      </View>
    </View>
  );
}

function ErrorView({
  message,
  onRetry,
  onPickManual,
}: {
  message: string;
  onRetry: () => void;
  onPickManual: () => void;
}) {
  return (
    <View
      style={{
        paddingHorizontal: theme.spacing.xl,
        paddingTop: 64,
        gap: theme.spacing.lg,
      }}
    >
      <Text
        style={{
          color: theme.text,
          fontSize: theme.fontSizes.lg,
          fontWeight: theme.fontWeights.bold,
          textAlign: "center",
        }}
      >
        {message || "Couldn't generate replies — try again?"}
      </Text>
      <View style={{ width: "100%", gap: theme.spacing.md }}>
        <PrimaryButton label="Retry" onPress={onRetry} />
        <View style={{ alignItems: "center" }}>
          <TextLink label="Pick another screenshot" onPress={onPickManual} />
        </View>
      </View>
    </View>
  );
}

/* ───────────── Bits ───────────── */

function Thumbnail({
  uri,
  active,
  dim,
}: {
  uri?: string | null;
  active?: boolean;
  dim?: boolean;
}) {
  return (
    <View
      style={{
        width: 220,
        height: 360,
        borderRadius: theme.radii.lg,
        overflow: "hidden",
        backgroundColor: theme.surface,
        borderWidth: active ? 2 : 1,
        borderColor: active ? theme.accent : theme.border,
        opacity: dim ? 0.6 : 1,
      }}
    >
      {uri ? (
        <Image
          source={{ uri }}
          style={{ width: "100%", height: "100%" }}
          contentFit="cover"
        />
      ) : null}
      {dim ? (
        <View
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(10,10,15,0.4)",
          }}
        />
      ) : null}
    </View>
  );
}

function PhoneIllustration() {
  // Lightweight blocky phone-with-message icon — matches the SVG in the
  // mockup but rendered as plain Views for zero asset weight.
  return (
    <View
      style={{
        width: 120,
        height: 120,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <View
        style={{
          width: 84,
          height: 132,
          borderRadius: 14,
          borderWidth: 1.5,
          borderColor: theme.border,
          padding: 12,
          gap: 8,
          justifyContent: "flex-start",
        }}
      >
        <View
          style={{
            height: 18,
            width: "60%",
            borderRadius: 9,
            backgroundColor: theme.surface2,
          }}
        />
        <View
          style={{
            height: 18,
            width: "70%",
            borderRadius: 9,
            backgroundColor: theme.surface2,
            alignSelf: "flex-end",
          }}
        />
        <View
          style={{
            height: 18,
            width: "50%",
            borderRadius: 9,
            backgroundColor: theme.surface2,
          }}
        />
      </View>
    </View>
  );
}

