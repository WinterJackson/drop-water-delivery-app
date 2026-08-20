/**
 * Actions taken offline that have not reached the server yet.
 *
 * This screen exists because the replay queue used to *delete* an action the
 * server rejected with a 400/404/409, behind a toast. For a completed delivery
 * that is the rider's proof of work — and their pay — being destroyed with a
 * message they may never have seen. Nothing anywhere else in the app admitted
 * the queue existed.
 *
 * `services/offlineQueue` now marks such an action `needs_attention` instead of
 * dropping it, and this is where it surfaces: what it was, when it happened, why
 * the server refused, and the two things the rider can do about it.
 */
import { Ionicons } from "@expo/vector-icons";
import { useTabBarClearance } from '@/constants/layout';
import { useAuth } from "@clerk/clerk-expo";
import { useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { Stack, useRouter } from "expo-router";
import React, { useCallback, useContext, useEffect, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StatusBar, TouchableOpacity, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";

import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { EmptyState } from "@/components/ui/EmptyState";
import PressableScale from "@/components/ui/PressableScale";
import { BRAND, TOAST } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { Popup } from "@/lib/popup";
import { Toast } from "@/lib/toast";
import {
    QueuedAction,
    discardQueuedAction,
    flushOfflineQueue,
    getQueuedActionsDetailed,
    retryQueuedAction,
} from "@/services/offlineQueue";

const LABELS: Record<string, string> = {
    UPDATE_DELIVERY_STATUS: "Delivery update",
    REJECT_BOTTLE: "Bottle rejection",
};

export default function PendingSync() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const { getToken } = useAuth();
    const queryClient = useQueryClient();

    const [actions, setActions] = useState<QueuedAction[]>([]);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState<string | null>(null);

    const load = useCallback(async () => {
        setActions(await getQueuedActionsDetailed());
        setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    const syncNow = async () => {
        setBusy("all");
        const result = await flushOfflineQueue(getToken, () => {
            queryClient.invalidateQueries({ queryKey: ["rider", "orders"] });
        });
        await load();
        setBusy(null);
        if (result.sent > 0) {
            Toast.success("Synced", `${result.sent} action${result.sent === 1 ? "" : "s"} sent.`);
        } else if (result.needsAttention > 0) {
            Toast.error("Still stuck", "These actions were refused by the server. See the reason on each.");
        } else {
            Toast.info("Nothing sent", "Still offline, or nothing is due yet.");
        }
    };

    const retryOne = async (action: QueuedAction) => {
        setBusy(action.row_id);
        await retryQueuedAction(action.row_id);
        await flushOfflineQueue(getToken, () => {
            queryClient.invalidateQueries({ queryKey: ["rider", "orders"] });
        });
        await load();
        setBusy(null);
    };

    const discardOne = (action: QueuedAction) => {
        Popup.show({
            title: "Discard this action?",
            message:
                "This will be deleted permanently and never sent. If it was a completed delivery, " +
                "you will not be paid for it. Contact support first if you are unsure.",
            cancelText: "Keep",
            confirmText: "Discard",
            isDestructive: true,
            onConfirm: async () => {
                Popup.hide();
                await discardQueuedAction(action.row_id);
                await load();
            },
        });
    };

    const describe = (action: QueuedAction) => {
        try {
            const payload = JSON.parse(action.payload);
            if (action.type === "UPDATE_DELIVERY_STATUS") return `Marked "${payload.status}"`;
            if (action.type === "REJECT_BOTTLE") return payload.reason_text ?? "Bottle reported";
        } catch { /* fall through to the generic label */ }
        return LABELS[action.type] ?? action.type;
    };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <StatusBar translucent barStyle={darkTheme ? "light-content" : "dark-content"} />
            <Stack.Screen options={{ headerShown: false }} />

            <View
                className="flex-row items-center px-4 py-3 pb-4 mb-2"
                style={{
                    backgroundColor: darkTheme ? "#000" : "#fff",
                    borderBottomWidth: 1,
                    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                }}
            >
                <TouchableOpacity onPress={() => router.back()} className="mr-4">
                    <BackButtonMinimal />
                </TouchableOpacity>
                <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                    Pending Sync
                </Text>
            </View>

            <ScrollView
                contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: tabBarClearance }}
                refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={BRAND.primary} />}
            >
                {loading ? (
                    <View className="py-20 items-center"><ActivityIndicator color={BRAND.primary} /></View>
                ) : actions.length === 0 ? (
                    <EmptyState
                        mood="proud"
                        title="Everything is synced"
                        subtitle="Anything you do without a connection is saved here until it reaches the server."
                    />
                ) : (
                    <>
                        <Text className={`text-sm mb-4 mt-2 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            These were saved on your phone and have not reached the server yet. They are
                            retried automatically — nothing is deleted without you.
                        </Text>

                        <PressableScale
                            onPress={syncNow}
                            disabled={busy !== null}
                            className="py-3 rounded-2xl items-center mb-6"
                            style={{ backgroundColor: BRAND.primary }}
                        >
                            {busy === "all"
                                ? <ActivityIndicator size="small" color="#fff" />
                                : <Text className="text-white font-sans-bold">Sync now</Text>}
                        </PressableScale>

                        {actions.map((action) => (
                            <View
                                key={action.row_id}
                                className={`p-4 mb-3 rounded-2xl border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`}
                            >
                                <View className="flex-row items-center justify-between mb-1">
                                    <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>
                                        {LABELS[action.type] ?? action.type}
                                    </Text>
                                    {action.needs_attention ? (
                                        <View className="flex-row items-center gap-1">
                                            <Ionicons name="alert-circle" size={16} color={TOAST.error} />
                                            <Text style={{ color: TOAST.error }} className="text-xs font-sans-bold">Needs attention</Text>
                                        </View>
                                    ) : (
                                        <Text className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                            Attempt {action.attempts ?? 0}
                                        </Text>
                                    )}
                                </View>

                                <Text className={`text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                                    {describe(action)}
                                </Text>
                                <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                    Order {String(action.id).slice(0, 8)} ·{" "}
                                    {action.created_at ? format(new Date(action.created_at), "d MMM, HH:mm") : "unknown time"}
                                </Text>

                                {action.last_error ? (
                                    <Text style={{ color: TOAST.error }} className="text-xs mt-2">
                                        {action.last_error}
                                    </Text>
                                ) : null}

                                <View className="flex-row gap-3 mt-4">
                                    <PressableScale
                                        onPress={() => retryOne(action)}
                                        disabled={busy !== null}
                                        className="flex-1 py-2.5 rounded-xl items-center"
                                        style={{ backgroundColor: `${BRAND.primary}1A` }}
                                    >
                                        {busy === action.row_id
                                            ? <ActivityIndicator size="small" color={BRAND.primary} />
                                            : <Text style={{ color: BRAND.primary }} className="font-sans-bold">Retry</Text>}
                                    </PressableScale>
                                    {action.needs_attention ? (
                                        <PressableScale
                                            onPress={() => discardOne(action)}
                                            disabled={busy !== null}
                                            className="flex-1 py-2.5 rounded-xl items-center border"
                                            style={{ borderColor: `${TOAST.error}4D` }}
                                        >
                                            <Text style={{ color: TOAST.error }} className="font-sans-bold">Discard</Text>
                                        </PressableScale>
                                    ) : null}
                                </View>
                            </View>
                        ))}
                    </>
                )}
            </ScrollView>
        </SafeAreaView>
    );
}
