import { apiFetch } from "@/API/apiFetch";
import { errorMessage } from "@/API/errors";
import { UIThemeContext } from "@/context/ThemeContext";
import { useAuth, useUser } from "@clerk/clerk-expo";
import { useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import React, { useContext, useEffect, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import {
    Image,
    KeyboardAvoidingView,
    Platform,
    ScrollView,
    StatusBar,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Toast } from "@/lib/toast";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";
import * as Haptics from "expo-haptics";
import { BRAND } from "@/constants/brandColors";
import { VendorOnboardingSkeleton } from "@/components/skeletons/ContextualSkeletons";

export default function VendorOnboarding() {
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
    const [step, setStep] = useState<1 | 2 | 3>(1);
    
    // Step 1: Profile
    const [businessName, setBusinessName] = useState("");
    const [vendorType, setVendorType] = useState("retail_refill");
    
    // Step 2: Contact & Location
    const [phoneNumber, setPhoneNumber] = useState("");
    const [locationData, setLocationData] = useState<{lat: number, lng: number, address: string} | null>(null);
    const [fetchingLocation, setFetchingLocation] = useState(false);
    const [manualAddress, setManualAddress] = useState("");
    const [showManualEntry, setShowManualEntry] = useState(false);

    // Step 3: Operations & KYC
    const [shiftStart, setShiftStart] = useState("07:00");
    const [shiftEnd, setShiftEnd] = useState("19:00");
    const [businessLicense, setBusinessLicense] = useState("");

    // Focus States
    const [focusBusiness, setFocusBusiness] = useState(false);
    const [focusPhone, setFocusPhone] = useState(false);
    const [focusAddress, setFocusAddress] = useState(false);
    const [focusLicense, setFocusLicense] = useState(false);

    const handleFocus = (setter: React.Dispatch<React.SetStateAction<boolean>>) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        setter(true);
    };

    useEffect(() => {
        const checkStatus = async () => {
            try {
                const data = await apiFetch<{ exists: boolean; missing_fields?: string[] }>(
                    VendorApiRoutes.GetProfileStatus.path,
                    { token: await getToken() }
                );
                if (!data.exists || (data.missing_fields && data.missing_fields.length > 0)) {
                    setMissingFields(data.missing_fields ?? []);
                } else {
                    router.replace("/(screens)");
                }
            } catch (error) {
                // Staying on the form is the right failure here: it is the only
                // screen a vendor without a profile can act from, and the fields
                // they fill in are checked again on submit.
                if (__DEV__) console.warn("Failed to check profile status", error);
            } finally {
                setLoading(false);
            }
        };
        if (isLoaded) {
            checkStatus();
        }
    }, [isLoaded]);

    const getLocation = async () => {
        setFetchingLocation(true);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        try {
            const { status } = await Location.requestForegroundPermissionsAsync();
            if (status !== 'granted') {
                Toast.error("Permission Denied", "We need location access to map your store.");
                setShowManualEntry(true);
                setFetchingLocation(false);
                return;
            }

            let coords: { latitude: number; longitude: number } | null = null;
            try {
                const current = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
                coords = current.coords;
            } catch (_e1) {}

            if (!coords) {
                try {
                    const current = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Low });
                    coords = current.coords;
                } catch (_e2) {}
            }

            if (!coords) {
                try {
                    const lastKnown = await Location.getLastKnownPositionAsync();
                    if (lastKnown) coords = lastKnown.coords;
                } catch (_e3) {}
            }

            if (!coords) {
                Toast.error("GPS Unavailable", "Could not get your position. Please enter your address manually.");
                setShowManualEntry(true);
                setFetchingLocation(false);
                return;
            }

            const { latitude, longitude } = coords;

            let address = "Unknown Location";
            try {
                const geocodeResponse = await Location.reverseGeocodeAsync({ latitude, longitude });
                if (geocodeResponse.length > 0) {
                    const place = geocodeResponse[0];
                    address = [place.name, place.street, place.city, place.region].filter(Boolean).join(", ");
                }
            } catch (geocodeError) {
                address = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
            }

            setLocationData({ lat: latitude, lng: longitude, address });
            setShowManualEntry(false);
            Toast.success("Location Found", address);
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        } catch (e) {
            Toast.error("Location Error", "GPS failed. Please enter your address manually.");
            setShowManualEntry(true);
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        } finally {
            setFetchingLocation(false);
        }
    };

    const handleManualLocation = () => {
        if (!manualAddress || manualAddress.length < 5) {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return Toast.error("Required", "Please enter a valid store address.");
        }
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        setLocationData({ lat: -1.2921, lng: 36.8219, address: manualAddress });
        Toast.success("Address Saved", manualAddress);
    };

    const handleStep1Next = () => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        if (!businessName) {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return Toast.error("Required", "Please enter your business name");
        }
        setStep(2);
    };

    const handleStep2Next = () => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        if (!phoneNumber || phoneNumber.length < 9) {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return Toast.error("Required", "Please enter a valid phone number");
        }
        if (!locationData) {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return Toast.error("Required", "Please pinpoint your store location");
        }
        setStep(3);
    };

    const handleSubmit = async () => {
        setSubmitting(true);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            const token = await getToken();
            const payload: any = {
                clerk_id: user?.id,
                owners_name: user?.fullName || "",
                business_name: businessName,
                email: user?.emailAddresses[0]?.emailAddress || "",
                vendor_type: vendorType,
                profile_pic: user?.imageUrl || "",
                phone_number: phoneNumber,
                shift_start: `${shiftStart}:00`,
                shift_end: `${shiftEnd}:00`
            };

            if (locationData) {
                payload.lat = locationData.lat;
                payload.lng = locationData.lng;
                payload.location_address = locationData.address;
            }

            if (businessLicense) {
                payload.business_license = businessLicense;
            }

            await apiFetch(VendorApiRoutes.Register.path, {
                method: "POST",
                token,
                body: payload,
            });

            Toast.success("Success", "Welcome to Drop Vendor!");
            queryClient.invalidateQueries({ queryKey: ['vendor'] });
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            router.replace("/(screens)");
        } catch (error) {
            // Registration fails on real, fixable things — a duplicate email, a
            // malformed phone number. "Network error occurred" told the vendor
            // to retry the same rejected form.
            Toast.error("Error", errorMessage(error, "Registration failed"));
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        } finally {
            setSubmitting(false);
        }
    };

    if (loading) {
        return (
            <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
                <StatusBar barStyle={darkTheme ? "light-content" : "dark-content"} backgroundColor="transparent" translucent />
                <VendorOnboardingSkeleton />
            </SafeAreaView>
        );
    }

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <StatusBar
                barStyle={darkTheme ? "light-content" : "dark-content"}
                backgroundColor="transparent"
                translucent
            />
            <KeyboardAvoidingView
                behavior={Platform.OS === "ios" ? "padding" : "height"}
                className="flex-1"
            >
                {/* Progress Indicator */}
                <View className="px-6 pt-4 pb-2">
                    <View className="flex-row items-center justify-between mb-2">
                        {step > 1 ? (
                            <PressableScale accessibilityLabel="Go back a step" onPress={() => setStep((step - 1) as 1|2|3)} className="w-10 h-10 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
                                <Ionicons name="arrow-back" size={20} color={darkTheme ? "#fff" : "#000"} />
                            </PressableScale>
                        ) : (
                            <View className="w-10 h-10" />
                        )}
                        <Text className={`font-sans-bold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            Step {step} of 3
                        </Text>
                        <View className="w-10 h-10" />
                    </View>
                    <View className="flex-row gap-2 h-1.5">
                        <View className={`flex-1 rounded-full ${step >= 1 ? "bg-primary" : (darkTheme ? "bg-gray-800" : "bg-white")}`} />
                        <View className={`flex-1 rounded-full ${step >= 2 ? "bg-primary" : (darkTheme ? "bg-gray-800" : "bg-white")}`} />
                        <View className={`flex-1 rounded-full ${step >= 3 ? "bg-primary" : (darkTheme ? "bg-gray-800" : "bg-white")}`} />
                    </View>
                </View>

                <ScrollView contentContainerStyle={{ padding: 24, paddingBottom: 100 }} showsVerticalScrollIndicator={false}>
                    
                    <View className="mb-8 mt-2 items-center">
                        <Text className={`text-3xl text-center font-heading-semibold mb-3 ${darkTheme ? "text-white" : "text-black"}`}>
                            {step === 1 ? "Set Up Your Store" : step === 2 ? "Contact & Location" : "Operations & KYC"}
                        </Text>
                        <Text className={`text-center px-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            {step === 1 
                                ? "Complete your vendor profile to start receiving orders locally." 
                                : step === 2 ? "Delivery radiuses are restricted based on location. Where is your warehouse?"
                                : "Add operating hours and business verification to complete setup."}
                        </Text>
                    </View>

                    {step === 1 && (
                        <View className="gap-6">
                            <View className="items-center mb-4">
                                <View className="relative">
                                    <Image 
                                        source={{ uri: user?.imageUrl || "https://ui-avatars.com/api/?name=Store&background=0295f7&color=fff" }} 
                                        className="w-24 h-24 rounded-full border-4 border-primary"
                                    />
                                    <View className="absolute bottom-0 right-0 bg-primary p-2 rounded-full border-2 border-white dark:border-black">
                                        <Ionicons name="camera" size={16} color="white" />
                                    </View>
                                </View>
                                <Text className={`mt-3 font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Store Profile Photo</Text>
                            </View>

                            <View>
                                <Text className={`text-base font-sans-bold mb-2 ${darkTheme ? "text-white" : "text-gray-800"}`}>
                                    Business Details
                                </Text>
                                <View className={`h-[55px] px-4 rounded-2xl border-2 justify-center ${focusBusiness ? "border-primary bg-primary/5" : (darkTheme ? "border-white/10 bg-black" : "border-gray-200 bg-white")}`}>
                                    <TextInput
                                        className={`text-base font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}
                                        placeholder="Business / Store Name"
                                        placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                        value={businessName}
                                        onChangeText={setBusinessName}
                                        onFocus={() => handleFocus(setFocusBusiness)}
                                        onBlur={() => setFocusBusiness(false)}
                                    />
                                </View>
                            </View>

                            <View>
                                <Text className={`text-base font-sans-bold mb-2 ${darkTheme ? "text-white" : "text-gray-800"}`}>Business Model</Text>
                                <View className="gap-3">
                                    <PressableScale 
                                        onPress={() => {
                                            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                            setVendorType("retail_refill");
                                        }}
                                        className={`flex-row items-center p-4 rounded-2xl border-2 ${vendorType === "retail_refill" ? "border-primary bg-primary/5" : (darkTheme ? "border-white/10 bg-black" : "border-gray-200 bg-white")}`}
                                    >
                                        <View className={`w-12 h-12 rounded-xl items-center justify-center ${vendorType === "retail_refill" ? "bg-primary/20" : (darkTheme ? "bg-white/10" : "bg-white")}`}>
                                            <Ionicons name="water" size={24} color={vendorType === "retail_refill" ? "#0295f7" : (darkTheme ? "#888" : "#9CA3AF")} />
                                        </View>
                                        <View className="flex-1 ml-4">
                                            <Text className={`text-base font-sans-bold ${vendorType === "retail_refill" ? "text-primary" : (darkTheme ? "text-white" : "text-gray-800")}`}>
                                                Retail Refill Station
                                            </Text>
                                            <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-500" : "text-gray-500"}`}>
                                                Sell directly to consumers
                                            </Text>
                                        </View>
                                        {vendorType === "retail_refill" && (
                                            <Ionicons name="checkmark-circle" size={24} color={BRAND.primary} />
                                        )}
                                    </PressableScale>

                                    <PressableScale 
                                        onPress={() => {
                                            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                            setVendorType("wholesale_b2b");
                                        }}
                                        className={`flex-row items-center p-4 rounded-2xl border-2 ${vendorType === "wholesale_b2b" ? "border-primary bg-primary/5" : (darkTheme ? "border-white/10 bg-black" : "border-gray-200 bg-white")}`}
                                    >
                                        <View className={`w-12 h-12 rounded-xl items-center justify-center ${vendorType === "wholesale_b2b" ? "bg-primary/20" : (darkTheme ? "bg-white/10" : "bg-white")}`}>
                                            <Ionicons name="cube" size={24} color={vendorType === "wholesale_b2b" ? "#0295f7" : (darkTheme ? "#888" : "#9CA3AF")} />
                                        </View>
                                        <View className="flex-1 ml-4">
                                            <Text className={`text-base font-sans-bold ${vendorType === "wholesale_b2b" ? "text-primary" : (darkTheme ? "text-white" : "text-gray-800")}`}>
                                                Wholesale / B2B
                                            </Text>
                                            <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-500" : "text-gray-500"}`}>
                                                Bulk supply to offices & vendors
                                            </Text>
                                        </View>
                                        {vendorType === "wholesale_b2b" && (
                                            <Ionicons name="checkmark-circle" size={24} color={BRAND.primary} />
                                        )}
                                    </PressableScale>
                                </View>
                            </View>

                            <PressableScale onPress={handleStep1Next} className={`mt-4 h-[55px] rounded-2xl items-center justify-center bg-primary`}>
                                <Text className="text-white font-sans-bold text-lg">Next Step</Text>
                            </PressableScale>
                        </View>
                    )}

                    {step === 2 && (
                        <View className="gap-6">
                            <View>
                                <Text className={`text-base font-sans-bold mb-2 ${darkTheme ? "text-white" : "text-gray-800"}`}>
                                    Phone Number
                                </Text>
                                <View className={`flex-row items-center h-[55px] rounded-2xl px-4 border-2 ${focusPhone ? "border-primary bg-primary/5" : (darkTheme ? "bg-black border-white/10" : "bg-white border-gray-200")}`}>
                                    <Ionicons name="call" size={20} color={darkTheme ? "#888" : "#9CA3AF"} />
                                    <Text className={`ml-3 mr-1 font-sans-bold ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>+254</Text>
                                    <TextInput
                                        className={`flex-1 h-full ml-1 text-base font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}
                                        placeholder="712345678"
                                        placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                        keyboardType="phone-pad"
                                        value={phoneNumber}
                                        onChangeText={setPhoneNumber}
                                        onFocus={() => handleFocus(setFocusPhone)}
                                        onBlur={() => setFocusPhone(false)}
                                        maxLength={10}
                                    />
                                </View>
                            </View>

                            <PressableScale
                                onPress={getLocation}
                                disabled={fetchingLocation}
                                className={`h-[60px] rounded-2xl items-center justify-center border-2 border-dashed ${darkTheme ? "border-primary/50 bg-primary/10" : "border-primary bg-primary/5"}`}
                            >
                                {fetchingLocation ? (
                                    <Ionicons name="sync" size={24} color={BRAND.primary} />
                                ) : (
                                    <View className="flex-row items-center gap-2">
                                        <Ionicons name="location" size={20} color={darkTheme ? "#0295f7" : "#0295f7"} />
                                        <Text className={`font-sans-bold text-lg ${darkTheme ? "text-primary" : "text-primary"}`}>Auto-Detect GPS Location</Text>
                                    </View>
                                )}
                            </PressableScale>

                            <View className="flex-row items-center">
                                <View className={`flex-1 h-[1px] ${darkTheme ? "bg-white/10" : "bg-white"}`} />
                                <Text className={`mx-4 text-xs font-sans-bold ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>OR</Text>
                                <View className={`flex-1 h-[1px] ${darkTheme ? "bg-white/10" : "bg-white"}`} />
                            </View>

                            <View>
                                <Text className={`text-base font-sans-bold mb-2 ${darkTheme ? "text-white" : "text-gray-800"}`}>Manual Address</Text>
                                <View className="gap-3">
                                    <View className={`h-[55px] px-4 rounded-2xl border-2 justify-center ${focusAddress ? "border-primary bg-primary/5" : (darkTheme ? "border-white/10 bg-black" : "border-gray-200 bg-white")}`}>
                                        <TextInput
                                            className={`text-base font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}
                                            placeholder="e.g. Moi Avenue, Nairobi CBD"
                                            placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                            value={manualAddress}
                                            onChangeText={setManualAddress}
                                            onFocus={() => handleFocus(setFocusAddress)}
                                            onBlur={() => setFocusAddress(false)}
                                        />
                                    </View>
                                    <PressableScale
                                        onPress={handleManualLocation}
                                        disabled={!manualAddress || manualAddress.length < 5}
                                        className={`h-[48px] rounded-2xl items-center justify-center ${!manualAddress || manualAddress.length < 5 ? (darkTheme ? "bg-white/5" : "bg-white") : (darkTheme ? "bg-white/10" : "bg-white")}`}
                                    >
                                        <View className="flex-row items-center gap-2">
                                            <Ionicons name="pencil" size={16} color={darkTheme ? "#888" : "#6B7280"} />
                                            <Text className={`font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>Use This Address</Text>
                                        </View>
                                    </PressableScale>
                                </View>
                            </View>

                            {locationData && (
                                <View className={`p-4 rounded-xl border ${darkTheme ? "bg-black border-green-900" : "bg-green-50 border-green-200"}`}>
                                    <View className="flex-row items-center gap-2">
                                        <Ionicons name="checkmark-circle" size={20} color={darkTheme ? "#4ade80" : "#16a34a"} />
                                        <Text className={`text-base font-sans-bold ${darkTheme ? "text-green-400" : "text-green-700"}`}>Location Set!</Text>
                                    </View>
                                    <Text className={`mt-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>{locationData.address}</Text>
                                </View>
                            )}

                            <PressableScale onPress={handleStep2Next} className={`mt-4 h-[55px] rounded-2xl items-center justify-center bg-primary`}>
                                <Text className="text-white font-sans-bold text-lg">Next Step</Text>
                            </PressableScale>
                        </View>
                    )}

                    {step === 3 && (
                        <View className="gap-6">
                            <View>
                                <Text className={`text-base font-sans-bold mb-2 ${darkTheme ? "text-white" : "text-gray-800"}`}>
                                    Operating Hours
                                </Text>
                                <View className="flex-row justify-between items-center">
                                    <View className={`flex-1 h-[55px] px-4 rounded-2xl border-2 justify-center ${darkTheme ? "border-white/10 bg-black" : "border-gray-200 bg-white"}`}>
                                        <Text className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Opens At</Text>
                                        <TextInput
                                            className={`text-base font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}
                                            placeholder="07:00"
                                            placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                            value={shiftStart}
                                            onChangeText={setShiftStart}
                                        />
                                    </View>
                                    <View className="px-4">
                                        <Text className={`font-sans-bold ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>TO</Text>
                                    </View>
                                    <View className={`flex-1 h-[55px] px-4 rounded-2xl border-2 justify-center ${darkTheme ? "border-white/10 bg-black" : "border-gray-200 bg-white"}`}>
                                        <Text className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Closes At</Text>
                                        <TextInput
                                            className={`text-base font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}
                                            placeholder="19:00"
                                            placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                            value={shiftEnd}
                                            onChangeText={setShiftEnd}
                                        />
                                    </View>
                                </View>
                            </View>

                            <View>
                                <Text className={`text-base font-sans-bold mb-2 ${darkTheme ? "text-white" : "text-gray-800"}`}>
                                    Business License / KRA PIN (Optional)
                                </Text>
                                <View className={`h-[55px] px-4 rounded-2xl border-2 justify-center ${focusLicense ? "border-primary bg-primary/5" : (darkTheme ? "border-white/10 bg-black" : "border-gray-200 bg-white")}`}>
                                    <TextInput
                                        className={`text-base font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}
                                        placeholder="e.g. A012345678Z"
                                        placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                        value={businessLicense}
                                        onChangeText={setBusinessLicense}
                                        onFocus={() => handleFocus(setFocusLicense)}
                                        onBlur={() => setFocusLicense(false)}
                                    />
                                </View>
                                <Text className={`text-xs mt-2 ${darkTheme ? "text-gray-500" : "text-gray-500"}`}>
                                    Providing a valid license or tax PIN helps us verify your store faster and builds trust with customers.
                                </Text>
                            </View>

                            <PressableScale
                                onPress={handleSubmit}
                                disabled={submitting}
                                className={`mt-4 h-[55px] rounded-2xl items-center justify-center ${submitting ? "bg-primary/50" : "bg-primary"}`}
                            >
                                {submitting ? (
                                    <Ionicons name="sync" size={32} color={BRAND.white} />
                                ) : (
                                    <Text className="text-white font-sans-bold text-lg">Complete Registration</Text>
                                )}
                            </PressableScale>
                        </View>
                    )}
                </ScrollView>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}
