// GenerationDock — persistent floating chips at the bottom of the
// screen. Mounted ONCE in the root layout so it survives navigation,
// shows on every screen, and never gets cancelled when the user
// switches between chats / opens settings / etc.
//
// Visual model:
//   • Running jobs render a mint chip with spinner + age timer
//   • Ready jobs render a brighter mint chip with the contact name and
//     a "View" CTA — tapping navigates to that chat detail and clears
//     the chip
//   • Error jobs render a red chip with retry / dismiss
//
// Keeps under 3 chips visible; older ones collapse into a "+N more".

import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { Pressable } from "./ui";
import {
  clearJob,
  Job,
  useJobs,
} from "../lib/genQueue";
import { theme } from "../lib/theme";

const MAX_VISIBLE = 3;

export function GenerationDock() {
  const jobs = useJobs();
  const router = useRouter();

  if (jobs.length === 0) return null;

  const visible = jobs.slice(0, MAX_VISIBLE);
  const overflow = jobs.length - visible.length;

  return (
    <View
      pointerEvents="box-none"
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 16,
        paddingHorizontal: theme.spacing.md,
        gap: 6,
        // Above tab bar / floating add buttons
        zIndex: 50,
      }}
    >
      {visible.map((j) => (
        <JobChip
          key={j.id}
          job={j}
          onView={() => {
            if (j.status === "ready" && j.chatId) {
              clearJob(j.id);
              router.push({
                pathname: "/chat/[id]",
                params: { id: j.chatId, contact: j.contact || "" },
              });
            }
          }}
          onDismiss={() => clearJob(j.id)}
        />
      ))}
      {overflow > 0 ? (
        <View
          style={{
            alignSelf: "center",
            backgroundColor: theme.surface,
            borderWidth: 1,
            borderColor: theme.border,
            borderRadius: theme.radii.pill,
            paddingHorizontal: theme.spacing.md,
            paddingVertical: 4,
          }}
        >
          <Text
            style={{
              color: theme.dim,
              fontSize: theme.fontSizes.sm,
              fontWeight: theme.fontWeights.semibold,
            }}
          >
            +{overflow} more in queue
          </Text>
        </View>
      ) : null}
    </View>
  );
}

function JobChip({
  job,
  onView,
  onDismiss,
}: {
  job: Job;
  onView: () => void;
  onDismiss: () => void;
}) {
  // Live age counter for running jobs.
  const [age, setAge] = useState(() =>
    Math.max(0, Math.floor((Date.now() - job.startedAt) / 1000)),
  );
  useEffect(() => {
    if (job.status !== "running") return;
    const t = setInterval(() => {
      setAge(Math.max(0, Math.floor((Date.now() - job.startedAt) / 1000)));
    }, 1000);
    return () => clearInterval(t);
  }, [job.status, job.startedAt]);

  if (job.status === "running") {
    return (
      <Chip
        bg={theme.accentDim}
        border={theme.accent}
        leading={<ActivityIndicator size="small" color={theme.accent} />}
        title="Generating replies"
        subtitle={`${age}s · keep using the app`}
        onClose={onDismiss}
        closeColor={theme.accent}
      />
    );
  }
  if (job.status === "ready") {
    return (
      <Chip
        bg={theme.accent}
        border={theme.accent}
        leading={
          <Text
            style={{
              color: theme.bg,
              fontSize: 14,
              fontWeight: theme.fontWeights.bold,
            }}
          >
            ✓
          </Text>
        }
        title={`Replies ready · ${job.contact || "chat"}`}
        subtitle="Tap to view"
        onTap={onView}
        onClose={onDismiss}
        textColor={theme.bg}
        closeColor={theme.bg}
      />
    );
  }
  // Error
  return (
    <Chip
      bg="rgba(255,71,87,0.15)"
      border={theme.error}
      leading={
        <Text
          style={{
            color: theme.error,
            fontSize: 14,
            fontWeight: theme.fontWeights.bold,
          }}
        >
          !
        </Text>
      }
      title="Generation failed"
      subtitle={prettyJobError(job.errorDetail)}
      onClose={onDismiss}
      textColor={theme.error}
      closeColor={theme.error}
    />
  );
}

function Chip({
  bg,
  border,
  leading,
  title,
  subtitle,
  onTap,
  onClose,
  textColor,
  closeColor,
}: {
  bg: string;
  border: string;
  leading: React.ReactNode;
  title: string;
  subtitle?: string;
  onTap?: () => void;
  onClose?: () => void;
  textColor?: string;
  closeColor?: string;
}) {
  const body = (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        backgroundColor: bg,
        borderColor: border,
        borderWidth: 1,
        borderRadius: theme.radii.pill,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm + 2,
        shadowColor: "#000",
        shadowOpacity: 0.4,
        shadowOffset: { width: 0, height: 6 },
        shadowRadius: 16,
        elevation: 6,
      }}
    >
      <View style={{ width: 22, alignItems: "center" }}>{leading}</View>
      <View style={{ flex: 1 }}>
        <Text
          numberOfLines={1}
          style={{
            color: textColor || theme.text,
            fontSize: theme.fontSizes.sm,
            fontWeight: theme.fontWeights.bold,
          }}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text
            numberOfLines={1}
            style={{
              color: textColor || theme.dim,
              fontSize: 12,
              fontWeight: theme.fontWeights.semibold,
              opacity: textColor ? 0.85 : 1,
            }}
          >
            {subtitle}
          </Text>
        ) : null}
      </View>
      {onClose ? (
        <Pressable onPress={onClose}>
          <View style={{ paddingHorizontal: 6, paddingVertical: 4 }}>
            <Text
              style={{
                color: closeColor || theme.dim,
                fontSize: 16,
                fontWeight: theme.fontWeights.bold,
              }}
            >
              ✕
            </Text>
          </View>
        </Pressable>
      ) : null}
    </View>
  );
  if (onTap) {
    return <Pressable onPress={onTap}>{body}</Pressable>;
  }
  return body;
}

function prettyJobError(detail?: string): string {
  if (!detail) return "Tap × to dismiss";
  if (detail === "daily_cap_free") return "Free limit hit — upgrade to keep going";
  if (detail === "daily_cap_paid") return "Daily limit hit — try tomorrow";
  if (detail === "no_replies_produced") return "Couldn't read clearly. Try again";
  if (detail.startsWith("network:")) return "No internet";
  return "Tap × to dismiss";
}
