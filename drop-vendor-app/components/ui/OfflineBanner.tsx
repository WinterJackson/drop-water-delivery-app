import React, { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import { Text } from '@/components/ui/Text';
// @ts-ignore
import NetInfo from "@react-native-community/netinfo";

/**
 * Network connectivity banner component.
 * Uses @react-native-community/netinfo for reliable native offline detection.
 */
export default function OfflineBanner() {
    const [isConnected, setIsConnected] = useState<boolean>(true);

    useEffect(() => {
        // Subscribe to network state changes
        const unsubscribe = NetInfo.addEventListener((state: any) => {
            setIsConnected(!!state.isConnected && !!state.isInternetReachable !== false);
        });

        // Fetch initial state
        NetInfo.fetch().then((state: any) => {
            setIsConnected(!!state.isConnected && !!state.isInternetReachable !== false);
        });

        return () => {
            unsubscribe();
        };
    }, []);

    // Also hide the banner if it's currently connected but isInternetReachable is null (initial fast check)
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
