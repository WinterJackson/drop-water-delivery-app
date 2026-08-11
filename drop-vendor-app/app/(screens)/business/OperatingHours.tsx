import React, { useContext, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, ScrollView, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { useUpdateVendorProfile, useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { errorMessage } from "@/API/errors";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { BRAND } from "@/constants/brandColors";

export default function OperatingHours() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    // Shift times live on the store profile, not the dashboard — the dashboard
    // never returned them, so these fields opened blank and saving them wrote
    // the defaults over whatever the vendor had actually set.
    const { data: vendorProfile } = useVendorProfile();
    const updateProfile = useUpdateVendorProfile();

    React.useEffect(() => {
        if (vendorProfile?.role === "staff") {
            Toast.error("Access Denied", "Staff members cannot modify operating hours.");
            router.replace("/(screens)");
        }
    }, [vendorProfile]);

    const to12Hour = (time24: string) => {
        if (!time24) return "";
        let [hours, minutes] = time24.split(':');
        if (!hours || !minutes) return time24;
        let h = parseInt(hours, 10);
        const ampm = h >= 12 ? 'PM' : 'AM';
        h = h % 12;
        h = h ? h : 12; 
        return `${h.toString().padStart(2, '0')}:${minutes} ${ampm}`;
    };

    const to24Hour = (time12: string) => {
        const match = time12.trim().match(/^(\d{2}):(\d{2})\s?(AM|PM)$/i);
        if (!match) return time12;
        let [_, hours, minutes, modifier] = match;
        let h = parseInt(hours, 10);
        if (h === 12) {
            h = modifier.toUpperCase() === 'AM' ? 0 : 12;
        } else if (modifier.toUpperCase() === 'PM') {
            h += 12;
        }
        return `${h.toString().padStart(2, '0')}:${minutes}`;
    };

    const format12HourTime = (input: string, prevInput: string) => {
        if (input.length < prevInput.length) return input;
        let cleaned = input.replace(/[^0-9APM]/gi, '').toUpperCase();
        let formatted = '';
        if (cleaned.length > 0) {
            if (!/^[0-1]/.test(cleaned[0])) {
                cleaned = '0' + cleaned;
            }
            formatted += cleaned.substring(0, 2);
        }
        if (cleaned.length >= 2) {
            let h = parseInt(formatted.substring(0,2), 10);
            if (h > 12) formatted = '12';
            if (h === 0) formatted = '12';
            formatted += ':';
        }
        if (cleaned.length > 2) {
            let m1 = cleaned[2];
            if (!/^[0-5]/.test(m1)) m1 = '0';
            formatted += m1;
        }
        if (cleaned.length > 3) {
            formatted += cleaned[3];
            formatted += ' ';
        }
        if (cleaned.length > 4) {
            let p = cleaned[4];
            if (p !== 'A' && p !== 'P') p = 'A';
            formatted += p;
        }
        if (cleaned.length > 5) {
            formatted += 'M';
        }
        return formatted;
    };

    const [start, setStart] = useState<string>(to12Hour(vendorProfile?.shift_start || "08:00"));
    const [end, setEnd] = useState<string>(to12Hour(vendorProfile?.shift_end || "17:00"));
    const [isSaving, setIsSaving] = useState(false);

    const [focusStart, setFocusStart] = useState(false);
    const [focusEnd, setFocusEnd] = useState(false);

    const isValidTime = (t: string) => /^(0[1-9]|1[0-2]):[0-5][0-9]\s(AM|PM)$/i.test(t);
    const isValid = isValidTime(start) && isValidTime(end);

    const handleFocus = (setter: React.Dispatch<React.SetStateAction<boolean>>) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        setter(true);
    };

    const handleSave = async () => {
        if (!isValid) return;
        setIsSaving(true);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            await updateProfile.mutateAsync({
                shift_start: to24Hour(start),
                shift_end: to24Hour(end),
            });
            Toast.success("Saved", "Operating hours updated successfully.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            setTimeout(() => router.back(), 500);
        } catch (error) {
            Toast.error("Error", errorMessage(error, "Could not update operating hours."));
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <Stack.Screen options={{ headerShown: false }} />
            <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} className="flex-1">
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
                        <Text className={`text-xl font-sans-bold flex-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                            Operating Hours
                        </Text>
                    </View>
                </View>

                <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 120 }}>
                    <Text className={`text-sm mb-6 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        Set your standard operating hours. Customers will not be able to place new orders outside of this time window.
                    </Text>

                    <View className="mb-6">
                        <Text className={`font-sans-semibold mb-2 text-base ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                            Shift Start Time
                        </Text>
                        <View className={`flex-row items-center px-4 h-[55px] rounded-2xl border-2 ${focusStart ? "border-accentbg bg-accentbg/5" : (darkTheme ? "bg-black border-gray-800" : "bg-white border-gray-200")}`}>
                            <Ionicons name="time-outline" size={20} color={BRAND.primary} />
                            <TextInput
                                value={start}
                                onChangeText={(text) => setStart(format12HourTime(text, start))}
                                onFocus={() => handleFocus(setFocusStart)}
                                onBlur={() => setFocusStart(false)}
                                placeholder="e.g. 08:00 AM"
                                placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                                className={`flex-1 ml-3 text-lg font-sans-medium tracking-wider ${darkTheme ? "text-white" : "text-black"}`}
                                keyboardType="default"
                                maxLength={8}
                            />
                        </View>
                    </View>

                    <View className="mb-8">
                        <Text className={`font-sans-semibold mb-2 text-base ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                            Shift End Time
                        </Text>
                        <View className={`flex-row items-center px-4 h-[55px] rounded-2xl border-2 ${focusEnd ? "border-accentbg bg-accentbg/5" : (darkTheme ? "bg-black border-gray-800" : "bg-white border-gray-200")}`}>
                            <Ionicons name="time-outline" size={20} color={BRAND.primary} />
                            <TextInput
                                value={end}
                                onChangeText={(text) => setEnd(format12HourTime(text, end))}
                                onFocus={() => handleFocus(setFocusEnd)}
                                onBlur={() => setFocusEnd(false)}
                                placeholder="e.g. 05:00 PM"
                                placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                                className={`flex-1 ml-3 text-lg font-sans-medium tracking-wider ${darkTheme ? "text-white" : "text-black"}`}
                                keyboardType="default"
                                maxLength={8}
                            />
                        </View>
                    </View>

                    <PressableScale activeOpacity={0.8} onPress={handleSave} disabled={isSaving || !isValid}>
                        <View className={`py-4 rounded-2xl items-center ${isSaving || !isValid ? "bg-accentbg/50" : "bg-accentbg"}`}>
                            {isSaving ? (
                                <ActivityIndicator color={BRAND.white} />
                            ) : (
                                <Text className="text-white text-lg font-sans-bold">Save Operating Hours</Text>
                            )}
                        </View>
                    </PressableScale>
                </ScrollView>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}
