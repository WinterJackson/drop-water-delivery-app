import Constants from "expo-constants";
import { Alert, Linking, Platform } from "react-native";

import { apiFetch } from "@/API/apiFetch";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";

/** What `GET /api/app-version` returns, per app. */
interface AppVersionResponse {
    min_version?: string;
    android_store_url?: string;
    ios_store_url?: string | null;
}

/**
 * Block the app when the build is too old to be trusted on this platform.
 *
 * The customer app has had this since launch; the vendor app did not, which had it
 * exactly backwards. A customer on a stale build sees wrong prices. A vendor on a
 * stale build is mid-trading, accepting orders it may price or dispatch wrongly — and is the person least able to
 * notice, because they are working rather than browsing an app store.
 *
 * `Alert`, not `Toast`, and `cancelable: false`: this is the one prompt in the
 * app that must not be dismissible. Everything else uses the themed `Popup`.
 *
 * Failure is silent by design. A version check is advisory, and the platform must
 * not become unusable because the check for whether it is usable did not answer.
 *
 * Called once from the root layout.
 */
export async function checkForAppUpdate() {
    try {
        const currentVersion = Constants.expoConfig?.version || "1.0.0";
        // Unauthenticated: this runs before there is a session, and a build too
        // old to sign in still has to be told. `apiFetch` is used anyway for the
        // connection-aware timeout — a check that never resolves is one that
        // runs on every cold start and never once completes.
        const data = await apiFetch<AppVersionResponse>(VendorApiRoutes.AppVersion.path, {
            kind: "read",
        });

        const minVersion = data.min_version;
        const storeUrl = Platform.OS === "ios" ? data.ios_store_url : data.android_store_url;

        if (minVersion && isVersionLower(currentVersion, minVersion)) {
            Alert.alert(
                "Update Required",
                "A new version of Drop Vendor is available. Please update to continue.",
                [
                    {
                        text: "Update Now",
                        onPress: () => {
                            if (storeUrl) Linking.openURL(storeUrl);
                        },
                    },
                ],
                { cancelable: false }
            );
        }
    } catch (_) {
        // Silently fail. See above.
    }
}

/**
 * Compare semantic versions. Returns true if current < required.
 */
function isVersionLower(current: string, required: string): boolean {
    const currentParts = current.split(".").map(Number);
    const requiredParts = required.split(".").map(Number);
    for (let i = 0; i < 3; i++) {
        const c = currentParts[i] || 0;
        const r = requiredParts[i] || 0;
        if (c < r) return true;
        if (c > r) return false;
    }
    return false;
}
