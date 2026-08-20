import { errorMessage } from "@/API/errors";
import { useTabBarClearance } from '@/constants/layout';
import React, { useContext } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, ScrollView } from "react-native";
import { Text } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { useQueryClient } from "@tanstack/react-query";
import { useUserDetails } from "@/hooks/queries/useUser";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";
import { useSavedLocations, useDeleteSavedLocation, useSelectSavedLocation, useRevokeLocation } from "@/hooks/queries/useSavedLocations";
import PressableScale from "@/components/ui/PressableScale";
import { SavedLocationSkeleton } from "@/components/skeletons/ContextualSkeletons";

export default function SavedLocations() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const queryClient = useQueryClient();
    const { data: User } = useUserDetails();

    const { data: savedLocations = [], isLoading } = useSavedLocations();
    const deleteSavedLocation = useDeleteSavedLocation();
    const selectSavedLocation = useSelectSavedLocation();
    const revokeLocation = useRevokeLocation();

    // Helper: check if a saved location matches the current active user location
    const isLocationActive = (loc: import("@/types/models").SavedLocation): boolean => {
        if (!User?.location_address || !loc?.address) return false;
        // Primary match: exact address string comparison
        if (loc.address === User.location_address) return true;
        // Fallback match: coordinate comparison
        if (User?.lat != null && User?.lng != null && loc.lat != null && loc.lng != null) {
            const latMatch = Math.abs(User.lat - loc.lat) < 0.0001;
            const lngMatch = Math.abs(User.lng - loc.lng) < 0.0001;
            if (latMatch && lngMatch) return true;
        }
        return false;
    };

    const handleSelect = async (loc: import("@/types/models").SavedLocation) => {
        try {
            await selectSavedLocation.mutateAsync(loc.id);
            queryClient.invalidateQueries({ queryKey: ['user', 'details'] });
            Toast.success("Location Updated", `Delivering to ${loc.address}`);
        } catch (e: unknown) {
            Toast.error("Couldn't use location", errorMessage(e, "Could not select location."));
        }
    };

    const handleDelete = (loc: import("@/types/models").SavedLocation) => {
        Popup.show({
            title: "Delete Location",
            message: `Remove "${loc.label || loc.address}"?`,
            cancelText: "Cancel",
            confirmText: "Delete",
            isDestructive: true,
            onConfirm: async () => {
                Popup.setLoading(true);
                try {
                    await deleteSavedLocation.mutateAsync(loc.id);
                    if (isLocationActive(loc)) {
                        await revokeLocation.mutateAsync();
                    }
                    Toast.success("Deleted", "Location removed.");
                } catch (e: unknown) {
                    Toast.error("Couldn't delete location", errorMessage(e, "Please try again."));
                } finally {
                    Popup.hide();
                }
            }
        });
    };

    const handleAddNew = () => {
        // Navigate to Map screen in setLocation mode using current coordinates or default
        if (User?.lat && User?.lng) {
            const id = `lat=${User.lat}|lng=${User.lng}|mode=setLocation`;
            router.push({ pathname: "/(screens)/Map/[id]", params: { id } });
        } else {
            const id = `lat=-1.2921|lng=36.8219|mode=setLocation`;
            router.push({ pathname: "/(screens)/Map/[id]", params: { id } });
        }
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
    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
}}
            >
                <PressableScale onPress={() => router.back()} className="mr-4">
                    <BackButtonMinimal />
                </PressableScale>
                <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                    Saved Locations
                </Text>
            </View>
            </View>

            <ScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 16, paddingBottom: tabBarClearance }}>
                {/* Current Active Location */}
                <View className={`p-4 mb-4 rounded-2xl border ${darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white"}`}>
                    <View className="flex-row justify-between items-start mb-1">
                        <Text className={`text-sm font-sans-bold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>CURRENT DELIVERY ADDRESS</Text>
                        <View className="px-2 py-1 rounded-md ml-2 bg-accentbg/10">
                            <Text className="text-accentbg font-sans-bold text-xs">ACTIVE</Text>
                        </View>
                    </View>
                    <Text className={`text-base font-sans-medium leading-6 ${darkTheme ? "text-white" : "text-gray-900"}`}>
                        {User?.location_address || "No location set. Tap '+' to add one."}
                    </Text>
                </View>

                {/* Saved Locations List */}
                {isLoading ? (
                    <View className="mt-4 gap-2">
                        <SavedLocationSkeleton />
                        <SavedLocationSkeleton />
                    </View>
                ) : savedLocations.length === 0 ? (
                    <View className="items-center pt-10 gap-3">
                        <Text className="text-3xl">📍</Text>
                        <Text className={`text-base font-sans-medium ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>No saved locations yet</Text>
                        <Text className={`text-sm text-center max-w-[250px] ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                            Save your frequently used addresses for faster checkout.
                        </Text>
                    </View>
                ) : (
                    <View className="gap-3">
                        <Text className={`text-xs font-sans-semibold uppercase tracking-wider mb-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                            Your Addresses ({savedLocations.length})
                        </Text>
                        {savedLocations.map((loc: import("@/types/models").SavedLocation) => (
                            <PressableScale
                                key={loc.id}
                                onPress={() => handleSelect(loc)}
                            >
                                <View className={`flex-row items-center p-4 rounded-xl ${darkTheme ? "bg-white/5" : "bg-white"} border ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
                                    <View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${darkTheme ? "bg-white/10" : "bg-white"}`}>
                                        <Text className="text-lg">{loc.label === "Home" ? "🏠" : loc.label === "Work" ? "💼" : "📍"}</Text>
                                    </View>
                                    <View className="flex-1">
                                        {loc.label && (
                                            <Text className={`text-xs font-sans-bold uppercase ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{loc.label}</Text>
                                        )}
                                        <Text numberOfLines={2} className={`text-sm font-sans-medium ${darkTheme ? "text-white" : "text-gray-900"}`}>{loc.address}</Text>
                                        <Text className={`text-xs mt-0.5 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>Used {loc.use_count} time{loc.use_count !== 1 ? "s" : ""}</Text>
                                    </View>
                                    <PressableScale
                                        onPress={() => handleDelete(loc)}
                                        className="ml-2 p-2"
                                        hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                                    >
                                        <Text className="text-red-400 text-xs font-sans-semibold">Remove</Text>
                                    </PressableScale>
                                </View>
                            </PressableScale>
                        ))}
                    </View>
                )}
            </ScrollView>

            {/* Add New Location FAB */}
            {/* `bottom-28` was 112px of guesswork: it clears the floating tab bar
                on a handset with a small gesture area and sits behind it on one
                without. The clearance is the same figure every scroller uses. */}
            <PressableScale
                onPress={handleAddNew}
                className="absolute right-5"
                style={{ bottom: tabBarClearance }}
            >
                <View className="w-14 h-14 rounded-full bg-accentbg items-center justify-center shadow-xl shadow-black/30">
                    <Text className="text-white text-2xl font-sans-bold">+</Text>
                </View>
            </PressableScale>
        </SafeAreaView>
    );
}
