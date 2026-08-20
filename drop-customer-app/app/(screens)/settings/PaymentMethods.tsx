import React, { useContext, useState } from "react";
import { useTabBarClearance } from "@/constants/layout";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";

import { View, ScrollView, ActivityIndicator } from "react-native";
import { Text, TextInput } from "@/components/ui/Text";
import { Stack, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { useUserDetails, useUpdateUser } from "@/hooks/queries/useUser";
import { errorMessage } from "@/API/errors";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";
import { PressableScale } from "@/components/ui/PressableScale";
import { Skeleton } from "@/components/ui/Skeleton";
import { isSafaricomNumber, toE164, formatPhone, normalisePhone, MAX_PAYMENT_METHODS } from "@/utils/phone";
import type { PaymentMethodEntry } from "@/types/models";

/**
 * At module scope, not inside the screen.
 *
 * A component declared in a render body is a new function object — and so a new
 * component *type* — on every render, which makes React unmount its subtree and
 * mount a fresh one instead of updating it.
 */
const MethodCard = ({
    item,
    darkTheme,
    onRemove,
    onMakeDefault,
    busy,
}: {
    item: PaymentMethodEntry;
    darkTheme: boolean;
    onRemove: (phone: string) => void;
    onMakeDefault: (phone: string) => void;
    busy: boolean;
}) => {
    const isDefault = !!item.isDefault;
    const phone = item.phone ?? "";
    return (
        <View
            className={`mb-3 rounded-2xl border overflow-hidden ${
                isDefault
                    ? darkTheme
                        ? "bg-primary/10 border-primary"
                        : "bg-blue-50 border-primary"
                    : darkTheme
                      ? "bg-surface-container border-gray-800"
                      : "bg-white border-gray-200"
            }`}
        >
            <View className="flex-row items-center gap-4 p-4">
                <View
                    className="w-12 h-12 rounded-2xl items-center justify-center"
                    style={{ backgroundColor: `${BRAND.primary}1A` }}
                >
                    <Ionicons name="phone-portrait-outline" size={22} color={BRAND.primary} />
                </View>

                <View className="flex-1">
                    <Text
                        className={`font-mono text-base ${darkTheme ? "text-white" : "text-black"}`}
                    >
                        {formatPhone(phone)}
                    </Text>
                    <Text className={`text-xs mt-0.5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        M-Pesa
                    </Text>
                </View>

                {isDefault ? (
                    <View className="flex-row items-center gap-1.5 px-3 py-1.5 rounded-full" style={{ backgroundColor: BRAND.primary }}>
                        <Ionicons name="checkmark-circle" size={13} color={BRAND.white} />
                        <Text className="text-white font-sans-bold text-[11px] tracking-wide">DEFAULT</Text>
                    </View>
                ) : null}
            </View>

            {/* The actions sit on their own row so the number above always has the
                full width. A 12-digit number and two controls do not share a line
                on a 360dp handset without one of them being truncated. */}
            <View
                className={`flex-row border-t ${
                    darkTheme ? "border-white/10" : "border-gray-100"
                }`}
            >
                {!isDefault && (
                    <PressableScale
                        accessibilityLabel={`Bill ${formatPhone(phone)} by default`}
                        onPress={() => onMakeDefault(phone)}
                        disabled={busy}
                        className="flex-1 flex-row items-center justify-center gap-2 py-3"
                    >
                        <Ionicons name="checkmark-circle-outline" size={17} color={BRAND.primary} />
                        <Text className="font-sans-semibold text-sm" style={{ color: BRAND.primary }}>
                            Set as default
                        </Text>
                    </PressableScale>
                )}
                <PressableScale
                    accessibilityLabel={`Remove ${formatPhone(phone)}`}
                    onPress={() => onRemove(phone)}
                    disabled={busy}
                    className={`${isDefault ? "flex-1" : ""} flex-row items-center justify-center gap-2 py-3 px-6 ${
                        isDefault ? "" : darkTheme ? "border-l border-white/10" : "border-l border-gray-100"
                    }`}
                >
                    <Ionicons name="trash-outline" size={17} color="#ef4444" />
                    <Text className="font-sans-semibold text-sm text-red-500">Remove</Text>
                </PressableScale>
            </View>
        </View>
    );
};

export default function PaymentMethods() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: User, isLoading } = useUserDetails();
    const updateUserMutation = useUpdateUser();
    const paymentMethods: PaymentMethodEntry[] = User?.payment_methods ?? [];

    const [isAdding, setIsAdding] = useState(false);
    const [newPhone, setNewPhone] = useState("");
    const [isSaving, setIsSaving] = useState(false);

    const busy = isSaving || updateUserMutation.isPending;

    /** Persist a whole list, keeping exactly one default. */
    const commit = async (methods: PaymentMethodEntry[], success: string) => {
        const withDefault =
            methods.length > 0 && !methods.some((m) => m.isDefault)
                ? methods.map((m, i) => ({ ...m, isDefault: i === 0 }))
                : methods;
        await updateUserMutation.mutateAsync({ payment_methods: withDefault });
        Toast.success("Saved", success);
    };

    const atCapacity = paymentMethods.length >= MAX_PAYMENT_METHODS;

    const handleSaveNew = async () => {
        if (atCapacity) {
            Toast.error(
                "That's the limit",
                `You can save up to ${MAX_PAYMENT_METHODS} numbers. Remove one to add another.`
            );
            return;
        }
        // Safaricom only. M-Pesa is Safaricom's, so an STK push to an Airtel or
        // Telkom line never arrives — saving one is not a payment method, it is
        // a failure deferred to the moment the customer is trying to pay.
        if (!isSafaricomNumber(newPhone)) {
            Toast.error(
                "Safaricom numbers only",
                "M-Pesa only sends the payment prompt to Safaricom lines."
            );
            return;
        }

        const canonical = toE164(newPhone)!;
        // Compare on the normalised value: 0712345678, +254712345678 and
        // 254712345678 are one number, and a raw string compare let the same
        // line be saved three times.
        if (paymentMethods.some((m) => normalisePhone(m.phone) === normalisePhone(canonical))) {
            Toast.error("Already saved", "That number is already on your list.");
            return;
        }

        setIsSaving(true);
        try {
            await commit(
                [...paymentMethods, { type: "mpesa", phone: canonical, isDefault: paymentMethods.length === 0 }],
                "Payment method added."
            );
            setIsAdding(false);
            setNewPhone("");
        } catch (error: unknown) {
            Toast.error("Couldn't add that", errorMessage(error, "Please try again."));
        } finally {
            setIsSaving(false);
        }
    };

    const handleMakeDefault = async (phone: string) => {
        try {
            await commit(
                paymentMethods.map((m) => ({ ...m, isDefault: m.phone === phone })),
                `${formatPhone(phone)} will be billed at checkout.`
            );
        } catch (error: unknown) {
            Toast.error("Couldn't update", errorMessage(error, "Please try again."));
        }
    };

    const handleRemove = (phone: string) => {
        const removing = paymentMethods.find((m) => m.phone === phone);
        Popup.show({
            title: "Remove this number?",
            message: removing?.isDefault
                ? `${formatPhone(phone)} is your default. Removing it means the next number on your list is billed instead.`
                : `${formatPhone(phone)} will no longer appear at checkout.`,
            cancelText: "Cancel",
            confirmText: "Remove",
            isDestructive: true,
            onConfirm: async () => {
                Popup.setLoading(true);
                try {
                    await commit(
                        paymentMethods.filter((m) => m.phone !== phone),
                        "Payment method removed."
                    );
                } catch (error: unknown) {
                    Toast.error("Couldn't remove", errorMessage(error, "Please try again."));
                } finally {
                    Popup.hide();
                }
            },
        });
    };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <Stack.Screen options={{ headerShown: false }} />
            <View style={{ overflow: "hidden", paddingBottom: 4 }}>
                <View
                    className="flex-row items-center px-4 py-3 pb-4 mb-2"
                    style={{
                        backgroundColor: darkTheme ? "#000" : "#fff",
                        borderBottomWidth: 1,
                        borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                        ...(darkTheme
                            ? { shadowColor: "#000", shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 }
                            : { shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }),
                    }}
                >
                    <PressableScale onPress={() => router.back()} className="mr-4">
                        <BackButtonMinimal />
                    </PressableScale>
                    <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                        Payment Methods
                    </Text>
                </View>
            </View>

            <ScrollView
                contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 16, paddingBottom: tabBarClearance }}
                showsVerticalScrollIndicator={false}
            >
                {/* What the screen is for. Without this the list of numbers does
                    not say which one matters or when it is used. */}
                <View
                    className={`flex-row gap-3 p-4 mb-5 rounded-2xl ${
                        darkTheme ? "bg-surface-container" : "bg-blue-50"
                    }`}
                >
                    <Ionicons name="information-circle-outline" size={20} color={BRAND.primary} />
                    <Text className={`flex-1 text-sm leading-5 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                        Your <Text className="font-sans-bold">default</Text> number is the one we send
                        the M-Pesa prompt to at checkout. Save up to{" "}
                        <Text className="font-sans-bold">{MAX_PAYMENT_METHODS}</Text> Safaricom
                        numbers — you can still change it on the payment screen.
                    </Text>
                </View>

                {isLoading && paymentMethods.length === 0 ? (
                    // Empty and loading are different answers. Rendering the
                    // empty state while the profile is in flight tells a customer
                    // their saved numbers are gone.
                    <View className="gap-3">
                        {[0, 1].map((i) => (
                            <Skeleton key={i} width="100%" height={116} borderRadius={16} />
                        ))}
                    </View>
                ) : (
                    paymentMethods.map((item) => (
                        <MethodCard
                            key={item.phone ?? JSON.stringify(item)}
                            item={item}
                            darkTheme={darkTheme}
                            busy={busy}
                            onRemove={handleRemove}
                            onMakeDefault={handleMakeDefault}
                        />
                    ))
                )}

                {!isLoading && paymentMethods.length === 0 && !isAdding && (
                    <View
                        className={`items-center px-6 py-10 rounded-2xl border border-dashed ${
                            darkTheme ? "border-gray-800" : "border-gray-300"
                        }`}
                    >
                        <View
                            className="w-16 h-16 rounded-full items-center justify-center mb-4"
                            style={{ backgroundColor: `${BRAND.primary}1A` }}
                        >
                            <Ionicons name="phone-portrait-outline" size={28} color={BRAND.primary} />
                        </View>
                        <Text className={`text-lg font-sans-bold mb-1 ${darkTheme ? "text-white" : "text-black"}`}>
                            No saved numbers yet
                        </Text>
                        <Text className={`text-sm text-center leading-5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            Save the Safaricom line you pay with and we'll fill it in for you at checkout.
                        </Text>
                    </View>
                )}

                {isAdding ? (
                    <View
                        className={`p-5 mt-2 rounded-2xl border ${
                            darkTheme ? "border-gray-800 bg-surface-container" : "border-gray-200 bg-white"
                        }`}
                    >
                        <Text className={`font-sans-bold text-base mb-1 ${darkTheme ? "text-white" : "text-black"}`}>
                            Add an M-Pesa number
                        </Text>
                        <Text className={`text-xs mb-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            Safaricom only, in any format — 0712 345 678 or +254 712 345 678.
                        </Text>
                        <TextInput
                            value={newPhone}
                            onChangeText={setNewPhone}
                            keyboardType="phone-pad"
                            maxLength={15}
                            autoFocus
                            placeholder="0712 345 678"
                            placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                            className={`px-4 py-3 rounded-xl border font-mono text-base ${
                                darkTheme ? "border-gray-700 bg-black text-white" : "border-gray-300 bg-white text-black"
                            }`}
                        />
                        {/* Confirm what will be stored before it is stored. The
                            number is the whole point of the screen. */}
                        <Text
                            className={`text-xs mt-2 h-4 ${
                                newPhone && !isSafaricomNumber(newPhone) ? "text-red-500" : darkTheme ? "text-gray-500" : "text-gray-400"
                            }`}
                        >
                            {!newPhone
                                ? ""
                                : isSafaricomNumber(newPhone)
                                  ? `Saving as ${formatPhone(newPhone)}`
                                  : "M-Pesa only reaches Safaricom lines."}
                        </Text>

                        <View className="flex-row gap-3 mt-4">
                            <PressableScale
                                onPress={() => {
                                    setIsAdding(false);
                                    setNewPhone("");
                                }}
                                className={`flex-1 py-3 items-center rounded-xl border ${
                                    darkTheme ? "border-gray-700" : "border-gray-300"
                                }`}
                            >
                                <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                                    Cancel
                                </Text>
                            </PressableScale>
                            <PressableScale
                                onPress={handleSaveNew}
                                disabled={busy || !isSafaricomNumber(newPhone)}
                                className="flex-1 py-3 items-center rounded-xl"
                                style={{
                                    backgroundColor: BRAND.primary,
                                    opacity: busy || !isSafaricomNumber(newPhone) ? 0.5 : 1,
                                }}
                            >
                                {isSaving ? (
                                    <ActivityIndicator color={BRAND.white} />
                                ) : (
                                    <Text className="text-white font-sans-bold">Save number</Text>
                                )}
                            </PressableScale>
                        </View>
                    </View>
                ) : atCapacity ? (
                    /* At the limit the control is replaced, not disabled. A greyed
                       button invites a tap and then explains nothing; this says
                       what the state is and what to do about it. */
                    <View
                        className={`mt-4 flex-row items-center gap-3 p-4 rounded-2xl border border-dashed ${
                            darkTheme ? "border-gray-800" : "border-gray-300"
                        }`}
                    >
                        <Ionicons
                            name="information-circle-outline"
                            size={20}
                            color={darkTheme ? "#6b7280" : "#9ca3af"}
                        />
                        <Text className={`flex-1 text-sm leading-5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            You've saved the maximum of {MAX_PAYMENT_METHODS} numbers. Remove one to
                            add a different line.
                        </Text>
                    </View>
                ) : (
                    <PressableScale
                        onPress={() => setIsAdding(true)}
                        activeOpacity={0.7}
                        disabled={busy}
                        className="mt-4 py-4 rounded-2xl flex-row items-center justify-center gap-2"
                        style={{ backgroundColor: BRAND.primary, opacity: busy ? 0.6 : 1 }}
                    >
                        <Ionicons name="add" size={20} color={BRAND.white} />
                        <Text className="text-white text-base font-sans-bold">Add M-Pesa number</Text>
                    </PressableScale>
                )}
            </ScrollView>
        </SafeAreaView>
    );
}
