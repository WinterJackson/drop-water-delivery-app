+-# Push notifications

## How a push reaches a device

```
order event ──▶ queue_push(session)         in-app Notification row written
                     │                       (always — the history survives
                     │                        even when the push is muted)
                 commit
                     │
              after_commit hook
                     ▼
            send_push_message ──▶ ARQ ──▶ Expo ──▶ APNs / FCM ──▶ device
                                            │
                                        ticket id
                                            ▼
                                   Redis (due in 15 min)
                                            ▼
                              check-push-receipts (cron-job.org)
                                            ▼
                                 purge DeviceNotRegistered tokens
```

Two properties matter and are easy to lose:

- The push is dispatched **after** the transaction commits. It used to fire
  several statements earlier, so a rolled-back order still told the customer it
  was confirmed. See the Notifications section of `BackendAPI/CLAUDE.md`.
- The in-app row is written regardless of preferences; only the push is muted.
  Muting "Promotions" must not lose the record.

## Android needs `google-services.json`

Expo's push service hands FCM v1 the actual delivery on Android, so a
**standalone build** needs a Firebase config for that exact package. Firebase
matches on package name — a file from another project, or from an older package
name, is rejected outright and `expo-notifications` simply never obtains a token.
Push then fails silently: no error, no notification.

Expo Go is unaffected, because it uses Expo's own Firebase project. That is why
this can look fine in development and be completely broken in production.

| App | Package / bundle |
|---|---|
| drop-customer-app | `com.drop.customer` |
| drop-rider-app | `com.drop.rider` |
| drop-vendor-app | `com.drop.vendor` |

### Getting the file

Once per app:

1. [Firebase console](https://console.firebase.google.com) → your project →
   **Add app** → Android.
2. Enter the package name from the table above, exactly.
3. Download `google-services.json`.
4. Put it at the app's root, e.g. `drop-customer-app/google-services.json`.

`app.config.js` picks it up automatically when present, and warns when it is not.
Nothing breaks without it — `expo start` and `expo prebuild` still work — so a
teammate without the file is not blocked.

The file is gitignored: it carries a project API key. For builds, upload it as an
EAS file variable instead — **already done for all three apps**:

```bash
cd drop-customer-app
eas env:set --name GOOGLE_SERVICES_JSON --type file \
  --value ./google-services.json --scope project --visibility secret \
  --environment production --environment preview --environment development
```

`eas secret:create` is deprecated in favour of `eas env:set`; `eas secret:list`
now redirects to `eas env:list`. Verify with `eas env:list production` — a
`secret` variable reads back as `*****`, which is correct, not an error.

`app.config.js` reads `GOOGLE_SERVICES_JSON` first, which is the path EAS
materialises the file at during a build, and falls back to the local file.

### One file, three apps

Firebase regenerates `google-services.json` with **every** Android app in the
project, so successive downloads are cumulative snapshots — the file downloaded
after registering the third app contains all three. All three apps therefore
ship the same file; the FCM plugin selects the matching `client` entry by
package name at build time.

That is deliberate: one artefact to regenerate when the project changes, and no
way to end up with two apps holding different vintages of the same config. The
alternative — hand-trimming each app to its own entry — drifts the moment
anybody downloads a fresh copy from the console.

### FCM v1 credentials on EAS

The config file is only half of it. EAS also needs the FCM v1 **service account
key** to talk to Firebase on your behalf:

1. Firebase console → Project settings → **Service accounts** → *Generate new
   private key*.
2. `eas credentials` → Android → *Push Notifications: FCM V1* → upload it.

Repeat per EAS project. Without this, Android push fails in standalone builds
even with a correct `google-services.json`.

### iOS

Nothing to configure by hand. `eas credentials` provisions the APNs key on first
build. `google-services.json` is Android-only.

## Verifying

```bash
# 1. Does the config reference the file?
cd drop-customer-app && npx expo config --type prebuild --json | grep googleServicesFile

# 2. Does the device get a token? (physical device, standalone build — not Expo Go)
#    usePushNotifications logs it in __DEV__.

# 3. Did the backend store it?
#    SELECT push_token FROM "Users" WHERE clerk_id = '<id>';

# 4. Did Expo accept the send? Check the API logs for the ticket, then wait for
#    check-push-receipts to resolve it — see docs/cron-jobs.md.
```

## A note on the file that used to be here

`drop-customer-app/google-services.json.bak` was a leftover from an earlier
project identity. It declared package `com.mohol.DROP`, but the app is
`com.drop.customer`, so Firebase would have rejected it; nothing referenced it;
and it sat in the working tree holding a live API key. It has been removed rather
than repaired — regenerate from the Firebase console using the steps above.

## Preflight: catching missing config before a build

Both failures this document describes are invisible at runtime. A missing
`google-services.json` produces no error and no notification; a missing Maps key
renders a blank grey grid. Neither shows up in Expo Go.

`app.config.js` only warns, deliberately — failing there would break `expo start`
for anyone without the credentials. The hard check lives in `scripts/preflight.js`
in each app instead:

```bash
cd drop-rider-app
pnpm preflight           # report problems, exit 0
pnpm preflight:strict    # exit 1 on any problem
```

It verifies, per app:

- both Maps keys are set, look like Google keys, and are **not the same key**
  (one Google key carries one application restriction — Android *or* iOS, never
  both, so a shared key cannot be restricted at all);
- `google-services.json` exists, parses, **and declares this app's package** — a
  file from another project is accepted by the build and rejected by Firebase at
  runtime, which is the worst case;
- `EXPO_PUBLIC_BACKEND_BASE_URL` and `EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY` are set,
  and under `--strict` that the backend is `https://` and the Clerk key is not a
  `pk_test_` key.

`package.json` wires `eas-build-pre-install` to the strict form, so **every EAS
build runs it** and fails early rather than shipping a silently broken binary.

### Current state

All three apps report `configuration OK`. Firebase project **`vepo-001`**
(project number `628446900014`) holds all three Android apps, the config file is
in each app root, and `GOOGLE_SERVICES_JSON` is uploaded to all three EAS
projects.

The one remaining step is the **FCM v1 service-account key**, which
`eas credentials` only accepts interactively — see below.

## The FCM v1 service-account key

`google-services.json` tells the *app* which Firebase project it belongs to. It
does not let Expo's servers **send** anything. That needs a service-account key,
uploaded once per EAS project:

```bash
cd drop-rider-app
eas credentials -p android
# → build profile → Push Notifications: FCM V1 → upload the .json
```

There is no non-interactive form: `eas credentials` accepts only `--platform`.

This key is a **server credential with broad access to the Firebase project** —
unlike `google-services.json`, which is client config designed to ship inside an
APK. Do not commit it, do not put it in an app directory, and do not paste it
anywhere it will be retained. Store it in a password manager and delete the
download afterwards. If it leaks, revoke it in Google Cloud Console → IAM &
Admin → Service Accounts → Keys, and generate a new one.

The same key works for all three apps because they share one Firebase project.

Without it, Android push fails in standalone builds **even with a correct
`google-services.json`** — the app obtains a token and the send is rejected.
