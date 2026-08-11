import { UIThemeContext } from "@/context/ThemeContext";
import { useAuth, useUser } from "@clerk/clerk-expo";
import { useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import React, { useContext, useEffect, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import {
    ActivityIndicator,
    Image,
    KeyboardAvoidingView,
    Platform,
    ScrollView,
    StatusBar,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Toast } from "@/lib/toast";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { apiFetch } from "@/API/apiFetch";
import { errorMessage } from "@/API/errors";
import PressableScale from "@/components/ui/PressableScale";
import VehicleDropdown from "@/components/ui/VehicleDropdown";
import { BRAND } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
import { RiderOnboardingSkeleton } from "@/components/skeletons/ContextualSkeletons";

export default function RiderOnboarding() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const { getToken, isLoaded } = useAuth();
    const { user } = useUser();
    const router = useRouter();
    const queryClient = useQueryClient();

    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [missingFields, setMissingFields] = useState<string[]>([]);
    
    // Form States
    const [phoneNumber, setPhoneNumber] = useState("");
    const [idNumber, setIdNumber] = useState("");
    const [vehicleType, setVehicleType] = useState("motorbike");
    const [plateNumber, setPlateNumber] = useState("");

    useEffect(() => {
        const checkStatus = async () => {
            try {
                const token = await getToken();
                const data = await apiFetch<{ exists?: boolean; missing_fields?: string[] }>(
                    RiderApiRoutes.ProfileStatus.path, { token }
                );
                if (!data.exists || (data.missing_fields && data.missing_fields.length > 0)) {
                    setMissingFields(data.missing_fields ?? []);
                } else {
                    router.replace("/(screens)");
                }
            } catch (error) {
                if (__DEV__) console.warn("Failed to check profile status:", errorMessage(error));
            } finally {
                setLoading(false);
            }
        };
        if (isLoaded) {
            checkStatus();
        }
    }, [isLoaded]);

    const handleSubmit = async () => {
        // The UI shows a fixed "+254" prefix and only collects the 9-digit local part
        // (e.g. "712345678"), so validate that shape specifically.
        const localPhoneDigits = phoneNumber.replace(/\D/g, "");
        if (missingFields.includes("phone_number") && (!localPhoneDigits || !/^[17]\d{8}$/.test(localPhoneDigits))) {
            return Toast.error("Required", "Please enter a valid 9-digit phone number (e.g. 712345678)");
        }
        if (missingFields.includes("ID_number") && !idNumber) {
            return Toast.error("Required", "Please enter your National ID");
        }
        const needsVehicle = missingFields.includes("vehicle_type") || missingFields.includes("plate_number");
        if (needsVehicle && !plateNumber) {
            return Toast.error("Required", "Please enter your Vehicle License Plate");
        }

        setSubmitting(true);
        try {
            const token = await getToken();
            const payload: any = {
                clerk_id: user?.id,
                name: user?.fullName || "Rider",
                email: user?.emailAddresses[0]?.emailAddress || "",
                profile_pic: user?.imageUrl || ""
            };

            // Prepend the country code the UI implies but never actually sent — the raw
            // 9-digit string doesn't match the backend's sanitize_phone_number() rules
            // (it only normalizes "0XXXXXXXXX" or "254XXXXXXXXX"), so it was being stored
            // unchanged and unusable for M-Pesa payouts, SMS, and tap-to-call.
            if (phoneNumber) payload.phone_number = `+254${localPhoneDigits}`;
            if (idNumber) payload.ID_number = idNumber;
            if (needsVehicle) {
                payload.vehicle_type = vehicleType;
                payload.plate_number = plateNumber;
            }

            await apiFetch(RiderApiRoutes.Register.path, { method: "POST", token, body: payload });
            Toast.success("Success", "Welcome to Drop Riders!");
            queryClient.invalidateQueries({ queryKey: ['rider'] });
            router.replace("/(screens)");
        } catch (error) {
            // A 422 here names the field that failed — "ID_number is required",
            // "phone_number is not a valid Kenyan number" — which is the whole
            // point of the form. "Network error occurred" was never true.
            Toast.error("Error", errorMessage(error, "Registration failed"));
        } finally {
            setSubmitting(false);
        }
    };

    if (loading) {
        return (
            <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}>
                <StatusBar barStyle={darkTheme ? "light-content" : "dark-content"} backgroundColor="transparent" translucent />
                <RiderOnboardingSkeleton />
            </SafeAreaView>
        );
    }

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}>
            <StatusBar
                barStyle={darkTheme ? "light-content" : "dark-content"}
                backgroundColor="transparent"
                translucent
            />
            <KeyboardAvoidingView
                behavior={Platform.OS === "ios" ? "padding" : "height"}
                className="flex-1"
            >
                <ScrollView contentContainerStyle={{ padding: 24, paddingBottom: 100 }} showsVerticalScrollIndicator={false}>
                    
                    <View className="mt-8 mb-6 items-center">
                        <Text className={`text-3xl text-center font-heading-semibold mb-3 ${darkTheme ? "text-white" : "text-black"}`}>
                            Rider Registration
                        </Text>
                        <Text className={`mt-3 text-center ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            Complete your rider profile to start delivering orders.
                        </Text>
                    </View>

                    <View className="gap-5">
                        {missingFields.includes("ID_number") && (
                            <View className={`p-5 rounded-3xl ${darkTheme ? "bg-white/5" : "bg-white border border-gray-100"}`}>
                                <Text className={`text-base font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-gray-800"}`}>
                                    National ID Number
                                </Text>
                                <TextInput
                                    className={`h-[55px] px-4 rounded-2xl text-base ${darkTheme ? "bg-black text-white border border-white/20" : "bg-white text-black border border-gray-200"}`}
                                    placeholder="e.g. 12345678"
                                    placeholderTextColor={darkTheme ? "#888" : "#A0AEC0"}
                                    keyboardType="number-pad"
                                    value={idNumber}
                                    onChangeText={setIdNumber}
                                />
                            </View>
                        )}

                        {missingFields.includes("phone_number") && (
                            <View className={`p-5 rounded-3xl ${darkTheme ? "bg-white/5" : "bg-white border border-gray-100"}`}>
                                <Text className={`text-base font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-gray-800"}`}>
                                    Phone Number
                                </Text>
                                <View className={`flex-row items-center h-[55px] rounded-2xl px-4 ${darkTheme ? "bg-black border border-white/20" : "bg-white border border-gray-200"}`}>
                                    <Ionicons name="call" size={24} color={BRAND.primary} />
                                    <Text className={`ml-3 mr-1 font-sans-bold ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>+254</Text>
                                    <TextInput
                                        className={`flex-1 h-full ml-1 text-base ${darkTheme ? "text-white" : "text-black"}`}
                                        placeholder="712345678"
                                        placeholderTextColor={darkTheme ? "#888" : "#A0AEC0"}
                                        keyboardType="phone-pad"
                                        value={phoneNumber}
                                        onChangeText={setPhoneNumber}
                                        maxLength={9}
                                    />
                                </View>
                            </View>
                        )}

                        {(missingFields.includes("vehicle_type") || missingFields.includes("plate_number")) && (
                            <View className={`p-5 rounded-3xl ${darkTheme ? "bg-white/5" : "bg-white border border-gray-100"}`}>
                                <Text className={`text-base font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-gray-800"}`}>
                                    Vehicle Details
                                </Text>
                                <View className="mb-4">
                                    <VehicleDropdown
                                        label=""
                                        value={vehicleType}
                                        onValueChange={setVehicleType}
                                        containerStyle={{ width: "100%", maxWidth: "100%" }}
                                    />
                                </View>
                                
                                    <TextInput
                                        className={`h-[55px] px-4 rounded-2xl text-base ${darkTheme ? "bg-black text-white border border-white/20" : "bg-white text-black border border-gray-200"}`}
                                        placeholder="License Plate (e.g. KCA 123A)"
                                        placeholderTextColor={darkTheme ? "#888" : "#A0AEC0"}
                                        autoCapitalize="characters"
                                        value={plateNumber}
                                        onChangeText={setPlateNumber}
                                    />
                            </View>
                        )}
                    </View>

                    <PressableScale
                        onPress={handleSubmit}
                        disabled={submitting}
                        className={`mt-10 h-[55px] rounded-full items-center justify-center ${submitting ? "bg-accentbg/50" : "bg-accentbg"}`}
                    >
                        {submitting ? (
                            <ActivityIndicator color={BRAND.white} />
                        ) : (
                            <Text className="text-white font-sans-bold text-lg">Complete Registration</Text>
                        )}
                    </PressableScale>

                </ScrollView>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}
