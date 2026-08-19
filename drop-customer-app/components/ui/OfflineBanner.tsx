import React, { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import { Text } from '@/components/ui/Text';
import NetInfo from "@react-native-community/netinfo";

/**
 * Network connectivity banner component.
 * Uses @react-native-community/netinfo for reliable native offline detection.
 */
/**
 * Offline only on a *definitive* answer.
 *
 * `isInternetReachable` is a tri-state: `true`, `false`, and `null` for "the
 * probe has not come back yet". Only `false` is a statement that there is no
 * internet; `null` is an unanswered question, and rendering it as a confident
 * "No internet connection" is the same defect as the coverage banner that told
 * a customer their neighbourhood was unserved before anybody had asked where
 * they lived.
 *
 * It was written `!!state.isInternetReachable !== false`, which reads as if it
 * tolerates `null` and does not: `!!` binds tighter than `!==`, so the
 * expression collapses to `!!state.isInternetReachable` and the `!== false` is
 * dead. `!!null` is `false`, so the banner fired on exactly the state the
 * comment below it said to ignore — on every cold start while the probe was in
 * flight, and permanently on any network where NetInfo's reachability probe
 * (a Google endpoint, not this API) is blocked or slow while the API itself is
 * fine. Reproduced under a VPN: the whole home screen loaded from the server,
 * images and all, under a red bar saying there was no connection.
 */
const isOffline = (state: { isConnected: boolean | null; isInternetReachable: boolean | null }) =>
    state.isConnected === false || state.isInternetReachable === false;

export default function OfflineBanner() {
    const [isConnected, setIsConnected] = useState<boolean>(true);

    useEffect(() => {
        // Subscribe to network state changes
        const unsubscribe = NetInfo.addEventListener(state => {
            setIsConnected(!isOffline(state));
        });

        // Fetch initial state
        NetInfo.fetch().then(state => {
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
