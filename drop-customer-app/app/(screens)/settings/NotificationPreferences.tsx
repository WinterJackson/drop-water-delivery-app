import React, { useContext, useState, useEffect } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, Text, ScrollView, Switch } from "react-native";
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { useUserDetails, useUpdateUser } from "@/hooks/queries/useUser";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";

export default function NotificationPreferences() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: User } = useUserDetails();
    const updateUserMutation = useUpdateUser();

    // Default preferences if none exist
    const defaultPrefs = {
        order_updates: true,
        promotions: false,
        delivery_reminders: true,
        analytics: true
    };

    const [preferences, setPreferences] = useState<any>(defaultPrefs);

    useEffect(() => {
        if (User?.preferences) {
            setPreferences({ ...defaultPrefs, ...User.preferences });
        }
    }, [User]);

    const handleToggle = async (key: string, value: boolean) => {
        const newPrefs = { ...preferences, [key]: value };
        // Optimistic update
        setPreferences(newPrefs);
        try {
            await updateUserMutation.mutateAsync({ preferences: newPrefs });
        } catch (error: unknown) {
            // Revert on failure
            setPreferences(preferences);
            Toast.error("Update Failed", "Could not save your preferences.");
        }
    };

    const ToggleItem = ({ title, description, prefKey }: { title: string, description: string, prefKey: string }) => (
        <View 
            className={`flex-row justify-between items-center p-4 mb-3 rounded-2xl border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`}
            style={darkTheme ? {} : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
        >
            <View className="flex-1 pr-6">
                <Text className={`text-lg font-bold mb-1 ${darkTheme ? "text-white" : "text-black"}`}>{title}</Text>
                <Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{description}</Text>
            </View>
            <View>
                <Switch 
                    value={preferences[prefKey]} 
                    onValueChange={(val) => handleToggle(prefKey, val)} 
                    trackColor={{ false: darkTheme ? "#333" : "#ddd", true: BRAND.blue }}
                    thumbColor={BRAND.white}
                />
            </View>
        </View>
    );

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
                <Text className={`text-xl font-bold ${darkTheme ? "text-white" : "text-black"}`}>
                    Notifications
                </Text>
            </View>
            </View>
            <ScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 20, paddingBottom: 120}}>
                <ToggleItem 
                    title="Order Updates" 
                    description="Get push notifications about your order status, out for delivery, and arrival." 
                    prefKey="order_updates" 
                />
                <ToggleItem 
                    title="Promotions & Offers" 
                    description="Receive special offers, discounts, and news from your favorite vendors." 
                    prefKey="promotions" 
                />
                <ToggleItem 
                    title="Delivery Reminders" 
                    description="Reminders to order water when you might be running low." 
                    prefKey="delivery_reminders" 
                />
            </ScrollView>
        </SafeAreaView>
    );
}
