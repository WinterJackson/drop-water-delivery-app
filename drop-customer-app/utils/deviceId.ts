import * as SecureStore from "expo-secure-store";
import * as Device from "expo-device";
import { Platform } from "react-native";

/**
 * A stable identifier for this handset, sent once at registration.
 *
 * The backend gates the first-order welcome discount on it: 30% of a KSH 300
 * deposit, taken entirely out of platform margin, and an account costs nothing
 * to create. `pricing_service.welcome_offer_available` refuses the offer when
 * another account on the same handset has already taken it.
 *
 * That check had never fired. Three separate reasons, and all three had to be
 * fixed for any of them to matter:
 *
 * 1. `Users.device_id` was `UNIQUE`, so two accounts could never share a value
 *    and the "has another account used this device?" query could not return a
 *    row under any circumstances.
 * 2. A null was treated as eligible.
 * 3. **No app ever sent the field.** Every account had a null.
 *
 * ## What this is and is not
 *
 * It is a deterrent, not a proof of identity. A determined attacker can factory
 * reset, use a second handset, or run an emulator. It stops the cheap attack —
 * uninstall, reinstall, claim again — which is the one that actually happens at
 * volume. Anything stronger means device attestation, which is a much larger
 * piece of work and is not warranted by a KSH 90 discount.
 *
 * ## Why it is stored rather than derived
 *
 * The value is minted once and kept in the keychain/keystore, which survives an
 * ordinary uninstall-and-reinstall on both platforms. `expo-application` would
 * give a platform-vendor id as well, but it is not a dependency of this app and
 * adding a native module for a deterrent is not a trade worth making — the
 * stored value covers the attack that actually happens.
 *
 * SecureStore is deliberate: `AsyncStorage` is cleared by "clear app data",
 * which is a two-tap reset on Android.
 */
const STORAGE_KEY = "drop.device_id.v1";

/** Cheap in-memory memo — this is read on a hot path at sign-up. */
let cached: string | null = null;

function randomId(): string {
  // Not cryptographic. It only has to be unlikely to collide across handsets.
  return `rnd_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * The device fingerprint, creating and persisting one on first call.
 *
 * Never throws. A signup must not fail because the keystore was unavailable —
 * the offer being wrongly granted is a KSH 90 problem, a blocked registration
 * is a lost customer.
 */
export async function getDeviceId(): Promise<string> {
  if (cached) return cached;

  try {
    const stored = await SecureStore.getItemAsync(STORAGE_KEY);
    if (stored) {
      cached = stored;
      return stored;
    }
  } catch {
    // Fall through and mint a fresh one.
  }

  const model = Device.modelName ? Device.modelName.replace(/\s+/g, "-") : "unknown";
  const id = `${Platform.OS}_${model}_${randomId()}`;

  try {
    await SecureStore.setItemAsync(STORAGE_KEY, id);
  } catch {
    // Unstored means it will differ next launch. Still better than null, which
    // is what every account carried before this existed.
  }

  cached = id;
  return id;
}
