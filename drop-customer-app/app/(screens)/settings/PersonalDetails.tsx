import React, { useContext, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, Text, ScrollView, TextInput, ActivityIndicator } from "react-native";
import Animated, { useAnimatedStyle, withSpring } from 'react-native-reanimated';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { useUserDetails, useUpdateUser } from "@/hooks/queries/useUser";
import { useUser } from "@clerk/clerk-expo";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";
import { InputFieldProps } from "@/types/components";

export default function PersonalDetails() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const { data: User } = useUserDetails();
    const { user } = useUser();
    const updateUserMutation = useUpdateUser();

    const [name, setName] = useState(User?.full_name || user?.fullName || "");
    const [phone, setPhone] = useState(User?.phone_number || "");
    const [floor, setFloor] = useState(User?.floor_level || 0);
    const [hasElevator, setHasElevator] = useState(User?.has_elevator || false);
    const [isSaving, setIsSaving] = useState(false);

    const elevatorToggleStyle = useAnimatedStyle(() => {
        return {
            transform: [{ translateX: withSpring(hasElevator ? 24 : 0, { mass: 1, damping: 15, stiffness: 300 }) }]
        };
    }, [hasElevator]);

    const handleSave = async () => {
        if (!name.trim()) {
            Toast.error("Validation Error", "Name cannot be empty.");
            return;
        }
        
        const phoneTrimmed = phone.trim();
        // Regex validates Kenyan formats: 07XX, 01XX, +2547XX, +2541XX or generic E.164 up to 15 digits
        const phoneRegex = /^(\+254|0)[17]\d{8}$|^\+?[1-9]\d{1,14}$/;
        if (phoneTrimmed && !phoneRegex.test(phoneTrimmed)) {
            Toast.error("Invalid Phone", "Please enter a valid phone number.");
            return;
        }

        setIsSaving(true);
        try {
            await updateUserMutation.mutateAsync({
                full_name: name.trim(),
                phone_number: phoneTrimmed || null,
                floor_level: floor,
                has_elevator: hasElevator
            });
            Toast.success("Saved", "Your details have been updated.");
        } catch (error: unknown) {
            Toast.error("Update Failed", (error as Error).message || "Network error.");
        } finally {
            setIsSaving(false);
        }
    };


    const InputField = ({ label, value, onChangeText = () => {}, keyboardType = "default", editable = true, maxLength }: InputFieldProps) => (
        <View className="mb-5">
            <Text className={`font-semibold mb-2 text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                {label}
            </Text>
            <View className={`px-4 py-3 rounded-2xl border ${darkTheme ? "bg-gray-900 border-gray-800" : "bg-white border-gray-200"} ${!editable ? "opacity-50" : ""}`}>
                <TextInput
                    value={value}
                    onChangeText={onChangeText}
                    keyboardType={keyboardType}
                    editable={editable}
                    maxLength={maxLength}
                    className={`text-base ${darkTheme ? "text-white" : "text-black"}`}
                    placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                />
            </View>
            {!editable && <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>Managed by your login provider</Text>}
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
                    Personal Details
                </Text>
            </View>
            </View>
            <ScrollView 
                contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 20, paddingBottom: 120 }}
                keyboardShouldPersistTaps="handled"
            >
                <InputField label="Full Name" value={name} onChangeText={setName} maxLength={50} />
                <InputField label="Email Address" value={User?.email || user?.emailAddresses?.[0]?.emailAddress || ""} onChangeText={() => {}} editable={false} />
                <InputField label="Phone Number" value={phone} onChangeText={setPhone} keyboardType="phone-pad" maxLength={15} />

                {/* ── Address Anti-Fraud Details ── */}
                <Text className={`font-semibold mt-4 mb-4 text-lg ${darkTheme ? "text-white" : "text-black"}`}>Delivery Details</Text>
                
                <InputField label="Floor Level (0 = Ground Floor)" value={String(floor)} onChangeText={(text: string) => setFloor(parseInt(text) || 0)} keyboardType="number-pad" maxLength={3} />
                
                <View className={`flex-row justify-between items-center mb-5 px-4 py-3 rounded-2xl border ${darkTheme ? "bg-gray-900 border-gray-800" : "bg-white border-gray-200"}`}>
                    <Text className={`text-base font-medium ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Has Elevator</Text>
                    <PressableScale onPress={() => setHasElevator(!hasElevator)} className={`w-14 h-8 rounded-full justify-center px-1 ${hasElevator ? "bg-sky-500" : (darkTheme ? "bg-gray-700" : "bg-gray-300")}`}>
                        <Animated.View className="w-6 h-6 rounded-full bg-white" style={elevatorToggleStyle} />
                    </PressableScale>
                </View>

                <PressableScale
                    activeOpacity={0.8}
                    onPress={handleSave}
                    disabled={isSaving}
                >
                    <View className={`mt-4 py-4 rounded-2xl items-center ${isSaving ? "bg-sky-400" : "bg-sky-500"}`}>
                        {isSaving ? (
                            <ActivityIndicator color={BRAND.white} />
                        ) : (
                            <Text className="text-white text-lg font-bold">Save Changes</Text>
                        )}
                    </View>
                </PressableScale>
            </ScrollView>
        </SafeAreaView>
    );
}
