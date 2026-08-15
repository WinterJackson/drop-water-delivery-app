import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React, { useContext, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { Text } from '@/components/ui/Text';

import { errorMessage } from "@/API/errors";
import PressableScale from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { PERMISSIONS, useCan } from "@/hooks/queries/useVendorProfile";
import {
    minutesRemaining,
    usePauseStore,
    useResumeStore,
    useStorefront,
} from "@/hooks/queries/useStorefront";
import { Toast } from "@/lib/toast";

/**
 * Stop taking orders for a while, from the screen the vendor is already on.
 *
 * The existing swipe control writes `is_online` through `PUT /profile`, which
 * is owner-only — so the person who has just run out of 20 L bottles at 11am,
 * standing behind the counter, could not use it. And `is_online` has no expiry:
 * a vendor who taps it during a rush and forgets loses the rest of the day to a
 * control they used correctly.
 *
 * A pause fixes both. It is `manage_orders`, because it is shop-floor
 * operations rather than a decision about the business; and it ends by itself.
 *
 * Every duration comes from the server — `pause_presets_minutes`, already
 * filtered against the platform's ceiling. An app offering "4 hours" against a
 * server that caps at two is a button that always fails.
 */
export default function StorePauseCard() {
    const { currentTheme } = useContext(UIThemeContext);
    const dark = currentTheme === "dark";
    const canManageOrders = useCan(PERMISSIONS.manageOrders);

    const { data } = useStorefront();
    const pause = usePauseStore();
    const resume = useResumeStore();
    const [expanded, setExpanded] = useState(false);

    if (!data || !canManageOrders) return null;

    // A suspension is not the vendor's to lift, and an offline store already
    // has its own control on this screen. Neither is a pause.
    if (data.state === "suspended") return null;

    const paused = data.state === "paused";
    const left = minutesRemaining(data.reopens_at);

    const card = `mx-4 mt-3 p-4 rounded-2xl ${dark ? "bg-surface-container" : "bg-white"}`;

    const doPause = async (minutes: number) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            await pause.mutateAsync({ minutes });
            setExpanded(false);
            Toast.success("Paused", "New orders are on hold. You reopen automatically.");
        } catch (err) {
            Toast.error("Could not pause", errorMessage(err, "Please try again."));
        }
    };

    const doResume = async () => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            await resume.mutateAsync();
            Toast.success("Open", "You are taking orders again.");
        } catch (err) {
            Toast.error("Could not reopen", errorMessage(err, "Please try again."));
        }
    };

    // ── Currently paused ──────────────────────────────────────────────────
    if (paused) {
        return (
            <View className={card} style={{ borderWidth: 1, borderColor: "#F59E0B33" }}>
                <View className="flex-row items-center gap-2">
                    <Ionicons name="pause-circle" size={20} color="#F59E0B" />
                    <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                        Paused
                    </Text>
                </View>
                <Text className={`text-xs mt-1 ${dark ? "text-gray-400" : "text-slate-500"}`}>
                    {left !== null
                        ? `You reopen in ${left} min. Customers see the time you are back.`
                        : "Reopening now."}
                </Text>

                <PressableScale
                    onPress={doResume}
                    disabled={resume.isPending}
                    className="mt-3 rounded-xl py-2.5 items-center"
                    style={{ backgroundColor: BRAND.primary }}
                >
                    {resume.isPending ? (
                        <ActivityIndicator color="#fff" size="small" />
                    ) : (
                        <Text className="text-white font-sans-bold text-sm">Reopen now</Text>
                    )}
                </PressableScale>
            </View>
        );
    }

    // ── Open, offline, or outside hours ───────────────────────────────────
    if (!expanded) {
        return (
            <View className={card}>
                <View className="flex-row items-center justify-between">
                    <View className="flex-1 pr-3">
                        <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                            {data.accepting ? "Taking orders" : "Not taking orders"}
                        </Text>
                        <Text className={`text-xs mt-0.5 ${dark ? "text-gray-400" : "text-slate-500"}`}>
                            {/* The server's sentence when it is not open, so the
                                reason on this screen is the one the customer is
                                being shown. */}
                            {data.reason ?? "Pause for a while if you need to catch up — you reopen by yourself."}
                        </Text>
                    </View>
                    {/* Only offered when the shop is actually open. Pausing a
                        store that is already offline or outside its hours
                        changes nothing a customer would notice, and a control
                        that does nothing is the thing this whole feature
                        exists to stop shipping. */}
                    {data.accepting ? (
                        <PressableScale
                            onPress={() => setExpanded(true)}
                            className={`px-3 py-2 rounded-xl ${dark ? "bg-slate-800" : "bg-slate-100"}`}
                        >
                            <View className="flex-row items-center gap-1.5">
                                <Ionicons
                                    name="pause"
                                    size={14}
                                    color={dark ? "#E2E8F0" : "#0F172A"}
                                />
                                <Text className={`text-xs font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                                    Pause
                                </Text>
                            </View>
                        </PressableScale>
                    ) : null}
                </View>
            </View>
        );
    }

    return (
        <View className={card}>
            <View className="flex-row items-center justify-between mb-3">
                <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                    Pause for how long?
                </Text>
                <PressableScale accessibilityLabel="Close the pause options" onPress={() => setExpanded(false)}>
                    <Ionicons name="close" size={20} color={dark ? "#94A3B8" : "#64748B"} />
                </PressableScale>
            </View>

            <View className="flex-row flex-wrap gap-2">
                {data.limits.pause_presets_minutes.map((minutes) => (
                    <PressableScale
                        key={minutes}
                        onPress={() => doPause(minutes)}
                        disabled={pause.isPending}
                        className={`px-4 py-2.5 rounded-xl ${dark ? "bg-slate-800" : "bg-slate-100"}`}
                    >
                        <Text className={`text-sm font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                            {minutes < 60 ? `${minutes} min` : `${minutes / 60} hr`}
                        </Text>
                    </PressableScale>
                ))}
            </View>

            <Text className={`text-xs mt-3 ${dark ? "text-gray-500" : "text-slate-400"}`}>
                Orders already accepted are unaffected. You reopen automatically and
                we will tell you when you do.
            </Text>
        </View>
    );
}
