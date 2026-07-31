import { errorMessage } from "@/API/errors";
import React, { useContext, useState } from "react";
import { View, Text, StatusBar, ScrollView, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import * as Location from "expo-location";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { UIThemeContext } from "@/context/ThemeContext";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { PressableScale } from "@/components/ui/PressableScale";
import PlacesAutocomplete from "@/components/map/PlacesAutocomplete";
import { useSavedLocations, useSelectSavedLocation, useRevokeLocation, useDeleteSavedLocation } from "@/hooks/queries/useSavedLocations";
import { useUserDetails } from "@/hooks/queries/useUser";
import { Image } from "expo-image";
import { BRAND } from "@/constants/brandColors";
import { Toast } from "@/lib/toast";
import { SavedLocationSkeleton } from '@/components/skeletons/ContextualSkeletons';
import { Ionicons } from "@expo/vector-icons";


export default function LocationSearch() {
	const router = useRouter();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const insets = useSafeAreaInsets();

	const { data: User } = useUserDetails();
	const { data: savedLocations = [], isLoading: isLoadingSaved } = useSavedLocations();
	const selectSavedLocation = useSelectSavedLocation();
	const revokeLocation = useRevokeLocation();
	const deleteLocation = useDeleteSavedLocation();

	const [isLocating, setIsLocating] = useState(false);
	const [loadingLocationId, setLoadingLocationId] = useState<string | null>(null);

	const isLocationActive = (loc: import("@/types/models").SavedLocation): boolean => {
		if (!User?.location_address || !loc?.address) return false;
		if (loc.address === User.location_address) return true;
		if (User?.lat != null && User?.lng != null && loc.lat != null && loc.lng != null) {
			const latMatch = Math.abs(User.lat - loc.lat) < 0.0001;
			const lngMatch = Math.abs(User.lng - loc.lng) < 0.0001;
			if (latMatch && lngMatch) return true;
		}
		return false;
	};

	const handleSelectLocation = (lat: number, lng: number, address?: string) => {
		if (lat === 0 && lng === 0) {
			Toast.error("Invalid Location", "Cannot route to 0,0.");
			return;
		}
		let id = `lat=${lat}|lng=${lng}|mode=setLocation`;
		if (address) {
			id += `|address=${encodeURIComponent(address)}`;
		}
		router.replace({ pathname: "/(screens)/Map/[id]", params: { id } });
	};

	const handleCurrentLocation = async () => {
		setIsLocating(true);
		try {
			let { status } = await Location.requestForegroundPermissionsAsync();
			if (status !== "granted") {
				Toast.error("Permission Denied", "Location access is required.");
				setIsLocating(false);
				return;
			}
			let location = await Location.getCurrentPositionAsync({});
			handleSelectLocation(location.coords.latitude, location.coords.longitude);
		} catch (error) {
			Toast.error("Location unavailable", "We couldn't read your current position. Check that location services are on and try again.");
		} finally {
			setIsLocating(false);
		}
	};

	const handleUseSavedLocation = async (loc: import("@/types/models").SavedLocation) => {
		if (isLocationActive(loc)) return; 
		setLoadingLocationId(loc.id);
		try {
			await selectSavedLocation.mutateAsync(loc.id);
			Toast.success("Location Updated", `Delivering to ${loc.address}`);
			router.back();
		} catch (e: unknown) {
			Toast.error("Couldn't use location", errorMessage(e, "Could not select location."));
		} finally {
			setLoadingLocationId(null);
		}
	};

	const handleRevokeLocation = async (loc: import("@/types/models").SavedLocation) => {
		setLoadingLocationId(loc.id);
		try {
			await revokeLocation.mutateAsync();
			Toast.success("Cleared", "Location revoked");
		} catch (e: unknown) {
			Toast.error("Couldn't remove location", errorMessage(e, "Please try again."));
		} finally {
			setLoadingLocationId(null);
		}
	};

	const handleDeleteLocation = async (loc: import("@/types/models").SavedLocation) => {
		setLoadingLocationId(loc.id);
		try {
			await deleteLocation.mutateAsync(loc.id);
			if (isLocationActive(loc)) {
				await revokeLocation.mutateAsync();
			}
			Toast.success("Deleted", "Location removed");
		} catch (e: unknown) {
			Toast.error("Couldn't delete location", errorMessage(e, "Please try again."));
		} finally {
			setLoadingLocationId(null);
		}
	};

	const SavedLocationCard = ({ loc, single = false }: { loc: import("@/types/models").SavedLocation, single?: boolean }) => {
		const isActive = isLocationActive(loc);
		const isLoading = loadingLocationId === loc.id;
		
		return (
			<PressableScale
				onPress={() => handleUseSavedLocation(loc)}
				disabled={isLoading || selectSavedLocation.isPending}
			>
				<View className={`flex-row items-center p-4 rounded-2xl border ${darkTheme ? "bg-surface-container" + (single ? " border-accentbg/20" : " border-transparent") : "bg-white" + (single ? " border-accentbg/15 bg-accentbg/5" : " border-gray-200")}`} style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
					<View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${darkTheme ? "bg-surface-variant" : "bg-white"}`}>
						<Text className="text-lg">
							{loc.label === "Home" ? "🏠" : loc.label === "Work" ? "💼" : "📍"}
						</Text>
					</View>
					<View className="flex-1">
						{loc.label && (
							<Text className={`text-sm font-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
								{loc.label}
							</Text>
						)}
						<Text numberOfLines={1} className={`text-xs ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
							{loc.address}
						</Text>
					</View>
					
					{isLoading ? (
						<ActivityIndicator size="small" color={BRAND.primary} />
					) : (
						<View className="flex-row items-center gap-2">
							{isActive ? (
								<PressableScale onPress={(e) => { e.stopPropagation?.(); handleRevokeLocation(loc); }}>
									<View className={`px-3 py-1.5 rounded-full ${darkTheme ? "bg-red-500/20" : "bg-red-100"}`}>
										<Text className={`text-xs font-bold ${darkTheme ? "text-red-400" : "text-red-600"}`}>Revoke</Text>
									</View>
								</PressableScale>
							) : (
								<View className={`px-3 py-1.5 rounded-full ${darkTheme ? "bg-accentbg/10" : "bg-accentbg/10"}`}>
									<Text className={`text-xs font-bold ${darkTheme ? "text-accentbg" : "text-accentbg"}`}>Use</Text>
								</View>
							)}

							<PressableScale onPress={(e) => { e.stopPropagation?.(); handleDeleteLocation(loc); }}>
								<View className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-red-500/10" : "bg-red-50"}`}>
									<Text className="text-red-500 text-lg">×</Text>
								</View>
							</PressableScale>
						</View>
					)}
				</View>
			</PressableScale>
		);
	};

	return (
		<SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`} edges={["top"]}>
			<StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />
			
			<View style={{ overflow: "hidden", paddingBottom: 4, zIndex: 50 }}>
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
						Enter delivery address
					</Text>
				</View>
			</View>

			<View className="px-4 z-40 relative mt-4 mb-4">
				<PlacesAutocomplete
					placeholder="Search for a location..."
					fetchDetails={true}
					language="en"
					components="country:ke"
					minLength={2}
					debounce={300}
					darkTheme={darkTheme}
					onPress={(data, details) => {
						if (details?.geometry?.location) {
							handleSelectLocation(details.geometry.location.lat, details.geometry.location.lng, details.formatted_address);
						}
					}}
					customStyles={{
						textInput: {
							backgroundColor: darkTheme ? "#201f1f" : "#ffffff",
							borderColor: darkTheme ? "transparent" : "#e5e7eb",
							borderWidth: darkTheme ? 0 : 1,
							...(darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
						},
						row: {
							backgroundColor: darkTheme ? "#201f1f" : "#ffffff",
						},
						listView: {
							backgroundColor: darkTheme ? "#201f1f" : "#ffffff",
							borderColor: darkTheme ? "#353534" : "#e5e7eb",
						}
					}}
				/>
			</View>

			<ScrollView 
				className="flex-1" 
				showsVerticalScrollIndicator={false}
				contentContainerStyle={{ paddingBottom: insets.bottom + 20 }}
				keyboardShouldPersistTaps="always"
			>
				<View className="px-4 gap-2">
					<PressableScale onPress={handleCurrentLocation} disabled={isLocating}>
						<View className={`flex-row items-center p-4 rounded-2xl border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"}`} style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
							<View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${darkTheme ? "bg-accentbg/20" : "bg-accentbg/10"}`}>
								{isLocating ? (
									<ActivityIndicator size="small" color={BRAND.primary} />
								) : (
									<Ionicons name="locate" size={24} color={BRAND.primary} />
								)}
							</View>
							<Text className={`text-base font-semibold ${darkTheme ? "text-accenttxt" : "text-accenttxt"}`}>
								Use current location
							</Text>
						</View>
					</PressableScale>

					<PressableScale onPress={() => {
						const fallbackLat = User?.lat || -1.2921;
						const fallbackLng = User?.lng || 36.8219;
						handleSelectLocation(fallbackLat, fallbackLng);
					}}>
						<View className={`flex-row items-center p-4 rounded-2xl border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"}`} style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
							<View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${darkTheme ? "bg-surface-variant" : "bg-white"}`}>
								<Ionicons name="location" size={24} color={BRAND.primary} />
							</View>
							<Text className={`text-base font-semibold ${darkTheme ? "text-on-surface" : "text-gray-800"}`}>
								Choose on map
							</Text>
						</View>
					</PressableScale>
				</View>

				{isLoadingSaved ? (
					<View className="mt-8 px-4">
						<View>
							<SavedLocationSkeleton />
							<SavedLocationSkeleton />
						</View>
					</View>
				) : savedLocations.length === 1 ? (
					<View className="mt-4 px-4">
						<Text className={`text-xs font-bold tracking-wider uppercase mb-2 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
							Quick Select
						</Text>
						<SavedLocationCard loc={savedLocations[0]} single />
					</View>
				) : savedLocations.length > 1 ? (
					<View className="mt-8 px-4">
						<Text className={`text-xs font-bold tracking-wider uppercase mb-3 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
							Saved Places
						</Text>
						<View className="gap-2">
							{savedLocations.map((loc: import("@/types/models").SavedLocation) => (
								<SavedLocationCard key={loc.id} loc={loc} />
							))}
						</View>
					</View>
				) : null}
			</ScrollView>
		</SafeAreaView>
	);
}
