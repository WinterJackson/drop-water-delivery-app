import React, { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import { Text } from '@/components/ui/Text';
// @ts-ignore
import NetInfo from "@react-native-community/netinfo";

/**
 * Network connectivity banner component.
 * Uses @react-native-community/netinfo for reliable native offline detection.
 */
/**
 * Offline only on a *definitive* answer — see the customer app's copy for the
 * full account. `isInternetReachable` is tri-state and `null` means "the probe
 * has not come back yet", which is a question rather than a result. The old
 * expression `!!x !== false` looks like it tolerates `null` and does not: `!!`
 * binds tighter than `!==`, so it collapses to `!!x` and `!!null` is `false`.
 * The banner therefore fired on every cold start while the probe was in flight,
 * and permanently wherever NetInfo's probe endpoint is unreachable while this
 * API is fine. On a shop's till screen that reads as the platform being down.
 */
const isOffline = (state: { isConnected: boolean | null; isInternetReachable: boolean | null }) =>
    state.isConnected === false || state.isInternetReachable === false;

export default function OfflineBanner() {
    const [isConnected, setIsConnected] = useState<boolean>(true);

    useEffect(() => {
        // Subscribe to network state changes
        const unsubscribe = NetInfo.addEventListener((state: any) => {
            setIsConnected(!isOffline(state));
        });

        // Fetch initial state
        NetInfo.fetch().then((state: any) => {
            setIsConnected(!isOffline(state));
        });

        return () => {
            unsubscribe();
        };
    }, []);

    if (isConnected) return null;

    return (
        <View style={styles.banner}>
            <Text style={styles.text}>📡 No internet connection</Text>
        </View>
    );
}

const styles = StyleSheet.create({
    banner: {
        backgroundColor: "#ef4444",
        paddingVertical: 8,
        paddingHorizontal: 16,
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
    },
    text: {
        color: "#fff",
        fontFamily: 'Karla_600SemiBold',
        fontSize: 14,
    },
});
