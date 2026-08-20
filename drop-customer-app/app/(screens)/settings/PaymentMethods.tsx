import React, { useContext, useState } from "react";
import { useTabBarClearance } from '@/constants/layout';
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";

import { View, ScrollView, ActivityIndicator } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import Button from "@/components/ui/Button";
import { useUserDetails, useUpdateUser } from "@/hooks/queries/useUser";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";
import { PressableScale } from "@/components/ui/PressableScale";

/**
 * At module scope, not inside the screen.
 *
 * A component declared in a render body is a new function object — and so a new
 * component *type* — on every render, which makes React unmount its subtree and
 * mount a fresh one instead of updating it. Even with no input and no state of
 * its own that is not free: every child is torn down and rebuilt, `PressableScale`
 * restarts its animation, and the reconciler does the most expensive kind of work
 * on the most ordinary re-render.
 *
 * What it closed over is passed in instead.
 */
const PaymentCard = ({ item, index, darkTheme, handleRemove }: any) => (
    <View className={`p-5 mb-4 rounded-2xl border flex-row items-center justify-between ${darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white"}`}>
        <View className="flex-row items-center gap-4">
            <View className={`w-12 h-12 rounded-full items-center justify-center ${item.type === "mpesa" ? "" : "bg-blue-500/10"}`} style={item.type === "mpesa" ? { backgroundColor: `${BRAND.primary}1A` } : {}}>
                <Text style={{ fontSize: 24 }}>{item.type === "mpesa" ? "📱" : "💳"}</Text>
            </View>
            <View>
                <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                    {item.type === "mpesa" ? "M-Pesa" : "Card"}
                </Text>
                <Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{item.phone}</Text>
            </View>
        </View>
        <View className="flex-row items-center gap-2">
            {item.isDefault && (
                <View className="bg-blue-500/10 px-2 py-1 rounded-md">
                    <Text className="text-blue-500 font-sans-bold text-xs">DEFAULT</Text>
                </View>
            )}
            <PressableScale onPress={() => handleRemove(index)} className="ml-2">
                <Text className="text-red-500 text-lg">🗑️</Text>
            </PressableScale>
        </View>
    </View>
);

export default function PaymentMethods() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: User } = useUserDetails();
    const updateUserMutation = useUpdateUser();
    const paymentMethods = User?.payment_methods || [];

    const [isAdding, setIsAdding] = useState(false);
    const [newPhone, setNewPhone] = useState("");
    const [isSaving, setIsSaving] = useState(false);

    const handleSaveNew = async () => {
        const phoneTrimmed = newPhone.trim();
        const phoneRegex = /^(\+254|0)[17]\d{8}$|^\+?[1-9]\d{1,14}$/;
        if (!phoneRegex.test(phoneTrimmed)) {
            Toast.error("Invalid Phone", "Please enter a valid phone number.");
            return;
        }

        const isDuplicate = paymentMethods.some((pm: any) => pm.phone === phoneTrimmed);
        if (isDuplicate) {
            Toast.error("Duplicate", "This payment method is already added.");
            return;
        }

        setIsSaving(true);
        try {
            const newMethods = [...paymentMethods, {
                type: "mpesa",
                phone: phoneTrimmed,
                isDefault: paymentMethods.length === 0
            }];
            await updateUserMutation.mutateAsync({ payment_methods: newMethods });
            Toast.success("Added", "Payment method added.");
            setIsAdding(false);
            setNewPhone("");
        } catch (error: unknown) {
            Toast.error("Error", (error as Error).message || "Failed to add.");
        } finally {
            setIsSaving(false);
        }
    };

    const handleRemove = (index: number) => {
        Popup.show({
            title: "Remove Payment Method",
            message: "Are you sure you want to remove this payment method?",
            cancelText: "Cancel",
            confirmText: "Remove",
            isDestructive: true,
            onConfirm: async () => {
                Popup.setLoading(true);
                const newMethods: any[] = [...paymentMethods];
                newMethods.splice(index, 1);
                // If we removed the default, make the first one default
                if (paymentMethods[index].isDefault && newMethods.length > 0) {
                    newMethods[0].isDefault = true;
                }
                try {
                    await updateUserMutation.mutateAsync({ payment_methods: newMethods });
                    Toast.success("Removed", "Payment method removed.");
                } catch (error: unknown) {
                    Toast.error("Error", (error as Error).message || "Failed to remove.");
                } finally {
                    Popup.hide();
                }
            }
        });
    };

    const paymentCardProps = { darkTheme, handleRemove };

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
                    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
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
            <ScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 20, paddingBottom: tabBarClearance }}>
                {paymentMethods.map((item: any, idx: number) => (
                    <PaymentCard {...paymentCardProps} key={idx} item={item} index={idx} />
                ))}

                {isAdding ? (
                    <View className={`p-5 mb-4 rounded-2xl border ${darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white"}`}>
                        <Text className={`font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Enter M-Pesa Number</Text>
                        <TextInput
                            value={newPhone}
                            onChangeText={setNewPhone}
                            keyboardType="phone-pad"
                            maxLength={15}
                            autoFocus
                            placeholder="e.g. +254712345678"
                            placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                            className={`p-3 rounded-xl border mb-4 ${darkTheme ? "border-gray-700 bg-black text-white" : "border-gray-300 bg-white text-black"}`}
                        />
                        <View className="flex-row gap-3">
                            <PressableScale onPress={() => setIsAdding(false)} className="flex-1 py-3 items-center rounded-xl border border-gray-400">
                                <Text className={darkTheme ? "text-white font-sans-bold" : "text-black font-sans-bold"}>Cancel</Text>
                            </PressableScale>
                            <PressableScale onPress={handleSaveNew} disabled={isSaving} className="flex-1 py-3 items-center rounded-xl" style={{ backgroundColor: BRAND.primary }}>
                                {isSaving ? <ActivityIndicator color={BRAND.white} /> : <Text className="text-white font-sans-bold">Save</Text>}
                            </PressableScale>
                        </View>
                    </View>
                ) : (
                    <PressableScale 
                        onPress={() => setIsAdding(true)}
                        activeOpacity={0.7}
                        className="mt-6 py-4 rounded-xl items-center border-2 bg-transparent"
                        style={{ borderColor: BRAND.primary }}
                    >
                        <Text className="text-lg font-sans-bold" style={{ color: BRAND.primary }}>+ Add M-Pesa Number</Text>
                    </PressableScale>
                )}
            </ScrollView>
        </SafeAreaView>
    );
}
