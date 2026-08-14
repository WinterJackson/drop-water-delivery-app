import React, { useContext, useState, useEffect } from "react";
import { View, ScrollView, StatusBar, ActivityIndicator, KeyboardAvoidingView, Platform, TouchableOpacity, KeyboardTypeOptions } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth, useUser } from "@clerk/clerk-expo";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import * as ImagePicker from 'expo-image-picker';
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { PressableScale } from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { Popup } from "@/lib/popup";
import { Toast } from "@/lib/toast";
import { useQueryClient } from "@tanstack/react-query";
import { errorMessage } from "@/API/errors";
import { useUpdateVendorProfile, useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { usePushNotifications } from "@/hooks/usePushNotifications";

/**
 * One label/value row on the owner record, editable in place.
 *
 * Module scope, not the render body of `OwnerProfile`. React reconciles by
 * component *type*, and a function defined during render is a new type on every
 * render — so React unmounts the old subtree and mounts a new one rather than
 * updating it. The `TextInput` here is driven by `editForm`, which lives in
 * `OwnerProfile`, so every keystroke destroyed and recreated the native input:
 * focus lost, keyboard closed, one character per tap.
 *
 * `focusedField` made it worse rather than better — the focus ring it drives was
 * being torn down by the same remount that dismissed the keyboard, so the field
 * never looked focused either.
 */
const InfoRow = ({
    label,
    value,
    field,
    placeholder,
    keyboardType = "default",
    darkTheme,
    isEditing,
    editForm,
    setEditForm,
    focusedField,
    setFocusedField,
}: any) => {
    const isFocused = focusedField === field;
    return (
        <View className={`flex-row justify-between py-3 border-b ${darkTheme ? "border-slate-800/80" : "border-slate-100"}`}>
            <Text className={`w-1/3 mt-3 text-sm ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>{label}</Text>
            {isEditing ? (
                <View className={`w-[60%] px-3 h-[45px] rounded-xl border-2 flex-row items-center ${isFocused ? "border-green-500 bg-green-500/5" : (darkTheme ? "bg-black border-gray-800" : "bg-white border-gray-200")}`}>
                    <TextInput
                        value={editForm[field as keyof typeof editForm]}
                        onChangeText={(text) => setEditForm({ ...editForm, [field]: text })}
                        onFocus={() => { setFocusedField(field); Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); }}
                        onBlur={() => setFocusedField(null)}
                        placeholder={placeholder || `Enter ${label}`}
                        placeholderTextColor={darkTheme ? "#666" : "#999"}
                        keyboardType={keyboardType as KeyboardTypeOptions}
                        className={`flex-1 text-sm font-sans-semibold ${darkTheme ? "text-white" : "text-gray-900"}`}
                    />
                </View>
            ) : (
                <Text className={`flex-1 mt-3 font-sans-semibold text-right ${darkTheme ? "text-slate-200" : "text-slate-900"}`}>{value || "—"}</Text>
            )}
        </View>
    );
};

export default function OwnerProfile() {

  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { signOut, getToken } = useAuth();
  const { clearPushToken } = usePushNotifications();
  const { user } = useUser();
  // `owners_name` and `phone_number` are store-profile fields; the dashboard
  // returns neither, so this form used to open with both blank.
  const { data: vendorProfile } = useVendorProfile();
  const updateProfile = useUpdateVendorProfile();
  const router = useRouter();
  const queryClient = useQueryClient();

  useEffect(() => {
      if (vendorProfile?.role === "staff") {
          Toast.error("Access Denied", "Staff members cannot access the Owner Profile.");
          router.replace("/(screens)");
      }
  }, [vendorProfile]);

  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [imageUploading, setImageUploading] = useState(false);
  const [focusedField, setFocusedField] = useState<string | null>(null);
  
  // Hydrate empty Clerk names from DB
  const extractNames = () => {
    let fName = user?.firstName || "";
    let lName = user?.lastName || "";
    if (!fName && !lName && vendorProfile?.owners_name) {
      const parts = vendorProfile.owners_name.split(" ");
      fName = parts[0] || "";
      lName = parts.slice(1).join(" ") || "";
    }
    return { fName, lName };
  };

  const [editForm, setEditForm] = useState({
    firstName: extractNames().fName,
    lastName: extractNames().lName,
    phone_number: vendorProfile?.phone_number || ""
  });

  const handleSignOut = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    Popup.show({
      title: "Sign Out",
      message: "Are you sure you want to log out of your account?",
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
        await user?.reload();
        
        // Sync DB Profile Pic. Clerk hosts this one, so it is a public URL
        // rather than an S3 key — the backend passes `http…` through unsigned.
        if (user?.imageUrl) {
          await updateProfile.mutateAsync({ profile_pic: user.imageUrl });
        }

        Toast.success("Success", "Profile picture updated successfully");
      } catch (err) {
        Toast.error("Upload Failed", errorMessage(err, "Could not update profile picture."));
      } finally {
        setImageUploading(false);
      }
    }
  };

  const handleSave = async () => {
    const phoneRegex = /^(?:\+254|0)[17]\d{8}$/; 
    if (editForm.phone_number && !phoneRegex.test(editForm.phone_number)) {
      Toast.error("Invalid Phone", "Please enter a valid Kenyan phone number.");
      return;
    }

    setSaving(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    try {
      // 1. Update Clerk Profile
      await user?.update({
        firstName: editForm.firstName,
        lastName: editForm.lastName
      });

      // 2. Update DB Profile
      const owners_name = `${editForm.firstName} ${editForm.lastName}`.trim();

      await updateProfile.mutateAsync({
        owners_name: owners_name || undefined,
        phone_number: editForm.phone_number || undefined,
      });

      Toast.success("Success", "Owner Profile updated successfully");
      setIsEditing(false);
    } catch (e) {
      Toast.error("Error", errorMessage(e, "Could not update profile"));
    } finally {
      setSaving(false);
    }
  };

  const infoRowProps = { darkTheme, isEditing, editForm, setEditForm, focusedField, setFocusedField };

  const renderKYCBadge = () => {
      const status = vendorProfile?.verification_status?.toLowerCase() || "pending";
      let bgColor = "bg-gray-500/20";
      let textColor = "text-gray-500";
      let text = "Unknown";

      if (status === "pending") {
          bgColor = "bg-orange-500/20";
          textColor = "text-orange-500";
          text = "Pending";
      } else if (status === "verified") {
          bgColor = "bg-green-500/20";
          textColor = "text-green-500";
          text = "Verified";
      } else if (status === "rejected") {
          bgColor = "bg-red-500/20";
          textColor = "text-red-500";
          text = "Rejected";
      }

      return (
          <View className={`px-3 py-1 rounded-full ${bgColor}`}>
              <Text className={`font-sans-bold text-xs uppercase ${textColor}`}>{text}</Text>
          </View>
      );
  };

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />

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
          <Text className={`text-xl font-sans-bold flex-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>Owner Profile</Text>
        </View>
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{flex: 1}}>
        <ScrollView className="px-5" contentContainerStyle={{ paddingBottom: 120 }} showsVerticalScrollIndicator={false}>
          {/* Personal Identity */}
          <View className="items-center pt-8 pb-8">
            <View className="relative mb-4">
                <View 
                  className={`w-28 h-28 rounded-full items-center justify-center border-[3px] p-1 ${darkTheme ? "bg-surface-container" : "bg-white"}`}
                  style={{ borderColor: BRAND.primary }}
                >
                  <View className={`w-full h-full rounded-full items-center justify-center overflow-hidden ${darkTheme ? "bg-slate-800" : "bg-white"}`}>
                    {user?.imageUrl ? (
                      <Image source={{ uri: user.imageUrl }} style={{ width: "100%", height: "100%" }} cachePolicy="disk" transition={200} />
                    ) : (
                      <Ionicons name="person-outline" size={40} color={BRAND.primary} />
                    )}
                  </View>
                  {imageUploading && (
                      <View className="absolute inset-0 bg-black/40 rounded-full items-center justify-center m-[3px]">
                         <ActivityIndicator color="#fff" size="small" />
                      </View>
                  )}
                </View>
                <TouchableOpacity accessibilityRole="button" accessibilityLabel="Change your profile photo" 
                  onPress={pickImage}
                  disabled={imageUploading}
                  className="absolute bottom-1 right-1 rounded-full items-center justify-center border-[2.5px]"
                  style={{ width: 36, height: 36, backgroundColor: BRAND.primary, borderColor: darkTheme ? "#000" : "#fff", zIndex: 10 }}
                >
                  <Ionicons name="camera" size={18} color="#fff" />
                </TouchableOpacity>
            </View>

            <Text className={`text-2xl font-heading-semibold text-center ${darkTheme ? "text-white" : "text-slate-900"}`}>
              {user?.fullName || vendorProfile?.owners_name || "Vendor Owner"}
            </Text>
            <Text className={`text-sm mt-1 font-sans-semibold ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              {user?.primaryEmailAddress?.emailAddress}
            </Text>
          </View>

          <View className="flex-row justify-between items-center mb-2 px-1">
              <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-gray-900"}`}>Identity Details</Text>
              <PressableScale onPress={() => {
                  if (isEditing) {
                      const names = extractNames();
                      setEditForm({ 
                          firstName: names.fName, 
                          lastName: names.lName,
                          phone_number: vendorProfile?.phone_number || "" 
                      });
                  }
                  setIsEditing(!isEditing);
              }} className="px-3 py-1 bg-accentbg/10 rounded-full">
                <Text className="text-accentbg font-sans-semibold">{isEditing ? "Cancel" : "Edit"}</Text>
              </PressableScale>
          </View>

          <View className={`rounded-[24px] p-6 mb-8 border shadow-sm ${darkTheme ? "bg-surface-container" : "bg-white border-gray-100"}`}>
            {isEditing ? (
              <>
                <InfoRow {...infoRowProps} label="First Name" field="firstName" value={editForm.firstName} />
                <InfoRow {...infoRowProps} label="Last Name" field="lastName" value={editForm.lastName} />
              </>
            ) : (
              <InfoRow {...infoRowProps} label="Full Name" value={user?.fullName || vendorProfile?.owners_name || ""} />
            )}
            
            <InfoRow {...infoRowProps} label="Phone Number" field="phone_number" value={vendorProfile?.phone_number || ""} placeholder="07XXXXXXXX" keyboardType="phone-pad" />
            
            {!isEditing && (
              <>
                <View className={`flex-row justify-between py-3 border-b ${darkTheme ? "border-slate-800/80" : "border-slate-100"}`}>
                    <Text className={`w-1/3 text-sm ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Auth Method</Text>
                    <Text className={`flex-1 font-sans-semibold text-right ${darkTheme ? "text-slate-200" : "text-slate-900"}`}>
                        {user?.externalAccounts?.length ? user.externalAccounts[0].provider.charAt(0).toUpperCase() + user.externalAccounts[0].provider.slice(1) : "Email / Password"}
                    </Text>
                </View>
                <View className={`flex-row justify-between py-3 pt-4 items-center`}>
                  <Text className={`${darkTheme ? "text-slate-400" : "text-slate-500"}`}>KYC Status</Text>
                  {renderKYCBadge()}
                </View>
              </>
            )}
          </View>

          {isEditing && (
            <PressableScale 
              onPress={handleSave} 
              disabled={saving}
              className={`mb-6 py-4 rounded-2xl items-center shadow-sm ${saving ? "bg-accentbg/70" : "bg-accentbg"}`}
            >
              {saving ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text className="text-white font-sans-bold text-lg">Save Profile</Text>
              )}
            </PressableScale>
          )}

          {!isEditing && (
              <PressableScale activeOpacity={0.8} onPress={handleSignOut} className="mt-2 mb-4 bg-red-50 py-4 rounded-2xl items-center border border-red-100 dark:bg-red-900/20 dark:border-red-900/30">
                <Text className="text-red-600 font-sans-bold text-lg">Sign Out</Text>
              </PressableScale>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
