#!/usr/bin/env node
/**
 * Pre-build configuration check.
 *
 * `app.config.js` only *warns* when the Maps keys or `google-services.json` are
 * missing, because failing there would break `expo start` for anyone who has
 * not been handed the credentials. That is the right call for development and
 * the wrong one for a release build: both failures are invisible at runtime.
 *
 *   - No Maps key  -> the map renders as a blank grey grid. No error, no log.
 *   - No google-services.json -> `expo-notifications` never obtains an FCM
 *     token on Android, so push silently never arrives. Expo Go is unaffected,
 *     which is exactly why this survives testing and ships broken.
 *
 * So the check lives here instead, and only release builds run it. Exits
 * non-zero with the specific fix for whatever is missing.
 *
 *   node scripts/preflight.js            # warn only
 *   node scripts/preflight.js --strict   # exit 1 on any problem (CI / release)
 */
const fs = require("fs");
const path = require("path");

const APP_ROOT = path.join(__dirname, "..");
const PACKAGE = "com.drop.rider";
const strict = process.argv.includes("--strict");

const problems = [];
const notes = [];

// ── .env, if present ──────────────────────────────────────────────────────
// EAS injects real secrets as environment variables, so a missing .env during
// a cloud build is normal. Locally it is how the keys arrive.
const envPath = path.join(APP_ROOT, ".env");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
    const match = /^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)$/.exec(line);
    if (match && !process.env[match[1]]) {
      process.env[match[1]] = match[2].trim().replace(/^["']|["']$/g, "");
    }
  }
}

// ── Google Maps native SDK keys ───────────────────────────────────────────
for (const key of ["GOOGLE_MAPS_ANDROID_API_KEY", "GOOGLE_MAPS_IOS_API_KEY"]) {
  const value = (process.env[key] || "").trim();
  if (!value) {
    problems.push(
      `${key} is not set.\n` +
        `    The map will render as a blank grey grid in a native build, with no error.\n` +
        `    Create it in Google Cloud Console > Credentials, restrict it to\n` +
        `    "Maps SDK for ${key.includes("ANDROID") ? "Android" : "iOS"}" and to ${PACKAGE},\n` +
        `    then set it in .env (local) or as an EAS secret (builds).`
    );
  } else if (!value.startsWith("AIza")) {
    problems.push(`${key} does not look like a Google API key (expected it to start with "AIza").`);
  }
}

if (
  process.env.GOOGLE_MAPS_ANDROID_API_KEY &&
  process.env.GOOGLE_MAPS_ANDROID_API_KEY === process.env.GOOGLE_MAPS_IOS_API_KEY
) {
  problems.push(
    "GOOGLE_MAPS_ANDROID_API_KEY and GOOGLE_MAPS_IOS_API_KEY are the same key.\n" +
      "    A Google key carries exactly one application restriction — Android apps\n" +
      "    OR iOS apps, never both. One shared key therefore cannot be restricted at\n" +
      "    all, which is how the previous key ended up exposed. Use two keys."
  );
}

// ── Firebase config for Android push ──────────────────────────────────────
const gsPath = process.env.GOOGLE_SERVICES_JSON || path.join(APP_ROOT, "google-services.json");
if (!fs.existsSync(gsPath)) {
  problems.push(
    "google-services.json not found.\n" +
      "    Android push will silently never arrive in a standalone build — no error,\n" +
      "    no notification. Expo Go is unaffected because it uses Expo's own\n" +
      "    Firebase project, so this cannot be caught by testing in Expo Go.\n" +
      `    Firebase Console > Add app > Android, package "${PACKAGE}", download the\n` +
      "    file to this directory. See docs/push-notifications.md."
  );
} else {
  // A file from another project or another package is accepted by the build and
  // rejected by Firebase at runtime, which is the worst of both worlds.
  try {
    const gs = JSON.parse(fs.readFileSync(gsPath, "utf8"));
    const packages = (gs.client || [])
      .map((c) => c.client_info && c.client_info.android_client_info && c.client_info.android_client_info.package_name)
      .filter(Boolean);
    if (!packages.includes(PACKAGE)) {
      problems.push(
        `google-services.json is for ${packages.join(", ") || "an unknown package"}, not ${PACKAGE}.\n` +
          "    Firebase matches on package name and rejects a mismatch outright, so\n" +
          "    push would fail silently. Regenerate it for the correct package."
      );
    }
  } catch (e) {
    problems.push(`google-services.json is not valid JSON: ${e.message}`);
  }
}

// ── Runtime configuration ─────────────────────────────────────────────────
const backend = (process.env.EXPO_PUBLIC_BACKEND_BASE_URL || "").trim();
if (!backend) {
  problems.push("EXPO_PUBLIC_BACKEND_BASE_URL is not set — every request will fail.");
} else if (strict && !backend.startsWith("https://")) {
  problems.push(
    `EXPO_PUBLIC_BACKEND_BASE_URL is "${backend}".\n` +
      "    A release build must not point at a local or plaintext host."
  );
}

const clerk = (process.env.EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY || "").trim();
if (!clerk) {
  problems.push("EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY is not set — nobody can sign in.");
} else if (strict && clerk.startsWith("pk_test_")) {
  // A note, not a blocker. `production` here also builds the internal-testing
  // APKs, and a Clerk *production* instance needs a verified domain — so
  // failing the build would stop legitimate work to enforce something that is
  // only wrong at public release.
  //
  // It must become a blocker before shipping to the Play Store: a dev instance
  // carries different session limits and rate limits, and its users are a
  // separate population from production's.
  notes.push(
    "EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY is a Clerk *test* instance (pk_test_…).\n" +
      "    Fine for internal builds. Switch to pk_live_… before any public release."
  );
}

if (!(process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER || "").trim()) {
  notes.push(
    "EXPO_PUBLIC_SMS_GATEWAY_NUMBER is not set — the \"No Data? SMS to Complete\"\n" +
      "    button will compose a message to the +254700000000 placeholder, so the\n" +
      "    offline delivery fallback does not work."
  );
}

// ── Report ────────────────────────────────────────────────────────────────
const label = "[preflight] drop-rider-app";

for (const note of notes) console.warn(`${label} note: ${note}`);

if (problems.length === 0) {
  console.log(`${label}: configuration OK`);
  process.exit(0);
}

console.error(`\n${label}: ${problems.length} problem(s) found\n`);
problems.forEach((p, i) => console.error(`  ${i + 1}. ${p}\n`));

if (strict) {
  console.error("Refusing to build. Fix the above, or run without --strict to bypass.\n");
  process.exit(1);
}
console.error("Continuing anyway (not --strict).\n");
process.exit(0);
