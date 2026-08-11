import { errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import React, { useContext, useState, useEffect } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { TouchableOpacity } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { View, ScrollView, ActivityIndicator } from "react-native";
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { useQueryClient } from "@tanstack/react-query";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";
import { useRiderProfile } from "@/hooks/queries/useRiderData";
import VehicleDropdown from "@/components/ui/VehicleDropdown";
import { BRAND } from "@/constants/brandColors";

export default function VehicleDetails() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const { data: profile } = useRiderProfile();
    const queryClient = useQueryClient();

    const { put } = useApiRequest();
    const [plateNo, setPlateNo] = useState(profile?.plate_number || "");
    const [vehicleType, setVehicleType] = useState(profile?.vehicle_type || "");
    const [isSaving, setIsSaving] = useState(false);

    useEffect(() => {
        if (profile) {
            setPlateNo(profile.plate_number || "");
            setVehicleType(profile.vehicle_type || "");
        }
    }, [profile]);

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await put(RiderApiRoutes.UpdateProfile.path, {
                plate_number: plateNo.trim().toUpperCase(),
                vehicle_type: vehicleType.trim().toLowerCase(),
            });
            queryClient.invalidateQueries({ queryKey: ["rider", "profile"] });
            Toast.success("Saved", "Vehicle parameters updated successfully.");
        } catch (error) {
            Toast.error("Error", errorMessage(error, "Could not update vehicle profile."));
        } finally {
            setIsSaving(false);
        }
    };

    const InputField = ({ label, value, onChangeText, placeholder }: any) => (
        <View className="mb-6">
            <Text className={`font-sans-semibold mb-2 text-base ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                {label}
            </Text>
            <View className={`px-4 py-4 rounded-2xl border ${darkTheme ? "bg-gray-900 border-gray-800" : "bg-white border-gray-200"}`}>
                <TextInput
                    value={value}
                    onChangeText={onChangeText}
                    className={`text-lg ${darkTheme ? "text-white" : "text-black"}`}
                    placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                    placeholder={placeholder}
                    autoCapitalize="characters"
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
                    <TouchableOpacity onPress={() => router.back()} className="mr-4">
                        <BackButtonMinimal />
                    </TouchableOpacity>
                    <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                        Vehicle Details
                    </Text>
                </View>
            </View>
            <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 120 }}>
                <InputField 
                    label="Plate Number / Registration" 
                    value={plateNo} 
                    onChangeText={setPlateNo} 
                    placeholder="e.g. KDG 123X"
                />
                
                <VehicleDropdown 
                    label="Vehicle Type" 
                    value={vehicleType} 
                    onValueChange={setVehicleType} 
                    containerStyle={{ width: "100%", maxWidth: "100%", marginBottom: 24 }}
                />

                <PressableScale activeOpacity={0.8} onPress={handleSave} disabled={isSaving}>
                    <View className={`mt-6 py-4 rounded-2xl items-center shadow-sm ${isSaving ? "opacity-70" : "opacity-100"}`} style={{ backgroundColor: BRAND.primary }}>
                        {isSaving ? (
                            <ActivityIndicator color={BRAND.white} />
                        ) : (
                            <Text className="text-white text-lg font-sans-bold">Update Registration</Text>
                        )}
                    </View>
                </PressableScale>
            </ScrollView>
        </SafeAreaView>
    );
}
