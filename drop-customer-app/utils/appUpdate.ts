import Constants from "expo-constants";
import { ROUTES } from "@/API/routes/ApiRoutes";
import { Alert, Linking, Platform } from "react-native";

/**
 * Check if there is a mandatory app update available.
 * Compares current app version against a minimum version from the backend.
 *
 * Call this on app mount in root _layout.tsx.
 */
export async function checkForAppUpdate() {
    try {
        const currentVersion = Constants.expoConfig?.version || "1.0.0";
        // Path comes from ROUTES, not an inline string — test_route_contract.py
        // verifies every ROUTES entry resolves on the backend.
        const res = await fetch(ROUTES.APP_VERSION, {
            method: "GET",
            headers: { "Content-Type": "application/json" },
        });

        if (!res.ok) return; // Silently skip if endpoint doesn't exist yet

        const data = await res.json();
        const minVersion = data.min_version;
        const storeUrl = Platform.OS === "ios" ? data.ios_store_url : data.android_store_url;

        if (minVersion && isVersionLower(currentVersion, minVersion)) {
            Alert.alert(
                "Update Required",
                "A new version of Drop is available. Please update to continue using the app.",
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
        // Silently fail — don't block app on version check failure.
        // The /api/app-version endpoint may not exist yet; this is expected.
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
