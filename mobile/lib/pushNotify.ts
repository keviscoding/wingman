// Push notification on generation completion.
//
// CURRENTLY DISABLED in the dev-client APK because expo-notifications
// eagerly probes for native modules (ExpoPushTokenManager) at require()
// time and throws even when wrapped in try/catch — LogBox catches it
// before our handler does, and the user sees an "Uncaught Error" dev
// overlay.
//
// To re-enable: rebuild the dev client (or production build) with
// expo-notifications properly linked, then flip ENABLED to true.
//
//   cd mobile && eas build --platform android --profile development
//
// In the meantime the dock chip is the canonical "ready" indicator —
// good enough for foregrounded usage which is 95% of the flow.

const ENABLED = false;

export async function firePushReady(_contactName: string) {
  if (!ENABLED) return;
  // Lazy-load only when enabled. Production build path:
  //
  //   try {
  //     const notif = require("expo-notifications");
  //     notif.setNotificationHandler({...});
  //     await notif.scheduleNotificationAsync({...});
  //   } catch { /* silent */ }
}
