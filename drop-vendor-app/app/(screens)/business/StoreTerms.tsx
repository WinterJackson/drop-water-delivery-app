import { errorMessage } from "@/API/errors";
import { useTabBarClearance } from '@/constants/layout';
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { useSetStorefrontTerms, useStorefront } from "@/hooks/queries/useStorefront";
import { useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { Toast } from "@/lib/toast";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import React, { useContext, useEffect, useState } from "react";
import {
    ActivityIndicator,
    KeyboardAvoidingView,
    Platform,
    ScrollView,
    Switch,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { formatMoney } from "@/utils/money";

/**
 * The terms this store trades on: will it take cash, and what is the smallest
 * order worth preparing.
 *
 * Owner-only, like the payout account and the business name — these are what
 * the business *is*, not how today is going. The pause control is deliberately
 * elsewhere (the dashboard) and open to staff, because running out of stock at
 * 11am is not a decision about the business.
 *
 * Neither figure here is a literal. The maximum minimum order and whether
 * declining cash is permitted at all both arrive from the server as settings
 * rows, so an administrator moving either changes what this screen says on the
 * next open — rather than the app confidently stating a rule the platform has
 * since changed.
 */
export default function StoreTerms() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const dark = currentTheme === "dark";
    const router = useRouter();

    const { data: profile } = useVendorProfile();
    const { data: storefront, isLoading } = useStorefront();
    const save = useSetStorefrontTerms();

    useEffect(() => {
        if (profile?.role === "staff") {
            Toast.error("Access Denied", "Only the owner can change store terms.");
            router.replace("/(screens)");
        }
    }, [profile]);

    const [minimum, setMinimum] = useState<string>("");
    const [hydrated, setHydrated] = useState(false);

    useEffect(() => {
        if (storefront && !hydrated) {
            const value = Number(storefront.min_order_value);
            setMinimum(value > 0 ? String(Math.round(value)) : "");
            setHydrated(true);
        }
    }, [storefront, hydrated]);

    if (isLoading || !storefront) {
        return (
            <SafeAreaView className={`flex-1 items-center justify-center ${dark ? "bg-black" : ""}`}>
                <ActivityIndicator color={BRAND.primary} />
            </SafeAreaView>
        );
    }

    const ceiling = Number(storefront.limits.max_min_order_value);
    const typed = minimum.trim() === "" ? 0 : Number(minimum);
    const overCeiling = Number.isFinite(typed) && typed > ceiling;
    const dirty = Math.round(Number(storefront.min_order_value)) !== Math.round(typed || 0);

    const toggleCash = async (next: boolean) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        try {
            await save.mutateAsync({ accepts_cash: next });
        } catch (err) {
            // The switch renders from the server's answer, so a refusal simply
            // leaves it where it was — no local state to unwind.
            Toast.error("Not changed", errorMessage(err, "Could not update cash orders."));
        }
    };

    const saveMinimum = async () => {
        if (overCeiling) return;
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            await save.mutateAsync({ min_order_value: Math.max(0, Math.round(typed || 0)) });
            Toast.success("Saved", "Your minimum order has been updated.");
        } catch (err) {
            Toast.error("Not saved", errorMessage(err, "Could not update the minimum order."));
        }
    };

    const cardClass = `p-4 rounded-2xl mb-4 ${dark ? "bg-surface-container" : "bg-white"}`;

    return (
        <SafeAreaView className={`flex-1 ${dark ? "bg-black" : "bg-gray-50"}`}>
            <Stack.Screen options={{ headerShown: false }} />
            <KeyboardAvoidingView
                behavior={Platform.OS === "ios" ? "padding" : undefined}
                className="flex-1"
            >
                <View className="flex-row items-center px-4 py-3 gap-3">
                    <BackButtonMinimal />
                    <Text className={`text-lg font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                        Store terms
                    </Text>
                </View>

                <ScrollView className="px-4" contentContainerStyle={{ paddingBottom: tabBarClearance }}>
                    {/* ── Cash orders ──────────────────────────────────── */}
                    <View className={cardClass}>
                        <View className="flex-row items-center justify-between">
                            <View className="flex-1 pr-4">
                                <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                                    Accept cash orders
                                </Text>
                                <Text className={`text-xs mt-1 ${dark ? "text-gray-400" : "text-slate-500"}`}>
                                    Turn this off if you have no float to work with. M-Pesa
                                    orders keep coming either way.
                                </Text>
                            </View>
                            <Switch
                                value={storefront.accepts_cash}
                                onValueChange={toggleCash}
                                disabled={save.isPending || !storefront.limits.may_decline_cash}
                                trackColor={{ false: dark ? "#334155" : "#CBD5E1", true: BRAND.primary }}
                                thumbColor="#fff"
                            />
                        </View>

                        {!storefront.limits.may_decline_cash ? (
                            <View className="flex-row items-start gap-2 mt-3">
                                <Ionicons
                                    name="information-circle-outline"
                                    size={14}
                                    color={dark ? "#94A3B8" : "#64748B"}
                                    style={{ marginTop: 1 }}
                                />
                                <Text className={`text-xs flex-1 ${dark ? "text-gray-400" : "text-slate-500"}`}>
                                    Cash orders are required on the platform at the moment, so
                                    this cannot be switched off. Contact support if you have no
                                    float to carry them.
                                </Text>
                            </View>
                        ) : null}
                    </View>

                    {/* ── Minimum order ────────────────────────────────── */}
                    <View className={cardClass}>
                        <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                            Minimum order
                        </Text>
                        <Text className={`text-xs mt-1 mb-3 ${dark ? "text-gray-400" : "text-slate-500"}`}>
                            The smallest basket you will prepare, counting the water only —
                            not delivery or fees. Leave it empty for no minimum.
                        </Text>

                        <View
                            className={`flex-row items-center px-4 h-[55px] rounded-2xl border-2 ${
                                overCeiling
                                    ? "border-red-500"
                                    : dark
                                      ? "bg-black border-gray-800"
                                      : "bg-white border-gray-200"
                            }`}
                        >
                            <Text className={`font-sans-bold mr-2 ${dark ? "text-gray-400" : "text-slate-500"}`}>
                                KSH
                            </Text>
                            <TextInput
                                value={minimum}
                                onChangeText={(t) => setMinimum(t.replace(/[^0-9]/g, ""))}
                                keyboardType="number-pad"
                                placeholder="No minimum"
                                placeholderTextColor={dark ? "#475569" : "#94A3B8"}
                                maxLength={6}
                                className={`flex-1 text-base font-sans-semibold ${dark ? "text-white" : "text-slate-900"}`}
                            />
                        </View>

                        <Text
                            className={`text-xs mt-2 ${
                                overCeiling
                                    ? dark
                                        ? "text-red-400"
                                        : "text-red-600"
                                    : dark
                                      ? "text-gray-500"
                                      : "text-slate-400"
                            }`}
                        >
                            {overCeiling
                                ? `The highest allowed is ${formatMoney(ceiling)}. A minimum above that hides you from customers who could not have met it, without showing you as closed.`
                                : `Up to ${formatMoney(ceiling)}.`}
                        </Text>

                        <PressableScale
                            onPress={saveMinimum}
                            disabled={!dirty || overCeiling || save.isPending}
                            className="mt-4 rounded-xl py-3 items-center"
                            style={{
                                backgroundColor:
                                    !dirty || overCeiling ? (dark ? "#1E293B" : "#E2E8F0") : BRAND.primary,
                            }}
                        >
                            {save.isPending ? (
                                <ActivityIndicator color="#fff" size="small" />
                            ) : (
                                <Text
                                    className={`font-sans-bold ${
                                        !dirty || overCeiling
                                            ? dark
                                                ? "text-gray-500"
                                                : "text-slate-400"
                                            : "text-white"
                                    }`}
                                >
                                    Save minimum
                                </Text>
                            )}
                        </PressableScale>
                    </View>

                    {/* Delivery fee and radius are set by the platform, not here.
                        Saying so is better than leaving a vendor hunting for a
                        control that does not exist — the rider is paid out of the
                        delivery fee, so a store undercutting to win orders would
                        be spending the rider's money. */}
                    <View className="flex-row items-start gap-2 px-1">
                        <Ionicons
                            name="lock-closed-outline"
                            size={14}
                            color={dark ? "#64748B" : "#94A3B8"}
                            style={{ marginTop: 2 }}
                        />
                        <Text className={`text-xs flex-1 ${dark ? "text-gray-500" : "text-slate-400"}`}>
                            Delivery fees and your delivery radius are set by Drop and are the
                            same for every store, so no shop competes by paying riders less.
                        </Text>
                    </View>
                </ScrollView>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}
