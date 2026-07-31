/**
 * Dynamic Expo config.
 *
 * `app.json` holds everything static. The Google Maps keys are injected here
 * from the environment so that:
 *
 *   1. No key is committed to the repository.
 *   2. Android and iOS get *separate* keys. A Google Cloud API key can carry
 *      exactly one application restriction — either "Android apps" (package +
 *      SHA-1) or "iOS apps" (bundle ID), never both. One shared key therefore
 *      cannot be restricted at all, which is how the previous key ended up
 *      unrestricted and exposed.
 *
 * Set these in `.env` locally and as EAS secrets for builds (they are
 * deliberately *not* `EXPO_PUBLIC_*`: they are consumed at build time and
 * written into AndroidManifest.xml / Info.plist for the native Maps SDK, and
 * must not be inlined into the JS bundle).
 *
 *   GOOGLE_MAPS_ANDROID_API_KEY   restricted to com.drop.vendor + release/debug SHA-1
 *                                 API restriction: "Maps SDK for Android"
 *   GOOGLE_MAPS_IOS_API_KEY       restricted to bundle id com.drop.vendor
 *                                 API restriction: "Maps SDK for iOS"
 *
 * See docs/security/google-api-key-rotation.md.
 */

const androidKey = process.env.GOOGLE_MAPS_ANDROID_API_KEY ?? "";
const iosKey = process.env.GOOGLE_MAPS_IOS_API_KEY ?? "";

const fs = require("fs");
const path = require("path");

/**
 * Firebase config for Android push.
 *
 * Expo's push service hands FCM v1 the delivery, so a standalone Android build
 * needs `google-services.json` for THIS package — Firebase matches on package
 * name, and a file from another project or another package is rejected outright.
 * Without it, `expo-notifications` gets no token in a production build and push
 * silently never arrives (Expo Go is unaffected: it uses Expo's own project).
 *
 * Referenced only when the file is actually present, so `expo prebuild` and
 * `expo start` still work on a machine that has not been given one. The file is
 * gitignored: it carries a project API key and belongs in EAS, not in git.
 *
 *   eas secret:create --scope project --name GOOGLE_SERVICES_JSON \
 *     --type file --value ./google-services.json
 *
 * See docs/push-notifications.md.
 */
const googleServicesFile = (() => {
  const fromEnv = process.env.GOOGLE_SERVICES_JSON;
  const candidates = [fromEnv, path.join(__dirname, "google-services.json")].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate));
})();


module.exports = ({ config }) => {
  // Expo Go renders maps with its own key, so a missing key is only a problem
  // for a native build. Warn rather than fail so `expo start` still works.
  if (!androidKey || !iosKey) {
    console.warn(
      "[app.config] GOOGLE_MAPS_ANDROID_API_KEY / GOOGLE_MAPS_IOS_API_KEY not set — " +
        "native builds will ship without a Maps key and the map will render blank."
    );
  }

  if (!googleServicesFile) {
    console.warn(
      "[app.config] google-services.json not found — Android push notifications " +
        "will not work in a standalone build. See docs/push-notifications.md."
    );
  }

  return {
    ...config,
    android: {
      ...config.android,
      ...(googleServicesFile ? { googleServicesFile } : {}),
      ...(androidKey
        ? { config: { ...config.android?.config, googleMaps: { apiKey: androidKey } } }
        : {}),
    },
    ios: {
      ...config.ios,
      ...(iosKey
        ? { config: { ...config.ios?.config, googleMapsApiKey: iosKey } }
        : {}),
    },
  };
};
