import { useBottleDebt } from "@/hooks/queries/useBottleDebt";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { UIThemeContext } from "@/context/ThemeContext";
import { useContext, useEffect, useState } from "react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { useAuth, useUser } from "@clerk/clerk-expo";
import * as ImagePicker from 'expo-image-picker';
import {
    ScrollView,
    StatusBar,
    Text,
    TextInput,
    View,
    KeyboardAvoidingView,
    Platform,
    TouchableOpacity,
    ActivityIndicator
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { BRAND } from "@/constants/brandColors";
import PressableScale from "@/components/ui/PressableScale";
import { Toast } from '@/lib/toast';
import { useRouter } from "expo-router";
import VehicleDropdown from "@/components/ui/VehicleDropdown";
import { Ionicons } from "@expo/vector-icons";
import { Popup } from "@/lib/popup";
import { RiderProfileSkeleton } from "@/components/skeletons/ContextualSkeletons";
import UserAvatar from "@/components/ui/UserAvatar";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useKycStatus } from "@/hooks/queries/useKycStatus";
import { errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";

export default function Profile() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { getToken, signOut } = useAuth();
  const { get, put } = useApiRequest();
  const { clearPushToken } = usePushNotifications();
  const router = useRouter();
  const { user } = useUser();
  const queryClient = useQueryClient();
  const [profile, setProfile] = useState<any>(null);
  
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState<any>({});
  const [saving, setSaving] = useState(false);
  const [imageUploading, setImageUploading] = useState(false);
  const [loading, setLoading] = useState(true);

  // Already cached by the `(screens)` gate — the same hook, so the same entry.
  const { data: statusData } = useKycStatus(!!user);

  // Fetch active associations and applications
  const { data: registeredVendors, isLoading: vendorsLoading } = useQuery({
    queryKey: ['rider', 'registered_vendors'],
    queryFn: () => get<any[]>(RiderApiRoutes.RegisteredVendors().path),
    enabled: !!user
  });

  // Empties this rider still owes vendors, surfaced as a badge below.
  const { data: bottleDebt } = useBottleDebt();
  const bottleDebtCount = bottleDebt?.total_bottles ?? 0;

  const fetchProfile = async () => {
    try {
      const data = await get<any>(RiderApiRoutes.GetProfile.path);
      setProfile(data);
      setEditForm({ name: data.name, phone_number: data.phone_number, vehicle_type: data.vehicle_type, plate_number: data.plate_number });
    } catch (e) {
      if (__DEV__) console.warn("[Profile] fetch failed:", errorMessage(e));
    } finally { setLoading(false); }
  };

  useEffect(() => { fetchProfile(); }, []);

  const handleSignOut = () => {
    Popup.show({
      title: "Sign Out",
      message: "Are you sure?",
      cancelText: "Cancel",
      confirmText: "Sign Out",
      isDestructive: true,
      onConfirm: async () => {
          Popup.hide();
          // Detach the push token first — the endpoint is authenticated, so it
          // cannot be done once the session is gone.
          await clearPushToken();
          queryClient.clear();
          await signOut();
      }
    });
  };

  const pickImage = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Popup.show({
        title: 'Permission Denied',
        message: 'Camera roll permissions are required to change your profile picture.',
        isAlertOnly: true
      });
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.5,
      base64: true
    });

    if (!result.canceled && result.assets[0].base64) {
      setImageUploading(true);
      try {
        const base64 = `data:image/jpeg;base64,${result.assets[0].base64}`;
        await user?.setProfileImage({ file: base64 });
        
        // Force refresh user data from clerk
        await user?.reload();
        
        Toast.success("Success", "Profile picture updated successfully");
        
        // Sync with backend DB
        if (user?.imageUrl) {
            await put(RiderApiRoutes.UpdateProfile.path, { profile_pic: user.imageUrl });
            // Update local profile state to trigger re-renders
            setProfile((prev: any) => ({ ...prev, profile_pic: user.imageUrl }));
        }
      } catch (err) {
        if (__DEV__) console.error("Upload error:", err);
        Toast.error("Upload Failed", errorMessage(err, "Could not update profile picture."));
      } finally {
        setImageUploading(false);
      }
    }
  };

  const handleSave = async () => {
    // Validate phone
    const phoneRegex = /^(?:\+254|0)[17]\d{8}$/; // Matches +254xxxxxxxxx or 07xxxxxxxx or 01xxxxxxxx
    if (editForm.phone_number && !phoneRegex.test(editForm.phone_number)) {
      Toast.error("Invalid Phone", "Please enter a valid Kenyan phone number (e.g. +254712345678 or 0712345678)");
      return;
    }

    setSaving(true);
    try {
      await put(RiderApiRoutes.UpdateProfile.path, editForm);
      Toast.success("Success", "Profile updated successfully");
      setProfile({ ...profile, ...editForm });
      setIsEditing(false);
      queryClient.invalidateQueries({ queryKey: ['rider', 'profile'] });
    } catch (e) {
      Toast.error("Error", errorMessage(e, "Could not update profile"));
    } finally {
      setSaving(false);
    }
  };

  const InfoRow = ({ label, value, field, placeholder }: { label: string; value: string; field: string; placeholder?: string }) => (
    <View className={`flex-row justify-between py-3 border-b ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
      <Text className={`w-1/3 mt-3 text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{label}</Text>
      {isEditing ? (
        field === "vehicle_type" ? (
          <VehicleDropdown 
              value={editForm[field]} 
              onValueChange={(val) => setEditForm({ ...editForm, [field]: val })} 
              containerStyle={{ width: "60%" }}
              buttonStyle={{ width: "100%", borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8, height: "auto" }}
          />
        ) : (
          <TextInput
            value={editForm[field]}
            onChangeText={(text) => setEditForm({ ...editForm, [field]: text })}
            placeholder={placeholder || `Enter ${label}`}
            placeholderTextColor={darkTheme ? "#666" : "#999"}
            className={`w-[60%] p-3 rounded-lg border ${darkTheme ? "bg-white/5 border-white/10 text-white" : "bg-white border-gray-200 text-gray-900"}`}
          />
        )
      ) : (
        <Text className={`flex-1 mt-3 font-semibold text-right ${darkTheme ? "text-white" : "text-gray-900"}`}>{value || "—"}</Text>
      )}
    </View>
  );

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
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
                  Profile
              </Text>
          </View>
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{flex: 1}}>
        <ScrollView className="px-5" contentContainerStyle={{ paddingBottom: 120 }}>
        {loading ? (
            <RiderProfileSkeleton />
        ) : (
          <>
            <View className="items-center pt-6 pb-8">
              <View className="relative mb-4">
                <View style={{ borderWidth: 3, borderColor: BRAND.primary, borderRadius: 999, padding: 3 }}>
                  <UserAvatar
                    profilePicUrl={profile?.profile_pic || user?.imageUrl}
                    fullName={profile?.name || user?.fullName || "Rider"}
                    size={96}
                  />
                  {imageUploading && (
                    <View className="absolute inset-0 bg-black/40 rounded-full items-center justify-center m-[3px]">
                       <ActivityIndicator color="#fff" size="small" />
                    </View>
                  )}
                </View>
                <TouchableOpacity 
                  onPress={pickImage}
                  disabled={imageUploading}
                  className="absolute bottom-1 right-1 rounded-full items-center justify-center border-[2.5px]"
                  style={{ width: 36, height: 36, backgroundColor: BRAND.primary, borderColor: darkTheme ? "#000" : "#fff" }}
                >
                  <Ionicons name="camera" size={18} color="#fff" />
                </TouchableOpacity>
              </View>

              <Text className={`text-2xl font-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>
                {profile?.name || user?.fullName || "Rider"}
              </Text>
              <Text className="text-sm mt-1 font-bold text-accentbg">
                {profile?.vehicle_type === 'truck' ? 'Wholesale Capacity (50+ Bottles)' : 
                 profile?.vehicle_type === 'tuktuk' ? 'Medium Payload (10-20 Bottles)' : 
                 'Standard Payload (Max 5 Bottles)'}
              </Text>
              <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                {profile?.email || user?.emailAddresses[0]?.emailAddress}
              </Text>
            </View>

            <View className="flex-row justify-between items-center mb-2 px-1">
              <Text className={`font-bold text-lg ${darkTheme ? "text-white" : "text-gray-900"}`}>Profile Details</Text>
              <PressableScale onPress={() => {
                  if (isEditing) {
                      setEditForm({ 
                          name: profile?.name || "", 
                          phone_number: profile?.phone_number || "", 
                          vehicle_type: profile?.vehicle_type || "", 
                          plate_number: profile?.plate_number || "" 
                      });
                  }
                  setIsEditing(!isEditing);
              }} className="px-3 py-1 bg-accentbg/10 rounded-full">
                <Text className="text-accentbg font-semibold">{isEditing ? "Cancel" : "Edit"}</Text>
              </PressableScale>
            </View>

            <View className={`rounded-2xl p-4 ${darkTheme ? "bg-white/5" : "bg-white"}`}>
              <InfoRow field="name" label="Name" value={profile?.name} />
              <InfoRow field="phone_number" label="Phone" value={profile?.phone_number} placeholder="07XXXXXXXX" />
              <InfoRow field="vehicle_type" label="Vehicle" value={profile?.vehicle_type} />
              <InfoRow field="plate_number" label="Plate" value={profile?.plate_number} />
              {!isEditing && <InfoRow field="is_available" label="Available" value={profile?.is_available ? "Yes" : "No"} />}
            </View>

            {isEditing && (
              <PressableScale 
                onPress={handleSave} 
                disabled={saving}
                className={`mt-6 py-4 rounded-2xl items-center shadow-sm ${saving ? "bg-accentbg/70" : "bg-accentbg"}`}
              >
                {saving ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text className="text-white font-bold text-lg">Save Profile</Text>
                )}
              </PressableScale>
            )}

            {/* Vendor Network Block */}
            <View className="mt-8 mb-4">
              <Text className={`mb-3 ml-1 font-bold text-lg ${darkTheme ? "text-white" : "text-gray-800"}`}>Vendor Network</Text>
              
              {vendorsLoading ? (
                  <View className={`rounded-2xl p-6 items-center justify-center border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`}>
                      <ActivityIndicator color={BRAND.primary} />
                  </View>
              ) : statusData?.employer_vendor_id ? (
                  // STATE 3: Dedicated Rider
                  <PressableScale onPress={() => router.push("/(screens)/OperationBase")} activeOpacity={0.7}>
                    <View className={`rounded-2xl p-4 flex-row items-center border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`} style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
                      <View className={`p-3 rounded-full mr-4 ${darkTheme ? "bg-blue-900/40" : "bg-blue-50"}`}>
                        <Ionicons name="briefcase-outline" size={26} color={BRAND.primary} />
                      </View>
                      <View className="flex-1">
                        <Text className={`text-base font-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>My Operation Base</Text>
                        <Text className={`text-xs mt-0.5 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>View employer metrics and announcements</Text>
                      </View>
                      <Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
                    </View>
                  </PressableScale>
              ) : registeredVendors && registeredVendors.length > 0 ? (
                  // STATE 2: Associated Rider
                  <PressableScale onPress={() => router.push("/(screens)/MyVendors")} activeOpacity={0.7}>
                    <View className={`rounded-2xl p-4 flex-row items-center border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`} style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
                      <View className={`p-3 rounded-full mr-4 ${darkTheme ? "bg-blue-900/40" : "bg-blue-50"}`}>
                        <Ionicons name="people-outline" size={26} color={BRAND.primary} />
                      </View>
                      <View className="flex-1">
                        <Text className={`text-base font-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Associated Vendors</Text>
                        <Text className={`text-xs mt-0.5 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Associated with {registeredVendors.length} vendor{registeredVendors.length === 1 ? '' : 's'}</Text>
                      </View>
                      <Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
                    </View>
                  </PressableScale>
              ) : (
                  // STATE 1: Independent Rider
                  <PressableScale onPress={() => router.push("/(screens)/DiscoverVendors")} activeOpacity={0.7}>
                    <View className={`rounded-2xl p-4 flex-row items-center border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`} style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
                      <View className={`p-3 rounded-full mr-4 ${darkTheme ? "bg-blue-900/40" : "bg-blue-50"}`}>
                        <Ionicons name="business-outline" size={26} color={BRAND.primary} />
                      </View>
                      <View className="flex-1">
                        <Text className={`text-base font-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Discover Vendors</Text>
                        <Text className={`text-xs mt-0.5 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Find and apply to nearby water vendors</Text>
                      </View>
                      <Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
                    </View>
                  </PressableScale>
              )}

              {/* Empties the rider is holding. Debt accrues on every quick_swap
                  delivery; before this entry point there was no way to see it. */}
              <PressableScale onPress={() => router.push("/(screens)/BottleDebt" as any)} activeOpacity={0.7} className="mt-3">
                <View className={`rounded-2xl p-4 flex-row items-center border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`} style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
                  <View className={`p-3 rounded-full mr-4 ${bottleDebtCount > 0 ? (darkTheme ? "bg-orange-900/40" : "bg-orange-50") : (darkTheme ? "bg-blue-900/40" : "bg-blue-50")}`}>
                    <Ionicons name="water-outline" size={26} color={bottleDebtCount > 0 ? "#ea580c" : BRAND.primary} />
                  </View>
                  <View className="flex-1">
                    <Text className={`text-base font-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Bottles I'm Holding</Text>
                    <Text className={`text-xs mt-0.5 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
                      {bottleDebtCount > 0
                        ? `${bottleDebtCount} empt${bottleDebtCount === 1 ? 'y' : 'ies'} to return`
                        : "No empties outstanding"}
                    </Text>
                  </View>
                  {bottleDebtCount > 0 && (
                    <View className="px-2 py-1 rounded-full bg-orange-500/20 mr-2">
                      <Text className="text-orange-600 font-bold text-xs">{bottleDebtCount}</Text>
                    </View>
                  )}
                  <Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
                </View>
              </PressableScale>
            </View>

            <PressableScale 
              activeOpacity={0.8} 
              onPress={handleSignOut} 
              className={`py-4 rounded-2xl items-center mt-6 bg-red-500/10`}
            >
              <Text className="text-red-500 font-bold text-base">Sign Out</Text>
            </PressableScale>
          </>
        )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
