// Banner that floats below the top bar when a new screenshot is
// detected (e.g. user took a screenshot in another app and returned
// to Wingman). Tapping enqueues a job through the global queue using
// the user's currently selected mode (Quick / Pro), so the work is
// indistinguishable from a Generate tap on the home screen.

import { Image } from "expo-image";
import { Text, View } from "react-native";
import { Pressable } from "./ui";
import { useAuth } from "../lib/auth";
import { enqueueJob } from "../lib/genQueue";
import { useMode } from "../lib/modeStore";
import {
  setProcessedScreenshotId,
  useFreshScreenshot,
} from "../lib/screenshotWatcher";
import { theme } from "../lib/theme";

export function NewScreenshotBanner() {
  const { token, refreshMe } = useAuth();
  const { shot, dismiss } = useFreshScreenshot();
  const [mode] = useMode();

  if (!shot) return null;

  const onAnalyze = () => {
    if (!token) return;
    setProcessedScreenshotId(shot.id);
    enqueueJob({
      token,
      uri: shot.uri,
      filename: shot.filename,
      screenshotId: shot.id,
      mode,
      refreshMe,
    });
    dismiss(); // chip in the dock takes over from here
  };

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: theme.spacing.md,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm + 2,
        backgroundColor: theme.surface,
        borderTopWidth: 2,
        borderTopColor: theme.accent,
        borderBottomWidth: 1,
        borderBottomColor: theme.border,
      }}
    >
      <Image
        source={{ uri: shot.uri }}
        style={{
          width: 40,
          height: 56,
          borderRadius: 6,
          backgroundColor: theme.surface2,
        }}
        contentFit="cover"
      />
      <View style={{ flex: 1 }}>
        <Text
          style={{
            color: theme.accent,
            fontSize: 11,
            fontWeight: theme.fontWeights.bold,
            letterSpacing: theme.tracking.label,
          }}
        >
          NEW SCREENSHOT
        </Text>
        <Text
          style={{
            color: theme.text,
            fontSize: theme.fontSizes.md,
            fontWeight: theme.fontWeights.semibold,
            marginTop: 2,
          }}
          numberOfLines={1}
        >
          {mode === "pro" ? "Analyze with Pro?" : "Analyze this chat?"}
        </Text>
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}>
        <Pressable onPress={dismiss}>
          <View style={{ paddingHorizontal: theme.spacing.sm, paddingVertical: 6 }}>
            <Text
              style={{
                color: theme.dim,
                fontSize: theme.fontSizes.sm,
                fontWeight: theme.fontWeights.semibold,
              }}
            >
              Dismiss
            </Text>
          </View>
        </Pressable>
        <Pressable onPress={onAnalyze}>
          <View
            style={{
              paddingHorizontal: theme.spacing.md,
              paddingVertical: 8,
              borderRadius: theme.radii.md,
              backgroundColor: theme.accent,
            }}
          >
            <Text
              style={{
                color: theme.bg,
                fontSize: theme.fontSizes.sm,
                fontWeight: theme.fontWeights.bold,
              }}
            >
              Analyze
            </Text>
          </View>
        </Pressable>
      </View>
    </View>
  );
}
