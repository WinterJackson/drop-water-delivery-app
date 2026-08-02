import { UIThemeContext } from "@/context/ThemeContext";
import React, { useContext, useState } from "react";
import { useUser, useAuth } from "@clerk/clerk-expo";
import * as Haptics from "expo-haptics";
import {
    ScrollView,
    StatusBar,
    Text,
    View,
    TouchableOpacity,
    ActivityIndicator
} from "react-native";
import { Image } from "expo-image";
import { BRAND } from "@/constants/brandColors";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import * as ImagePicker from 'expo-image-picker';
import { useQueryClient } from "@tanstack/react-query";
import { errorMessage } from "@/API/errors";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import SecureUpload from "@/Helpers/imageUpload";
import { useActiveStore } from "@/stores/activeStoreStore";
import { useUpdateVendorProfile } from "@/hooks/queries/useVendorProfile";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";

export default function Profile() {
  const { currentTheme, setTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { user } = useUser();
  const { getToken, signOut } = useAuth();
  const { clearPushToken } = usePushNotifications();
  const { request } = useApiRequest();
  const updateProfile = useUpdateVendorProfile();
  const activeStoreId = useActiveStore((s) => s.activeStoreId);
  const clearActiveStore = useActiveStore((s) => s.clear);
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: vendor } = useVendorProfile();
  const isStaff = vendor?.role === "staff";
  const [imageUploading, setImageUploading] = useState(false);

  const pickImage = async () => {
      const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (status !== 'granted') {
          Popup.show({
              title: 'Permission Denied',
              message: 'Camera roll permissions are required to change your store picture.',
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

      if (!result.canceled && result.assets[0]?.uri) {
          setImageUploading(true);
          try {
              // The whole image used to be stored *in* the column, as a
              // `data:image/jpeg;base64,…` string a megabyte or two long — it was
              // written to `Vendor.profile_pic` and then sent back inside every
              // profile response, and to every customer browsing the store.
              // Now it goes to S3 and the column holds the key.
              const uploaded = await SecureUpload(
                  result.assets[0].uri,
                  `store_${vendor?.id ?? "avatar"}`,
                  getToken,
                  activeStoreId
              );
              await updateProfile.mutateAsync({ profile_pic: uploaded.secure_url });
              Toast.success("Success", "Store picture updated successfully");
          } catch (err) {
              // `SecureUpload` has already surfaced an upload failure; this
              // catches a refused *save*, which is a different problem.
              Toast.error("Upload Failed", errorMessage(err, "Could not update store picture."));
          } finally {
              setImageUploading(false);
          }
      }
  };

  const handleSignOut = () => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      Popup.show({
          title: "Secure Logout",
          message: "Are you sure you want to sign out? Your store will remain active, but you won't receive immediate push notifications or be able to accept live orders until you securely log back in.",
          cancelText: "Cancel",
          confirmText: "Sign Out",
          isDestructive: true,
          onConfirm: async () => {
              Popup.setLoading(true);
              try {
                  // Before `signOut()` — the endpoint is authenticated. On a
                  // shared till device the token would otherwise stay registered
                  // and the next person would keep receiving this store's
                  // incoming-order notifications.
                  await clearPushToken();
                  await signOut();
                  // Orders, products, wallet and staff records all sat in the
                  // cache and survived sign-out, so the next account to sign in
                  // on this device rendered the previous store's data. The
                  // remembered store id is part of that: left behind, the next
                  // account sends an `X-Store-Id` it does not own.
                  clearActiveStore();
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
          title: "Delete Vendor Account",
          message: "Your store profile, bank details, and personal identifiers will be permanently removed. Your store will immediately go offline. Past payouts and orders will be irreversibly anonymized for financial auditing. You cannot recover this account. Do you wish to proceed?",
          cancelText: "Cancel",
          confirmText: "Delete",
          isDestructive: true,
          onConfirm: async () => {
              Popup.setLoading(true);
              try {
                  const result = await request<{ message: string; warning?: string }>(
                      "DELETE",
                      VendorApiRoutes.DeleteAccount.path,
                      { app_type: "vendor", confirmation: "DELETE MY ACCOUNT" }
                  );
                  Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
                  // The backend reports honestly when the local data is gone but
                  // the Clerk identity survived; saying "deleted successfully"
                  // over that warning would be a lie about a deletion.
                  if (result?.warning) {
                      Toast.info("Account deleted", result.warning);
                  } else {
                      Toast.success("Goodbye", "Store deleted successfully.");
                  }
                  await clearPushToken();
                  await signOut();
                  clearActiveStore();
                  queryClient.clear();
                  Popup.hide();
                  router.replace("/(Auth)");
              } catch (error) {
                  Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
                  // "You have unfulfilled orders" is the answer the vendor needs;
                  // "Network error occurred" was shown for it.
                  Popup.show({
                      title: "Cannot Delete",
                      message: errorMessage(error, "You have active orders preventing deletion."),
                      isAlertOnly: true,
                  });
              }
          }
      });
  };

  const NavItem = ({ icon, label, description, path, onPress, danger }: { icon: any, label: string, description: string, path?: string, onPress?: () => void, danger?: boolean }) => (
    <TouchableOpacity
      activeOpacity={0.7}
      onPress={() => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        if (onPress) onPress();
        else if (path) router.push(path as any);
      }}
      className={`rounded-3xl p-5 mb-3 flex-row items-center border ${danger ? (darkTheme ? "bg-red-500/10 border-red-500/20" : "bg-red-50 border-red-100") : (darkTheme ? "bg-surface-container" : "bg-white border-gray-100")}`}
      style={darkTheme ? {} : { 
        ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) 
      }}
    >
      <View className={`w-12 h-12 rounded-full items-center justify-center mr-4 ${danger ? "bg-red-500/20" : (darkTheme ? "bg-slate-800" : "bg-white")}`}>
        <Ionicons name={icon} size={24} color={danger ? "#ef4444" : BRAND.primary} />
      </View>
      <View className="flex-1">
        <Text className={`text-lg font-bold ${danger ? "text-red-500" : (darkTheme ? "text-white" : "text-slate-900")}`}>{label}</Text>
        <Text className={`text-sm mt-1 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>{description}</Text>
      </View>
      <Ionicons name={path ? "chevron-forward" : "chevron-forward"} size={24} color={danger ? "#ef4444" : BRAND.primary} />
    </TouchableOpacity>
  );

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />

      {/* Header */}
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
          <Text className={`text-xl font-bold flex-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>Settings</Text>

          {/* THEME TOGGLE — matches Customer & Rider app pattern */}
          <TouchableOpacity
            activeOpacity={0.7}
            onPress={() => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              setTheme();
            }}
          >
            <View className={`w-10 h-10 items-center justify-center rounded-full ${darkTheme ? "bg-gray-800" : "bg-white"}`}>
              <Ionicons name={darkTheme ? "sunny-outline" : "moon-outline"} size={22} color={BRAND.primary} />
            </View>
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView className="px-5" contentContainerStyle={{ paddingBottom: 120 }}>
        {/* Hub Header */}
        <View className="items-center pt-8 pb-8">
          <View className="relative">
            <View 
              className={`w-28 h-28 rounded-full items-center justify-center mb-4 border-[3px] p-1 ${darkTheme ? "bg-surface-container" : "bg-white"}`}
              style={{
                borderColor: BRAND.primary,
                ...(darkTheme ? {} : {
                  ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
                })
              }}
            >
              <View className={`w-full h-full rounded-full items-center justify-center overflow-hidden ${darkTheme ? "bg-slate-800" : "bg-white"}`}>
                {vendor?.profile_pic ? (
                  <Image source={{ uri: vendor.profile_pic }} style={{ width: "100%", height: "100%" }} cachePolicy="disk" transition={200} />
                ) : (
                  <Ionicons name="storefront-outline" size={40} color={BRAND.primary} />
                )}
                {imageUploading && (
                    <View className="absolute inset-0 bg-black/40 items-center justify-center">
                        <ActivityIndicator color="#fff" size="small" />
                    </View>
                )}
              </View>
            </View>
            {!isStaff && (
                <TouchableOpacity 
                    onPress={pickImage}
                    disabled={imageUploading}
                    className="absolute bottom-5 right-1 rounded-full items-center justify-center border-[2.5px]"
                    style={{ width: 36, height: 36, backgroundColor: BRAND.primary, borderColor: darkTheme ? "#000" : "#fff", zIndex: 10 }}
                >
                    <Ionicons name="camera" size={18} color="#fff" />
                </TouchableOpacity>
            )}
          </View>
          <Text className={`text-2xl font-bold text-center ${darkTheme ? "text-white" : "text-slate-900"}`}>
            {vendor?.business_name || "Settings Hub"}
          </Text>
          <Text className={`text-base mt-1 font-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
            Managed by {user?.fullName || "Owner"}
          </Text>
        </View>

        <Text className={`mb-4 ml-2 font-bold text-xl tracking-tight ${darkTheme ? "text-white" : "text-slate-900"}`}>Account & Identity</Text>
        
        <NavItem 
          icon="storefront-outline" 
          label="Store Profile" 
          description="View public store details and operations" 
          path="/(screens)/StoreProfile" 
        />
        
        {!isStaff && (
          <NavItem 
            icon="person-circle-outline" 
            label="Owner Profile" 
            description="Manage personal KYC and sign-in details" 
            path="/(screens)/OwnerProfile" 
          />
        )}

        <Text className={`mt-6 mb-4 ml-2 font-bold text-xl tracking-tight ${darkTheme ? "text-white" : "text-slate-900"}`}>Business Tools</Text>
        
        <NavItem 
          icon="map-outline" 
          label="Live Map" 
          description="Track active orders and riders" 
          path="/(screens)/MyMap" 
        />

        <NavItem 
          icon="wallet-outline" 
          label="Digital Wallet" 
          description="Manage funds and float balance" 
          path="/(screens)/WalletScreen" 
        />

        <NavItem 
          icon="water-outline" 
          label="Bottle Reconciliation" 
          description="Clear empty bottle debt with riders" 
          path="/(screens)/BottleReconciliation" 
        />
        
        {!isStaff && (
          <NavItem 
            icon="people-outline" 
            label={vendor?.vendor_type === "wholesale_b2b" ? "Link TukTuk Drivers" : "Manage Riders"}
            description={vendor?.vendor_type === "wholesale_b2b" ? "Link drivers to your Vendor ID" : "View and approve gig rider applications"}
            path="/(screens)/RiderManagement" 
          />
        )}

        <Text className={`mt-6 mb-4 ml-2 font-bold text-xl tracking-tight ${darkTheme ? "text-white" : "text-slate-900"}`}>Help</Text>

        {/* Not owner-only. Staff are the ones on the floor when a rider turns up
            with the wrong bottle count, and they have no other way to reach us. */}
        <NavItem
          icon="help-buoy-outline"
          label="Help & Support"
          description="Message the Drop team about this store"
          path="/(screens)/Support"
        />

        <Text className={`mt-6 mb-4 ml-2 font-bold text-xl tracking-tight ${darkTheme ? "text-white" : "text-slate-900"}`}>System & Security</Text>
        
        <NavItem 
          icon="log-out-outline" 
          label="Sign Out" 
          description="Securely log out of your account" 
          onPress={handleSignOut} 
        />
        
        {!isStaff && (
          <NavItem 
            icon="trash-outline" 
            label="Delete Store" 
            description="Permanently erase your account and data" 
            onPress={handleDeleteAccount} 
            danger={true}
          />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
