// In-app purchases — RevenueCat wrapper.
//
// We use RevenueCat as the abstraction layer over Google Play Billing
// and (eventually) StoreKit. RC handles:
//   - Native purchase sheet (we just call purchasePackage, RC opens it)
//   - Receipt verification with Google/Apple servers
//   - Cross-platform identity (one user across iOS + Android)
//   - Webhook delivery to our backend on every purchase event
//
// Flow at runtime:
//   1. App boots → boot() initializes the SDK with the public Android key
//   2. User logs in → identify(userId) tells RC which user this device belongs to
//   3. Paywall opens → PaywallSheet calls fetchOfferings() to get prices
//   4. User taps Subscribe → purchasePackage(planId) opens native Play sheet
//   5. Play charges card → RC validates receipt → webhook fires to our backend
//   6. Backend sets users.plan = 'pro' | 'pro_max'
//   7. /me refreshes on next call → mobile UI reflects new plan
//
// The "public" Android API key here is exactly what its name implies —
// public. RC's docs say it's safe to ship in client apps. The secret
// key (used for server-side webhook validation) lives only on our
// backend.

import Purchases, {
  CustomerInfo,
  PurchasesOffering,
  PurchasesPackage,
} from "react-native-purchases";
import { Platform } from "react-native";

// Public app-specific RC API key (Android). iOS key will be added when
// we ship the iOS build. Per RC docs these are safe to ship in source —
// they only allow purchase verification, not account modification.
const ANDROID_KEY = "goog_grPRoDOxdNewDdwLkvhrXlGoyDJ";
const IOS_KEY = ""; // TODO: add when iOS launches

let initialized = false;

/** Boot once at app launch. Idempotent — safe to call multiple times. */
export async function boot(): Promise<void> {
  if (initialized) return;
  try {
    const key = Platform.OS === "ios" ? IOS_KEY : ANDROID_KEY;
    if (!key) {
      // No key for this platform yet — silently no-op. Paywall will
      // gracefully degrade by showing no offerings.
      return;
    }
    await Purchases.configure({ apiKey: key });
    initialized = true;
  } catch (e) {
    // Don't crash the app if RC init fails — purchases just won't work.
    // Surface to console so we see it in dev.
     
    console.warn("[iap] Purchases.configure failed", e);
  }
}

/** Tell RC which user this device belongs to. Call after sign-in /
 *  on every app open if a token is already in SecureStore.
 *
 *  Passing the same user_id we use server-side ensures purchases
 *  follow the user across devices and platforms. */
export async function identify(userId: string): Promise<void> {
  if (!initialized) await boot();
  if (!initialized) return;
  try {
    await Purchases.logIn(userId);
  } catch (e) {
     
    console.warn("[iap] logIn failed", e);
  }
}

/** Sign out from RC. Used on app sign-out so the next user gets a
 *  fresh anonymous identity until they log in. */
export async function forget(): Promise<void> {
  if (!initialized) return;
  try {
    await Purchases.logOut();
  } catch (e) {
     
    console.warn("[iap] logOut failed", e);
  }
}

/** Fetch the current Offering ("default") with all packages and their
 *  localized store prices. Returns null if RC isn't configured or if
 *  there's no offering yet (e.g. Play products not approved yet). */
export async function fetchOfferings(): Promise<PurchasesOffering | null> {
  if (!initialized) await boot();
  if (!initialized) return null;
  try {
    const offerings = await Purchases.getOfferings();
    return offerings.current;
  } catch (e) {
     
    console.warn("[iap] getOfferings failed", e);
    return null;
  }
}

export type PurchaseOutcome =
  | { ok: true; entitlements: string[] }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled?: false; error: string };

/** Trigger a purchase. Opens the native Play purchase sheet. Returns
 *  ok:true with the user's active entitlement IDs if the purchase
 *  succeeded. */
export async function purchasePackage(
  pkg: PurchasesPackage,
): Promise<PurchaseOutcome> {
  if (!initialized) await boot();
  if (!initialized) return { ok: false, error: "iap_not_configured" };
  try {
    const result = await Purchases.purchasePackage(pkg);
    const active = Object.keys(result.customerInfo.entitlements.active);
    return { ok: true, entitlements: active };
  } catch (e: unknown) {
    const err = e as { userCancelled?: boolean; message?: string };
    if (err?.userCancelled) {
      return { ok: false, cancelled: true };
    }
    return { ok: false, error: err?.message || "purchase_failed" };
  }
}

/** Restore purchases — required for App Store compliance. Looks up
 *  whatever the user already owns under their Apple/Google ID and
 *  reapplies entitlements. Useful when reinstalling on a new device. */
export async function restorePurchases(): Promise<CustomerInfo | null> {
  if (!initialized) await boot();
  if (!initialized) return null;
  try {
    return await Purchases.restorePurchases();
  } catch (e) {
     
    console.warn("[iap] restorePurchases failed", e);
    return null;
  }
}

/** Look up RC's snapshot of the current user without triggering a
 *  purchase. Useful for the initial paywall render to know if the user
 *  is already subscribed. */
export async function getCustomerInfo(): Promise<CustomerInfo | null> {
  if (!initialized) await boot();
  if (!initialized) return null;
  try {
    return await Purchases.getCustomerInfo();
  } catch {
    return null;
  }
}
