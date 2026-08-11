import React, { useContext, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, ScrollView, ActivityIndicator, KeyboardAvoidingView, Platform, TouchableOpacity } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { errorMessage } from "@/API/errors";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import * as Location from "expo-location";
import { BRAND } from "@/constants/brandColors";
import { useUpdateVendorProfile, useVendorProfile } from "@/hooks/queries/useVendorProfile";

export default function StoreProfile() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    // Every field on this screen belongs to the store profile. It used to read
    // them off the dashboard response, which returns none of them — so the form
    // opened blank and "saving" it wrote empty strings over the vendor's real
    // business name, licence and phone number.
    const { data: vendorProfile, isLoading: dashLoading } = useVendorProfile();
    const updateProfile = useUpdateVendorProfile();
    
    const isStaff = vendorProfile?.role === "staff";

    const [isEditing, setIsEditing] = useState(false);
    const [businessName, setBusinessName] = useState(vendorProfile?.business_name || "");
    const [ownersName, setOwnersName] = useState(vendorProfile?.owners_name || "");
    const [phone, setPhone] = useState(vendorProfile?.phone_number || "");
    const [businessLicense, setBusinessLicense] = useState(vendorProfile?.business_license || "");
    const [depositFee, setDepositFee] = useState(vendorProfile?.deposit_fee?.toString() || "");
    const [vendorType, setVendorType] = useState(vendorProfile?.vendor_type || "retail_refill");

    React.useEffect(() => {
        if (vendorProfile && !isEditing) {
            setBusinessName(vendorProfile.business_name || "");
            setOwnersName(vendorProfile.owners_name || "");
            setPhone(vendorProfile.phone_number || "");
            setBusinessLicense(vendorProfile.business_license || "");
            setDepositFee(vendorProfile.deposit_fee?.toString() || "");
            setVendorType(vendorProfile.vendor_type || "retail_refill");
        }
    }, [vendorProfile, isEditing]);
    
    // Location state
    const [locationData, setLocationData] = useState<{lat: number, lng: number, address: string} | null>(null);
    const [fetchingLocation, setFetchingLocation] = useState(false);
    const [manualAddress, setManualAddress] = useState("");
    const [showManualEntry, setShowManualEntry] = useState(false);
    
    const [isSaving, setIsSaving] = useState(false);

    const getLocation = async () => {
        setFetchingLocation(true);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        try {
            const { status } = await Location.requestForegroundPermissionsAsync();
            if (status !== 'granted') {
                Toast.error("Permission Denied", "We need location access to map your store. Please enable it in Settings.");
                setShowManualEntry(true);
                setFetchingLocation(false);
                return;
            }

            let coords: { latitude: number; longitude: number } | null = null;
            try {
                const current = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
                coords = current.coords;
            } catch (_e1) {
                if (__DEV__) console.warn("Tier 1 (High) GPS failed, trying Low...");
            }

            if (!coords) {
                try {
                    const current = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Low });
                    coords = current.coords;
                } catch (_e2) {
                    if (__DEV__) console.warn("Tier 2 (Low) GPS failed, trying last known...");
                }
            }

            if (!coords) {
                try {
                    const lastKnown = await Location.getLastKnownPositionAsync();
                    if (lastKnown) {
                        coords = lastKnown.coords;
                    }
                } catch (_e3) {
                    if (__DEV__) console.warn("Tier 3 (LastKnown) also failed.");
                }
            }

            if (!coords) {
                Toast.error("GPS Unavailable", "Could not get your position. Please enter your address manually below.");
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

    const handleManualLocation = async () => {
        if (!manualAddress || manualAddress.length < 5) {
            return Toast.error("Required", "Please enter a valid store address.");
        }
        
        setFetchingLocation(true);
        try {
            const geocodeResponse = await Location.geocodeAsync(manualAddress);
            if (geocodeResponse.length > 0) {
                const { latitude, longitude } = geocodeResponse[0];
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                setLocationData({ lat: latitude, lng: longitude, address: manualAddress });
                Toast.success("Address Saved", manualAddress);
            } else {
                Toast.error("Location Not Found", "Could not pinpoint this address. Please be more specific (e.g., add city/country).");
                Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            }
        } catch (error) {
            Toast.error("Geocoding Error", "Failed to resolve address to map coordinates.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        } finally {
            setFetchingLocation(false);
        }
    };

    const handleSave = async () => {
        if (!businessName.trim() || !ownersName.trim()) {
            Toast.error("Validation Error", "Store Name and Owner Name cannot be empty.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return;
        }

        const phoneRegex = /^(?:\+254|0)[17]\d{8}$/; 
        if (phone.trim() && !phoneRegex.test(phone.trim())) {
            Toast.error("Invalid Phone", "Please enter a valid Kenyan phone number.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return;
        }

        if (isStaff) {
            Toast.error("Access Denied", "Staff members cannot edit business information.");
            return;
        }

        if (depositFee.trim() && isNaN(Number(depositFee.trim()))) {
            Toast.error("Invalid Input", "Deposit fee must be a valid number.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return;
        }

        setIsSaving(true);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

        try {
            const payload: any = {
                business_name: businessName.trim(),
                owners_name: ownersName.trim(),
                phone_number: phone.trim() || null,
                business_license: businessLicense.trim() || null,
                vendor_type: vendorType,
            };

            if (depositFee.trim()) {
                payload.deposit_fee = Number(depositFee.trim());
            }

            if (locationData) {
                payload.lat = locationData.lat;
                payload.lng = locationData.lng;
                payload.location_address = locationData.address;
            }

            await updateProfile.mutateAsync(payload);
            Toast.success("Saved", "Store Profile updated successfully.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            setIsEditing(false);
        } catch (error: unknown) {
            // Owner-only, and the deposit-fee range check answers with the
            // permitted bounds. Both were previously flattened to
            // "Check your connection and try again."
            Toast.error("Update Failed", errorMessage(error, "Unable to update profile."));
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        } finally {
            setIsSaving(false);
        }
    };

    const shadowStyle = darkTheme 
        ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } 
        : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 };

    const InfoRow = ({ label, value, stateVal, setStateVal, placeholder, editable = true, keyboardType = "default" }: any) => (
        <View className={`flex-row justify-between py-3 border-b ${darkTheme ? "border-slate-800/80" : "border-gray-100"}`}>
            <Text className={`w-1/3 mt-3 text-sm font-sans-semibold ${darkTheme ? "text-slate-400" : "text-gray-500"}`}>{label}</Text>
            {isEditing && editable ? (
                <TextInput
                    value={stateVal}
                    onChangeText={setStateVal}
                    placeholder={placeholder || `Enter ${label}`}
                    placeholderTextColor={darkTheme ? "#666" : "#999"}
                    keyboardType={keyboardType}
                    className={`w-[60%] p-3 rounded-xl border ${darkTheme ? "bg-white/5 border-white/10 text-white" : "bg-white border-gray-200 text-gray-900"}`}
                />
            ) : (
                <Text className={`flex-1 mt-3 font-sans-semibold text-right ${darkTheme ? "text-slate-200" : "text-gray-900"} ${!editable && isEditing ? "opacity-50" : ""}`}>{value || "—"}</Text>
            )}
        </View>
    );

    const OperationsCard = ({ title, desc, icon, href, color }: any) => (
        <PressableScale onPress={() => router.push(href)} activeOpacity={0.7} className="mb-3">
            <View className={`rounded-2xl p-4 flex-row items-center border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`} style={shadowStyle}>
                <View className={`p-3 rounded-full mr-4 ${darkTheme ? "bg-blue-900/40" : "bg-blue-50"}`}>
                    <Ionicons name={icon} size={26} color={color || BRAND.primary} />
                </View>
                <View className="flex-1">
                    <Text className={`text-base font-sans-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>{title}</Text>
                    <Text className={`text-xs mt-0.5 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>{desc}</Text>
                </View>
                <Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
            </View>
        </PressableScale>
    );

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
                            ...shadowStyle
                        }}
                    >
                        <PressableScale onPress={() => router.back()} className="mr-4">
                            <BackButtonMinimal />
                        </PressableScale>
                        <Text className={`text-xl font-sans-bold flex-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                            Store Profile
                        </Text>
                    </View>
                </View>
                
                <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 120 }} showsVerticalScrollIndicator={false}>
                    
                    {dashLoading ? (
                        // Skeletons correctly shaped
                        <View className="animate-pulse">
                            <View className={`h-6 w-1/2 rounded-md mb-4 ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                            <View className={`rounded-2xl p-4 mb-8 ${darkTheme ? "bg-white/5" : "bg-white border border-gray-100"}`}>
                                <View className={`h-12 border-b mb-1 ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
                                    <View className={`h-4 w-3/4 rounded-md mt-4 ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                                </View>
                                <View className={`h-12 border-b mb-1 ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
                                    <View className={`h-4 w-1/2 rounded-md mt-4 ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                                </View>
                                <View className={`h-12 border-b mb-1 ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
                                    <View className={`h-4 w-2/3 rounded-md mt-4 ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                                </View>
                                <View className={`h-12 border-b mb-1 ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
                                    <View className={`h-4 w-[85%] rounded-md mt-4 ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                                </View>
                            </View>
                            <View className={`h-6 w-1/2 rounded-md mb-4 mt-2 ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                            <View className={`h-[72px] rounded-2xl mb-3 ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                            <View className={`h-[72px] rounded-2xl mb-3 ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                            <View className={`h-[72px] rounded-2xl ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                        </View>
                    ) : (
                        <>
                            <View className="flex-row justify-between items-center mb-4 px-1">
                                <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-gray-900"}`}>Business Information</Text>
                                {!isStaff && (
                                    <PressableScale onPress={() => setIsEditing(!isEditing)} className="px-3 py-1 bg-accentbg/10 rounded-full">
                                        <Text className="text-accentbg font-sans-semibold">{isEditing ? "Cancel" : "Edit"}</Text>
                                    </PressableScale>
                                )}
                            </View>

                            <View className={`rounded-2xl p-4 mb-8 ${darkTheme ? "bg-white/5 border border-white/5" : "bg-white border border-gray-100"} shadow-sm`}>
                                <InfoRow label="Store Name" value={vendorProfile?.business_name} stateVal={businessName} setStateVal={setBusinessName} />
                                <InfoRow label="Owner Name" value={vendorProfile?.owners_name} stateVal={ownersName} setStateVal={setOwnersName} />
                                <InfoRow label="Email Address" value={vendorProfile?.email} editable={false} />
                                <InfoRow label="Phone Number" value={vendorProfile?.phone_number} stateVal={phone} setStateVal={setPhone} keyboardType="phone-pad" placeholder="07XXXXXXXX" />
                                
                                {isEditing ? (
                                    <>
                                        <InfoRow label="Business License" value={vendorProfile?.business_license} stateVal={businessLicense} setStateVal={setBusinessLicense} placeholder="License No" />
                                        <InfoRow label="Deposit Fee" value={vendorProfile?.deposit_fee?.toString()} stateVal={depositFee} setStateVal={setDepositFee} keyboardType="numeric" placeholder="e.g. 500" />
                                        
                                        {/* Vendor Type Selection */}
                                        <View className={`flex-row justify-between py-4 border-b ${darkTheme ? "border-slate-800/80" : "border-gray-100"}`}>
                                            <Text className={`w-1/3 mt-2 text-sm font-sans-semibold ${darkTheme ? "text-slate-400" : "text-gray-500"}`}>Vendor Type</Text>
                                            <View className="w-[60%] flex-row gap-2">
                                                <PressableScale onPress={() => setVendorType("retail_refill")} className={`flex-1 py-2 px-1 items-center justify-center rounded-lg border ${vendorType === "retail_refill" ? (darkTheme ? "bg-accentbg/20 border-accentbg" : "bg-accentbg/10 border-accentbg") : (darkTheme ? "border-gray-700" : "border-gray-300")}`}>
                                                    <Text className={`text-xs font-sans-semibold text-center ${vendorType === "retail_refill" ? (darkTheme ? "text-accenttxt" : "text-accentbg") : (darkTheme ? "text-gray-400" : "text-gray-500")}`}>Retail</Text>
                                                </PressableScale>
                                                <PressableScale onPress={() => setVendorType("wholesale_b2b")} className={`flex-1 py-2 px-1 items-center justify-center rounded-lg border ${vendorType === "wholesale_b2b" ? (darkTheme ? "bg-accentbg/20 border-accentbg" : "bg-accentbg/10 border-accentbg") : (darkTheme ? "border-gray-700" : "border-gray-300")}`}>
                                                    <Text className={`text-xs font-sans-semibold text-center ${vendorType === "wholesale_b2b" ? (darkTheme ? "text-accenttxt" : "text-accentbg") : (darkTheme ? "text-gray-400" : "text-gray-500")}`}>Wholesale</Text>
                                                </PressableScale>
                                            </View>
                                        </View>
                                    </>
                                ) : (
                                    <>
                                        <InfoRow label="Business License" value={vendorProfile?.business_license || "Not Provided"} editable={false} />
                                        <InfoRow label="Vendor Type" value={vendorProfile?.vendor_type === "wholesale_b2b" ? "Wholesale (B2B)" : (vendorProfile?.vendor_type === "retail_refill" ? "Retail Refill" : "N/A")} editable={false} />
                                        <InfoRow label="Deposit Fee" value={vendorProfile?.deposit_fee != null ? `Ksh ${vendorProfile?.deposit_fee}` : "N/A"} editable={false} />
                                        <InfoRow label="Operating Hours" value={vendorProfile?.shift_start && vendorProfile?.shift_end ? `${vendorProfile.shift_start.slice(0, 5)} - ${vendorProfile.shift_end.slice(0, 5)}` : "Not Set"} editable={false} />
                                        <View className="flex-row justify-between pt-3">
                                            <Text className={`w-1/3 mt-3 text-sm font-sans-semibold ${darkTheme ? "text-slate-400" : "text-gray-500"}`}>Location</Text>
                                            <Text className={`flex-1 mt-3 font-sans-semibold text-right ${darkTheme ? "text-slate-200" : "text-gray-900"}`}>{vendorProfile?.location_address || "Not Set"}</Text>
                                        </View>
                                    </>
                                )}
                            </View>

                            {/* Location Update Section - ONLY IF EDITING */}
                            {isEditing && (
                                <View className={`rounded-2xl p-4 mb-8 ${darkTheme ? "bg-white/5 border border-white/5" : "bg-white border border-gray-100"} shadow-sm`}>
                                    <Text className={`text-base font-sans-bold mb-2 ${darkTheme ? "text-white" : "text-gray-800"}`}>
                                        Store Location Update
                                    </Text>
                                    <Text className={`text-xs mb-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                        Ensure riders can find your new warehouse. Current: {vendorProfile?.location_address}
                                    </Text>

                                    <PressableScale
                                        onPress={getLocation}
                                        disabled={fetchingLocation}
                                        className={`h-[55px] rounded-xl items-center justify-center border-2 border-dashed ${darkTheme ? "border-accentbg/50 bg-accentbg/10" : "border-accentbg bg-accentbg/5"}`}
                                    >
                                        {fetchingLocation ? (
                                            <ActivityIndicator color={BRAND.primary} />
                                        ) : (
                                            <View className="flex-row items-center gap-2">
                                                <Ionicons name="location" size={18} color={BRAND.primary} />
                                                <Text className={`font-sans-bold text-base ${darkTheme ? "text-accentbg" : "text-blue-600"}`}>Update via GPS</Text>
                                            </View>
                                        )}
                                    </PressableScale>

                                    {(showManualEntry || locationData) && (
                                        <View className="flex-row items-center my-4">
                                            <View className={`flex-1 h-[1px] ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                                            <Text className={`mx-3 text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>or</Text>
                                            <View className={`flex-1 h-[1px] ${darkTheme ? "bg-white/10" : "bg-gray-200"}`} />
                                        </View>
                                    )}

                                    {showManualEntry && !locationData && (
                                        <View className="gap-3">
                                            <TextInput
                                                className={`h-[55px] px-4 rounded-xl text-base ${darkTheme ? "bg-black text-white border border-white/20" : "bg-white text-black border border-gray-200"}`}
                                                placeholder="e.g. Moi Avenue, Nairobi CBD"
                                                placeholderTextColor={darkTheme ? "#555" : "#A0AEC0"}
                                                value={manualAddress}
                                                onChangeText={setManualAddress}
                                            />
                                            <PressableScale
                                                onPress={handleManualLocation}
                                                disabled={!manualAddress || manualAddress.length < 5}
                                                className={`h-[48px] rounded-xl items-center justify-center ${!manualAddress || manualAddress.length < 5 ? (darkTheme ? "bg-white/5" : "bg-gray-100") : (darkTheme ? "bg-white/10" : "bg-white border border-gray-200")}`}
                                            >
                                                <View className="flex-row items-center gap-2">
                                                    <Ionicons name="pencil" size={14} color={BRAND.primary} />
                                                    <Text className={`font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>Use This Address</Text>
                                                </View>
                                            </PressableScale>
                                        </View>
                                    )}

                                    {locationData && (
                                        <View className={`p-4 mt-2 rounded-xl border ${darkTheme ? "bg-black border-green-900" : "bg-green-50 border-green-200"}`}>
                                            <View className="flex-row items-center gap-2">
                                                <Ionicons name="checkmark-circle" size={20} color={BRAND.primary} />
                                                <Text className={`text-base font-sans-bold ${darkTheme ? "text-green-400" : "text-green-700"}`}>New Location Ready</Text>
                                            </View>
                                            <Text className={`mt-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>{locationData.address}</Text>
                                        </View>
                                    )}
                                </View>
                            )}

                            {isEditing && (
                                <PressableScale activeOpacity={0.8} onPress={handleSave} disabled={isSaving}>
                                    <View className={`py-4 mb-8 rounded-2xl items-center ${isSaving ? "bg-accentbg/50" : "bg-accentbg"}`} style={shadowStyle}>
                                        {isSaving ? (
                                            <ActivityIndicator color={BRAND.white} />
                                        ) : (
                                            <Text className="text-white text-lg font-sans-bold">Save Changes</Text>
                                        )}
                                    </View>
                                </PressableScale>
                            )}

                            {/* Vendor Operations Network Block */}
                            {!isEditing && (
                                <View className="mt-2 mb-4">
                                    <Text className={`mb-4 ml-1 font-sans-bold text-lg ${darkTheme ? "text-white" : "text-gray-800"}`}>Operations & Team</Text>
                                    
                                    {!isStaff && (
                                        <>
                                            <OperationsCard 
                                                title="Operating Hours" 
                                                desc="Set store open and close times" 
                                                icon="time-outline" 
                                                href="/(screens)/business/OperatingHours" 
                                            />
                                            
                                            <OperationsCard 
                                                title="Staff Management" 
                                                desc="Delegate operations to a team member" 
                                                icon="people-outline" 
                                                href="/(screens)/business/ManageStaff" 
                                            />
                                            
                                            <OperationsCard 
                                                title="Payout Settings" 
                                                desc="Configure bank or M-Pesa details" 
                                                icon="card-outline" 
                                                href="/(screens)/business/PayoutSettings" 
                                            />
                                        </>
                                    )}
                                </View>
                            )}
                        </>
                    )}
                </ScrollView>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}
