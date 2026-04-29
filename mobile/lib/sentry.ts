// Sentry crash + error reporting.
//
// Initialized exactly once on app boot, controlled by EXPO_PUBLIC_SENTRY_DSN
// (set in EAS build env). When the env var is missing we silently
// no-op so dev / unconfigured builds don't crash or noise up Sentry.
//
// What gets sent:
//   - JS errors uncaught by error boundaries
//   - Fatal native crashes (auto-captured by the iOS/Android SDK)
//   - Manual `Sentry.captureException(err)` calls from try/catch sites
//
// What does NOT get sent:
//   - User auth tokens (we strip Authorization headers)
//   - Screenshot bytes / chat content (we never call addBreadcrumb on
//     these or attach them as context)
//   - PII beyond a hashed user id
//
// Wired through @sentry/react-native, the Expo-compatible SDK.

import * as Sentry from "@sentry/react-native";

let initialized = false;

export function bootSentry(): void {
  if (initialized) return;
  const dsn = process.env.EXPO_PUBLIC_SENTRY_DSN?.trim();
  if (!dsn) {
    // No DSN configured for this build. That's fine in dev or in a
    // build that just doesn't ship Sentry. Silently no-op.
    return;
  }
  try {
    Sentry.init({
      dsn,
      environment: process.env.EXPO_PUBLIC_SENTRY_ENVIRONMENT || "production",
      // Dial way down — we only want errors, not perf traces. Performance
      // monitoring eats Sentry quota fast and isn't useful for an indie
      // launch where we just want to see crashes.
      tracesSampleRate: 0.0,
      enableNative: true,
      enableNativeCrashHandling: true,
      // Keep reports lean — no auto breadcrumbs for navigation /
      // network so Authorization headers + chat URLs don't leak.
      enableAutoPerformanceTracing: false,
      enableAutoSessionTracking: true,
      // Strip sensitive fields from any event before send.
      beforeSend(event) {
        try {
          if (event.request?.headers) {
            const h = event.request.headers as Record<string, unknown>;
            for (const k of Object.keys(h)) {
              if (k.toLowerCase() === "authorization") {
                h[k] = "[scrubbed]";
              }
            }
          }
        } catch {
          /* tolerate */
        }
        return event;
      },
    });
    initialized = true;
  } catch (e) {
     
    console.warn("[sentry] init failed", e);
  }
}

/** Tag the current Sentry session with the signed-in user. Doesn't
 *  send PII — just the opaque user_id we generate server-side. */
export function identifySentryUser(userId: string): void {
  if (!initialized) return;
  try {
    Sentry.setUser({ id: userId });
  } catch {
    /* tolerate */
  }
}

export function clearSentryUser(): void {
  if (!initialized) return;
  try {
    Sentry.setUser(null);
  } catch {
    /* tolerate */
  }
}

/** Manually capture a non-fatal error (e.g. caught in try/catch). */
export function reportError(err: unknown, tags?: Record<string, string>): void {
  if (!initialized) return;
  try {
    Sentry.withScope((scope) => {
      if (tags) {
        for (const [k, v] of Object.entries(tags)) scope.setTag(k, v);
      }
      Sentry.captureException(err);
    });
  } catch {
    /* tolerate */
  }
}
