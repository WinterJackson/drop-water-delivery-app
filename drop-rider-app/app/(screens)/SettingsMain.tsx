import React, { useContext, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { 
    View, 
    Text, 
    ScrollView, 
    StatusBar, 
    Dimensions,
    TouchableOpacity,
    ActivityIndicator
} from "react-native";
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { useAuth, useUser } from "@clerk/clerk-expo";
import * as Haptics from "expo-haptics";
import { useQueryClient } from "@tanstack/react-query";
import { useRiderProfile } from "@/hooks/queries/useRiderData";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import UserAvatar from "@/components/ui/UserAvatar";
import { Image } from "expo-image";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { Toast } from "@/lib/toast";
import { BRAND } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import SecureUpload from "@/Helpers/imageUpload";
import { Popup } from "@/lib/popup";
import { RiderSettingsSkeleton } from "@/components/skeletons/ContextualSkeletons";

const { width } = Dimensions.get("window");

export default function SettingsMain() {
    const { currentTheme, setTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const queryClient = useQueryClient();
    const { data: RiderData, isLoading } = useRiderProfile();
    const [isUploadingPic, setIsUploadingPic] = useState(false);
    const { user } = useUser();
    const { signOut, getToken } = useAuth();
    const { clearPushToken } = usePushNotifications();

    const handleUpdateProfilePic = async () => {
        try {
            const result = await ImagePicker.launchImageLibraryAsync({
                mediaTypes: ['images'],
                allowsEditing: true,
                aspect: [1, 1],
                quality: 0.5,
            });

            if (!result.canceled && result.assets && result.assets.length > 0) {
                setIsUploadingPic(true);
                const imageUri = result.assets[0].uri;
                
                // Upload securely to backend S3
                const uploadedData = await SecureUpload(imageUri, `rider_avatar_${user?.id}`, getToken);
                
                if (uploadedData && uploadedData.secure_url) {
                    const secureUrl = uploadedData.secure_url;
                    
                    // Send to backend
                    const res = await fetch(RiderApiRoutes.UpdateProfile.path, {
                        method: RiderApiRoutes.UpdateProfile.method,
                        headers: {
                            Authorization: `Bearer ${await getToken()}`,
                            "Content-Type": "application/json",
                        },
                        body: JSON.stringify({ profile_pic: secureUrl })
                    });
                    
                    if (res.ok) {
                        queryClient.invalidateQueries({ queryKey: ['rider', 'profile'] });
                        Toast.success("Success", "Profile picture updated!");
                    } else {
                        Toast.error("Error", "Failed to update profile picture on server.");
                    }
                } else {
                    Toast.error("Error", "Failed to upload image.");
                }
            }
        } catch (error) {
            console.error("Profile pic update error:", error);
            Toast.error("Error", "An error occurred while updating profile picture.");
        } finally {
            setIsUploadingPic(false);
        }
    };

    const handleSignOut = () => {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
        Popup.show({
            title: "Secure Logout",
            message: "Are you sure you want to sign out? You will be marked as offline and will not receive any delivery requests or platform notifications until you log back in.",
            cancelText: "Cancel",
            confirmText: "Sign Out",
            isDestructive: false,
            onConfirm: async () => {
                Popup.setLoading(true);
                try {
                    // Before `signOut()` — the endpoint is authenticated. On a
                    // shared device the token would otherwise stay registered and
                    // the next rider would keep receiving this one's delivery
                    // requests.
                    await clearPushToken();
                    await signOut();
                    // `useSessionCleanup` also clears on the session transition;
                    // doing it here makes the wipe synchronous with the redirect.
                    queryClient.clear();
                    Popup.hide();
                    router.replace("/(Auth)");
                } catch (error) {
                    if (__DEV__) console.error("Sign out error", error);
                    Popup.hide();
                }
            }
        });
    };

    const handleDeleteAccount = () => {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
        Popup.show({
            title: "Delete Rider Account",
            message: "Your rider profile, vehicle records, and personal identifiers will be permanently removed. You will be deactivated from the Drop fleet. Past payouts and delivery history will be strictly anonymized. This action is irreversible. Proceed?",
            cancelText: "Cancel",
            confirmText: "Delete",
            isDestructive: true,
            onConfirm: async () => {
                Popup.setLoading(true);
                try {
                    const res = await fetch(RiderApiRoutes.DeleteAccount.path, {
                        method: RiderApiRoutes.DeleteAccount.method,
                        headers: {
                            Authorization: `Bearer ${await getToken()}`,
                            "Content-Type": "application/json",
                        },
                        body: JSON.stringify({ app_type: "rider", confirmation: "DELETE MY ACCOUNT" })
                    });

                    if (res.ok) {
                        Toast.success("Goodbye", "Account deleted successfully.");
                        await clearPushToken();
                        await signOut();
                        queryClient.clear();
                        Popup.hide();
                        router.replace("/(Auth)");
                    } else {
                        const data = await res.json();
                        Toast.error("Cannot Delete", data.detail || "You have active deliveries preventing deletion.");
                        Popup.hide();
                    }
                } catch (error) {
                    Toast.error("Error", "Network error occurred.");
                    Popup.hide();
                }
            }
        });
    };

    const SettingItem = ({ title, iconName, onPress, danger = false }: any) => (
        <TouchableOpacity 
            activeOpacity={0.7} 
            onPress={() => {
                Haptics.selectionAsync();
                onPress();
            }}
            className={`flex-row items-center justify-between p-4 mb-3 rounded-2xl border ${danger ? (darkTheme ? "bg-red-500/10 border-red-500/20" : "bg-red-50 border-red-100") : (darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200")}`}
            style={darkTheme ? {} : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
        >
            <View className="flex-row items-center gap-4">
                <View className={`w-10 h-10 items-center justify-center rounded-full ${danger ? "bg-red-500/10" : (darkTheme ? "bg-blue-900/40" : "bg-blue-50")}`}>
                    <Ionicons name={iconName} size={20} color={danger ? "#ef4444" : BRAND.primary} />
                </View>
                <Text className={`text-lg font-semibold ${danger ? "text-red-500" : (darkTheme ? "text-white" : "text-gray-900")}`}>
                    {title}
                </Text>
            </View>
            <Ionicons name="chevron-forward" size={20} color={BRAND.primary} />
        </TouchableOpacity>
    );

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <StatusBar
                translucent
                backgroundColor={darkTheme ? "black" : "white"}
                barStyle={darkTheme ? "light-content" : "dark-content"}
            />
            
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
                    <Text className={`text-xl font-bold ${darkTheme ? "text-white" : "text-black"}`}>
                        Rider Settings
                    </Text>
                </View>
            </View>

            <ScrollView 
                contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 40, paddingBottom: 120 }} 
                showsVerticalScrollIndicator={false}
            >
                {isLoading ? (
                    <RiderSettingsSkeleton />
                ) : (
                    <>
                        {/* Profile Header Block */}
                        <View className="items-center mb-10">
                    <View className="relative">
                        <View style={{ 
                            borderWidth: 2, 
                            borderColor: BRAND.primary, 
                            borderRadius: 999, 
                            padding: 2 
                        }}>
                            <UserAvatar 
                                profilePicUrl={RiderData?.profile_pic || user?.imageUrl}
                                fullName={RiderData?.name || user?.fullName || "Rider"}
                                size={100}
                            />
                            {isUploadingPic && (
                                <View className="absolute inset-0 items-center justify-center rounded-full" style={{ backgroundColor: 'rgba(0,0,0,0.5)', margin: 2, zIndex: 10 }}>
                                    <ActivityIndicator size="large" color={BRAND.white} />
                                </View>
                            )}
                        </View>
                        <TouchableOpacity 
                            onPress={handleUpdateProfilePic}
                            disabled={isUploadingPic}
                            activeOpacity={0.8}
                            className="absolute bottom-0 right-0 rounded-full items-center justify-center z-20 shadow-sm"
                            style={{ 
                                backgroundColor: BRAND.primary, 
                                width: 32, 
                                height: 32,
                                borderWidth: 3,
                                borderColor: darkTheme ? "black" : "white"
                            }}
                        >
                            <Ionicons name="camera" size={16} color={BRAND.white} />
                        </TouchableOpacity>
                    </View>
                    <Text className={`text-2xl font-bold mt-4 ${darkTheme ? "text-white" : "text-black"}`}>
                        {RiderData?.name || user?.fullName || "Verified Rider"}
                    </Text>
                    <Text className={`text-sm mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        {user?.emailAddresses?.[0]?.emailAddress || RiderData?.email || "No email available"}
                    </Text>
                </View>

                {/* Settings Groups */}
                <Text className={`text-sm font-bold mb-2 uppercase tracking-widest ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                    Vendors
                </Text>
                <View className="mb-8">
                    <SettingItem 
                        title="My Vendors" 
                        iconName="briefcase-outline" 
                        onPress={() => router.push("/(screens)/MyVendors")} 
                    />
                </View>

                <Text className={`text-sm font-bold mb-2 uppercase tracking-widest ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                    Verification & Vehicle
                </Text>
                <View className="mb-8">
                    <SettingItem 
                        title="Vehicle Details" 
                        iconName="bicycle-outline" 
                        onPress={() => router.push("/(screens)/rider/VehicleDetails")} 
                    />
                </View>

                <Text className={`text-sm font-bold mb-2 uppercase tracking-widest ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                    Financials
                </Text>
                <View className="mb-8">
                    <SettingItem 
                        title="Bank & Earning Settings" 
                        iconName="business-outline" 
                        onPress={() => router.push("/(screens)/rider/BankDetails")} 
                    />
                </View>

                <Text className={`text-sm font-bold mb-2 uppercase tracking-widest ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                    Preferences
                </Text>
                <View className="mb-8">
                    <SettingItem 
                        title="App Preferences" 
                        iconName="settings-outline" 
                        onPress={() => router.push("/(screens)/rider/Preferences")} 
                    />
                    <TouchableOpacity 
                        activeOpacity={0.7} 
                        onPress={async () => {
                            Haptics.selectionAsync();
                            setTheme();
                        }}
                        className={`flex-row items-center justify-between p-4 mb-3 rounded-2xl border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`}
                        style={darkTheme ? {} : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
                    >
                        <View className="flex-row items-center gap-4">
                            <View className={`w-10 h-10 items-center justify-center rounded-full ${darkTheme ? "bg-blue-900/40" : "bg-blue-50"}`}>
                                <Ionicons name={darkTheme ? "moon-outline" : "sunny-outline"} size={20} color={BRAND.primary} />
                            </View>
                            <Text className={`text-lg font-semibold ${darkTheme ? "text-white" : "text-gray-900"}`}>
                                Dark Mode
                            </Text>
                        </View>
                        <View 
                            className={`w-12 h-6 rounded-full justify-center px-1 ${!darkTheme ? "bg-gray-300" : ""}`}
                            style={darkTheme ? { backgroundColor: BRAND.primary } : {}}
                        >
                            <View className={`w-4 h-4 rounded-full bg-white shadow-sm ${darkTheme ? "self-end" : "self-start"}`} />
                        </View>
                    </TouchableOpacity>
                </View>

                <Text className={`text-sm font-bold mb-2 uppercase tracking-widest ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                    System
                </Text>
                <View className="mb-8">
                    <SettingItem 
                        title="Sign Out" 
                        iconName="log-out-outline" 
                        onPress={handleSignOut} 
                    />
                    <SettingItem 
                        title="Delete Account" 
                        iconName="trash-outline" 
                        danger={true} 
                        onPress={handleDeleteAccount} 
                    />
                </View>
                </>
                )}
            </ScrollView>
        </SafeAreaView>
    );
}
