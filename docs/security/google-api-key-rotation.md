# Rotating and restricting the Google API key

**Status:** the repo-side work is done (see §3). Steps 1, 2 and 4 have to be done
by you — they happen in Google Cloud Console, in EAS, and in git history.

The leaked key is `AIzaSyD9R6-hmSRZwjEuWj_8CPRzZipXtJ6MMAI`. It was committed in
three places: `drop-customer-app/google-services.json.bak`, `app.json` (twice), and
`eas.json`. It is **unrestricted**, so anyone who pulls the repo — or reads the
commit history, or unzips the shipped APK — can bill Maps requests to your project.

Treat it as compromised. Restricting it is not enough; it must be rotated.

> ### ⚠️ The same key is also hardcoded in the rider and vendor apps
>
> `git grep -n AIza` also hits `drop-rider-app/app.json`, `drop-rider-app/eas.json`,
> `drop-vendor-app/app.json`, `drop-vendor-app/eas.json`. Those apps are outside the
> scope you authorised, so they were **not** modified.
>
> **Consequence: deleting the old key (step 4) breaks maps in the rider and vendor
> apps.** Either give me the go-ahead to apply the same `app.config.js` treatment
> there — each app needs its own pair of keys, restricted to its own package/bundle
> id (`com.drop.rider`, `com.drop.vendor`) — or do it by hand before step 4. Five
> keys total: android+ios × three apps, minus whichever platforms you do not ship.

---

## 1. Create two new, restricted keys

A Google Cloud API key can carry **one** application restriction: *either* "Android
apps" *or* "iOS apps", never both. The old key was shared by both platforms, which
is precisely why it could not be restricted. You need two keys.

Go to **Google Cloud Console → APIs & Services → Credentials**
(<https://console.cloud.google.com/apis/credentials>), select the project that owns
the current key.

### 1a. Android key

**Enable the API first.** The "API restrictions" dropdown only lists APIs already
enabled in the project — if "Maps SDK for Android" is missing from it, that is why:
<https://console.cloud.google.com/apis/library/maps-android-backend.googleapis.com>

1. **+ Create credentials → API key**. Name it `drop-customer-android-maps`.
   Leave *"Authenticate API calls through a service account"* **off** — that is for
   Vertex/Gemini, not the Maps SDKs.
2. **Application restrictions → Android apps → Add an item**:
   - **Package name:** `com.drop.customer` — this is `expo.android.package` in
     `app.json`. It must match exactly; a mismatch returns `REQUEST_DENIED` and the
     map renders grey.
   - **SHA-1 certificate fingerprint:** this project is on the **managed** workflow
     (no `android/` directory), so EAS holds the keystore — there is no local
     `~/.android/debug.keystore` to read. Get the fingerprint from either:

     ```bash
     cd drop-customer-app
     npx eas-cli login
     npx eas-cli credentials -p android
     # → build profile → "Keystore: Manage everything..." → SHA-1 Fingerprint
     ```

     …or the dashboard, which shows it as copyable text:
     <https://expo.dev/accounts/wj-kuzzi/projects/drop/credentials>

     No keystore yet? `npx eas-cli build -p android --profile preview` generates one
     on the first build.

     EAS uses **one keystore per project** unless `eas.json` sets per-profile
     credentials — this one does not, so a single SHA-1 covers development, preview
     and production. A SHA-1 comes from a public certificate; it is not a secret.

     The `12:34:...` string prefilled in that field is Google's placeholder example.
     Replace it entirely.
3. **API restrictions → Restrict key →** select **Maps SDK for Android** only.
4. Save. Copy the key.

**Add a second Android entry** (same package, different SHA-1) only if you later:
- run `npx expo prebuild` and build locally with Gradle — that finally creates
  `~/.android/debug.keystore`, readable with
  `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android -keypass android | grep SHA1`; or
- ship via **Play App Signing**, which re-signs the app. Play Console → Release →
  Setup → App signing shows the SHA-1 the released app actually presents; add it
  alongside the upload key's.

Expo Go needs no key — it renders maps with Expo's own.

### 1b. iOS key

Enable <https://console.cloud.google.com/apis/library/maps-ios-backend.googleapis.com>
first, for the same reason.

1. **+ Create credentials → API key**. Name it `drop-customer-ios-maps`.
2. **Application restrictions → iOS apps → Add**: bundle ID `com.drop.customer`
   (`expo.ios.bundleIdentifier`). No fingerprint — the bundle ID is the whole
   restriction.
3. **API restrictions → Restrict key →** select **Maps SDK for iOS** only.
4. Save. Copy the key.

> **Neither key needs Places, Geocoding, or Directions enabled — keep them
> Maps-SDK-only.** Address search *does* now use Google Places, but through the
> backend proxy (`/api/maps/places/*`), not from the app: a key callable from
> JavaScript cannot be package-restricted, so it would be extractable from the
> APK and billable by anyone who found it.
>
> Those web services run on the separate, IP-restricted
> `GOOGLE_MAPS_SERVER_API_KEY`, which needs **Places API** and **Directions API**
> enabled. That key never leaves the server. See `docs/maps-architecture.md`.

### 1c. Fill-in sheet — all six keys

Values below are read from each app's resolved Expo config, not guessed. Enable the
two APIs first (§1a) or the restrictions dropdown will be empty. On every key, leave
*"Authenticate API calls through a service account"* **off**.

**Android — Application restrictions → Android apps**

> ⚠️ **These fingerprints are stale as of 2026-07-31.** They were read from the
> `l-bonez` account, and the three projects have since been relinked to
> `wj-kuzzi` (`@wj-kuzzi/drop`, `/drop-rider`, `/drop-vendor`).
>
> **EAS keeps a separate keystore per project**, so the `wj-kuzzi` copies sign
> with different certificates and therefore have different SHA-1s. An Android
> Maps key restricted to the old fingerprints will **reject** requests from a
> build made under the new account — the map renders blank with no error in the
> app, which is precisely the failure mode this document exists to prevent.
>
> All three fingerprints have been re-read from `wj-kuzzi` and the table below is
> current. **The Google Cloud key restrictions still need updating** — that is the
> remaining action.
>
> To re-read them at any time (no build required; the keystores already exist):
>
> ```bash
> cd drop-customer-app && npx eas-cli@latest credentials -p android
> # → production → the Keystore block prints SHA1 Fingerprint before the menu
> ```

Fingerprints read from EAS on 2026-07-30 (`npx eas-cli credentials -p android` →
`production` → Keystore, as `l-bonez`). Each keystore was created ~2026-06 and is the
one existing builds are signed with. A SHA-1 is derived from a public certificate —
not a secret.

**Current — `wj-kuzzi` keystores.** These are what builds present today. Put
these in the Google Cloud key restrictions.

Read from EAS on 2026-07-31, as `wj-kuzzi`, `production` profile. Each keystore
was created ~2026-06 under that account.

| # | Name | Package name | SHA-1 | API restriction |
|---|---|---|---|---|
| 1 | `drop-customer-android-maps` | `com.drop.customer` | `80:AE:FC:87:54:09:0A:2E:80:4C:CA:6E:8F:98:EA:34:DE:07:47:0B` | Maps SDK for Android |
| 2 | `drop-rider-android-maps` | `com.drop.rider` | `80:C6:60:E4:4E:22:32:B4:90:7D:A7:46:51:C1:7B:8F:78:6E:1A:7C` | Maps SDK for Android |
| 3 | `drop-vendor-android-maps` | `com.drop.vendor` | `ED:8A:17:76:D2:32:23:BB:1F:1F:AF:DA:94:2F:B2:13:CE:51:EF:1A` | Maps SDK for Android |

The three are genuinely distinct — EAS generates a keystore per project. Pasting
one app's fingerprint against another's package is the likeliest mistake here,
and it fails silently: the map renders blank, with no client-side error.

**Superseded — `l-bonez` keystores.** Kept only to show the two do not match, so
nobody assumes a fingerprint survives an account move. Do **not** restrict keys
to these; a build under `wj-kuzzi` presenting one of the rows above would be
refused, and the map would render blank with no client-side error.

| Package name | Old SHA-1 (`l-bonez`) |
|---|---|
| `com.drop.customer` | `EE:48:82:83:5F:34:94:A5:99:A4:DB:59:DC:CC:11:EA:49:22:E2:D7` |
| `com.drop.rider` | `17:03:E5:D4:B2:0C:48:B8:AE:86:C7:01:A9:5C:78:50:A2:D2:DC:DE` |
| `com.drop.vendor` | `CE:35:27:44:23:F3:87:16:F0:E7:19:3A:EE:1A:02:F0:46:F4:71:00` |

Keeping both fingerprints on a key also works, and is worth doing while the
`l-bonez` projects still exist as a rollback. Drop the old rows once those
projects are deleted.

Re-read them if a keystore is ever regenerated (`Set up a new keystore` in that same
menu) — the fingerprint changes and every Maps request starts failing with a grey map
and no client-side error.

**iOS — Application restrictions → iOS apps** (no fingerprint; bundle ID is the whole
restriction). All three `eas.json` production profiles currently build `apk`, so
these are only needed once you ship iOS.

| # | Name | Bundle ID | API restriction |
|---|---|---|---|
| 4 | `drop-customer-ios-maps` | `com.drop.customer` | Maps SDK for iOS |
| 5 | `drop-rider-ios-maps` | `com.drop.rider` | Maps SDK for iOS |
| 6 | `drop-vendor-ios-maps` | `com.drop.vendor` | Maps SDK for iOS |

Six keys, not two: the package name / bundle ID is *part of* the restriction, so one
key cannot serve three different applications. Select exactly one API per key —
"Don't restrict key" is the state the leaked key is in today.

**Destinations.** Only the customer app can consume these yet; it is the only one
with an `app.config.js`. Keys 2, 3, 5 and 6 have nowhere to go until the rider and
vendor apps get the same treatment — both still carry the leaked key verbatim in
`app.json` and `eas.json`.

## 2. Install the new keys

**Locally** — in `drop-customer-app/.env` (already gitignored):

```
GOOGLE_MAPS_ANDROID_API_KEY=<new android key>
GOOGLE_MAPS_IOS_API_KEY=<new ios key>
```

Then delete the now-unused `EXPO_PUBLIC_GOOGLE_MAPS_API_KEY` line.

**For EAS builds** — as secrets, so they never enter the repo:

```bash
cd drop-customer-app
eas secret:create --scope project --name GOOGLE_MAPS_ANDROID_API_KEY --value "<new android key>"
eas secret:create --scope project --name GOOGLE_MAPS_IOS_API_KEY     --value "<new ios key>"
eas secret:list
```

`app.config.js` reads both at build time and writes them into `AndroidManifest.xml`
and `Info.plist`. Nothing is inlined into the JS bundle.

Verify before shipping:

```bash
cd drop-customer-app
npx expo config --type prebuild --json | python3 -c \
  "import json,sys;c=json.load(sys.stdin);print(c['android']['config'],c['ios']['config'])"
```

Use `--type prebuild` (what the native build consumes), **not** `--type public`:
Expo scrubs the Maps keys out of the public manifest, so `--type public` shows
nothing even when the keys are correctly wired. That scrubbing is also why the app
can no longer read the key back at runtime through `Constants.expoConfig` — the two
screens that tried to were reading `undefined` and have been cleaned up.

If both variables are missing, `app.config.js` prints a warning and emits no key
rather than silently shipping a broken map.

## 3. Already done in the repo

| Change | File |
|---|---|
| Hardcoded key removed from both platform blocks | `drop-customer-app/app.json` |
| Hardcoded key removed from the production build profile | `drop-customer-app/eas.json` |
| Per-platform keys injected from env at build time | `drop-customer-app/app.config.js` *(new)* |
| Dead `GOOGLE_MAPS_API_KEY` constants deleted (neither screen used the value) | `app/(screens)/Map/[id].tsx`, `app/(screens)/LocationSearch.tsx` |
| `apiKey` on the autocomplete marked optional + documented as not for the SDK key | `components/map/PlacesAutocomplete.tsx` |
| `google-services.json.bak` untracked; `*.bak`, `google-services.json`, `GoogleService-Info.plist` ignored | `.gitignore` |

After step 2 the working tree contains no Google key at all.

## 4. Delete the old key, then purge it from history

**Order matters.** Ship or at least build with the new keys first, confirm maps
render, *then*:

1. Console → Credentials → the old key → **Delete**. (If you are nervous, first set
   its application restriction to an IP that does not exist and watch for errors for
   a day — deletion is instant and irreversible.)
2. Check **APIs & Services → Metrics** for unexpected usage before deletion; that
   tells you whether it was actually abused.
3. Set a **budget alert** on the project (Billing → Budgets & alerts) — the standard
   protection against a key leak becoming a bill.

### Purging git history

The key stays in `229fcb4` and later commits until history is rewritten. This is
**your call** — it rewrites every commit SHA and forces everyone to re-clone.

Rotating (step 4.1) makes the leaked value worthless, so a rewrite is optional
hygiene rather than a fix. If you want it:

```bash
# from the repo root, on a clean tree, with a backup
git clone --mirror . ../drop-backup.git          # backup first

pipx install git-filter-repo                     # or: pip install git-filter-repo
cat > /tmp/keys.txt <<'EOF'
AIzaSyD9R6-hmSRZwjEuWj_8CPRzZipXtJ6MMAI==>REDACTED_GOOGLE_API_KEY
EOF
git filter-repo --replace-text /tmp/keys.txt

git remote add origin <your remote url>          # filter-repo drops remotes
git push --force --all
git push --force --tags
```

Every collaborator must then re-clone (a `git pull` on rewritten history creates a
tangle). If the repo is private and only you have it, this is cheap. If it is public
or has forks, assume the value is permanently out there — which is why step 4.1,
not the rewrite, is the actual remedy.

## 5. Sanity checklist

- [ ] Two new keys exist, each with one application restriction and one API restriction
- [ ] Old key deleted in the Console
- [ ] `.env` has the two new vars; `EXPO_PUBLIC_GOOGLE_MAPS_API_KEY` deleted
- [ ] EAS secrets created; `eas secret:list` shows both
- [ ] `git grep -n AIza` returns nothing in the working tree
- [ ] Budget alert configured
- [ ] (Optional) history rewritten and force-pushed
