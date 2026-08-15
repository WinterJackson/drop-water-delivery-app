import { errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import React, { useContext, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { TouchableOpacity } from "react-native";
import { Text } from '@/components/ui/Text';
import { View, ScrollView, Switch } from "react-native";
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { Toast } from "@/lib/toast";
import { useRiderProfile, type RiderPreferences } from "@/hooks/queries/useRiderData";
import { BRAND } from "@/constants/brandColors";

export default function Preferences() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const { data: profile } = useRiderProfile();
    const queryClient = useQueryClient();

    const { put } = useApiRequest();
    const prefs: Required<RiderPreferences> = {
        orderUpdates: profile?.preferences?.orderUpdates ?? true,
        analytics: profile?.preferences?.analytics ?? true,
    };

    const updatePreferencesMutation = useMutation({
        mutationFn: (newPrefs: RiderPreferences) =>
            put(RiderApiRoutes.UpdateProfile.path, { preferences: newPrefs }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["rider", "profile"] });
        },
        onError: (e) => {
             Toast.error("Error", errorMessage(e, "Could not update preferences."));
        }
    });

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
                    <TouchableOpacity onPress={() => router.back()} className="mr-4">
                        <BackButtonMinimal />
                    </TouchableOpacity>
                    <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                        Preferences
                    </Text>
                </View>
            </View>
            <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 120 }}>
                <Text className={`text-lg font-sans-bold mb-4 px-2 ${darkTheme ? "text-white" : "text-black"}`}>
                    App Preferences
                </Text>

                <View className={`rounded-2xl border ${darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white"} overflow-hidden`}>
                    <View className="flex-row justify-between items-center p-4 border-b border-gray-200 dark:border-gray-800">
                        <View className="flex-1 pr-4">
                            <Text className={`text-base font-sans-bold mb-1 ${darkTheme ? "text-white" : "text-black"}`}>
                                Order Updates
                            </Text>
                            <Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                Receive push notifications for order statuses.
                            </Text>
                        </View>
                        <Switch 
                            value={prefs.orderUpdates} 
                            onValueChange={(val) => updatePreferencesMutation.mutate({ ...prefs, orderUpdates: val })} 
                            trackColor={{ false: darkTheme ? "#333" : "#ddd", true: BRAND.primary }} 
                            thumbColor="#fff"
                        />
                    </View>

                    <View className="flex-row justify-between items-center p-4">
                        <View className="flex-1 pr-4">
                            <Text className={`text-base font-sans-bold mb-1 ${darkTheme ? "text-white" : "text-black"}`}>
                                Analytics & Tracking
                            </Text>
                            <Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                Help us improve the app by sharing crash reports.
                            </Text>
                        </View>
                        <Switch 
                            value={prefs.analytics} 
                            onValueChange={(val) => updatePreferencesMutation.mutate({ ...prefs, analytics: val })} 
                            trackColor={{ false: darkTheme ? "#333" : "#ddd", true: BRAND.primary }} 
                            thumbColor="#fff"
                        />
                    </View>
                </View>
            </ScrollView>
        </SafeAreaView>
    );
}
