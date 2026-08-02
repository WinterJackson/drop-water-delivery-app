import React, { useContext, useState } from "react";
import { View, Text, StatusBar, TextInput, Image, ScrollView, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { UIThemeContext } from "@/context/ThemeContext";
import { useAuth } from "@clerk/clerk-expo";
import { ApiError, errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import PressableScale from "@/components/ui/PressableScale";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import * as ImagePicker from "expo-image-picker";
import SecureUpload from "@/Helpers/imageUpload";
import { Toast } from "@/lib/toast";
import { queueOfflineAction } from "@/config/database";
import { useRouter, useLocalSearchParams } from "expo-router";
import { BRAND, TOAST } from "@/constants/brandColors";
import { useQueryClient } from "@tanstack/react-query";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export default function BottleRejection() {
  const { currentTheme } = useContext<any>(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { getToken } = useAuth();
  const { post } = useApiRequest();
  const router = useRouter();
  const params = useLocalSearchParams();
  const orderId = params.orderId as string;
  const queryClient = useQueryClient();
  const insets = useSafeAreaInsets();

  const [reason, setReason] = useState("");
  const [photos, setPhotos] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const takePhoto = async () => {
    if (photos.length >= 3) {
      Toast.info("Limit Reached", "You can only attach up to 3 photos.");
      return;
    }

    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      Toast.error("Permission Required", "Camera access is needed to capture evidence.");
      return;
    }

    try {
      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        aspect: [4, 3],
        quality: 0.5,
      });

      if (!result.canceled) {
        setPhotos(prev => [...prev, result.assets[0].uri]);
      }
    } catch (e) {
      if (__DEV__) console.error("Camera error:", e);
    }
  };

  const removePhoto = (index: number) => {
    setPhotos(prev => prev.filter((_, i) => i !== index));
  };

  const submitRejection = async () => {
    if (photos.length < 2) {
      Toast.error("Action Required", "Please provide at least 2 photos clearly showing the damage or issue.");
      return;
    }
    if (reason.trim().length < 10) {
      Toast.error("Action Required", "Please provide a detailed description of the issue.");
      return;
    }

    setIsSubmitting(true);
    let uploadedUrls: string[] = [];
    try {
      // Upload photos securely to S3 first
      Toast.info("Uploading...", "Uploading evidence photos...");
      for (let i = 0; i < photos.length; i++) {
         const uploadResult = await SecureUpload(photos[i], `reject_${orderId}_${i}`, getToken);
         if (uploadResult?.secure_url) {
             uploadedUrls.push(uploadResult.secure_url);
         }
      }

      if (uploadedUrls.length < 2) {
         throw new Error("Failed to upload all required photos. Please try again.");
      }

      await post(RiderApiRoutes.ReportBottleRejection(orderId).path, {
        reason_text: reason,
        photo_urls: uploadedUrls,
      });
      Toast.success("Submitted for Review", "The bottle has been flagged. Please wait 2-5 minutes for the admin to review it.");
      queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
      router.back();
    } catch (e: unknown) {
       // Photos never made it: there is nothing worth queueing, because the
       // report is inadmissible without its evidence.
       if (uploadedUrls.length < 2) {
           Toast.error("Error", errorMessage(e, "Network Error"));
           return;
       }

       // The server refused this report on the merits — a reason too short, an
       // order not in a state that can be disputed. Replaying it offline would
       // retry the same refusal forever, so say why instead.
       if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
           Toast.error("Rejected", errorMessage(e, "This report was not accepted."));
           return;
       }

       // Photos are already in S3 and the submission is legitimate — hold it.
       try {
           await queueOfflineAction(orderId, "REJECT_BOTTLE", JSON.stringify({ reason_text: reason, photo_urls: uploadedUrls }));
           Toast.success("Saved Offline", "Network error. The bottle rejection has been saved and will sync automatically when online.");
           router.back();
       } catch (queueErr) {
           Toast.error("Error", errorMessage(e, "Network Error"));
       }
    } finally {
       setIsSubmitting(false);
    }
  };

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
                  Flag Empty Bottle
              </Text>
          </View>
      </View>
      <View className="px-5 pt-1 pb-3">
        <Text className={`text-sm mt-0.5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
          Report a cracked, broken, or heavily stained bottle.
        </Text>
      </View>

      <ScrollView contentContainerStyle={{ paddingBottom: 120 }} className="flex-1 p-5">
         <Text className={`font-bold text-lg mb-2 ${darkTheme ? "text-white" : "text-gray-900"}`}>1. Photographic Evidence</Text>
         <Text className={`text-sm mb-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Please provide at least 2 clear photos showing the damage. Max 3 photos.</Text>
         
         <View className="flex-row flex-wrap gap-3 mb-6">
             {photos.map((uri, index) => (
                 <View key={index} className="relative w-24 h-24 rounded-xl overflow-hidden border border-gray-200 dark:border-white/10">
                     <Image source={{ uri }} className="w-full h-full" />
                     <PressableScale onPress={() => removePhoto(index)} className="absolute top-1 right-1 w-6 h-6 bg-red-500 rounded-full items-center justify-center">
                         <Ionicons name="close" size={14} color="#fff" />
                     </PressableScale>
                 </View>
             ))}
             
             {photos.length < 3 && (
                 <PressableScale onPress={takePhoto} className={`w-24 h-24 rounded-xl items-center justify-center border-2 border-dashed ${darkTheme ? "border-white/20 bg-white/5" : "border-gray-300 bg-white"}`}>
                     <Ionicons name="camera-outline" size={32} color={BRAND.primary} />
                     <Text className={`text-xs mt-1 font-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Add Photo</Text>
                 </PressableScale>
             )}
         </View>

         <Text className={`font-bold text-lg mb-2 ${darkTheme ? "text-white" : "text-gray-900"}`}>2. Reason for Rejection</Text>
         <TextInput
            multiline
            numberOfLines={4}
            value={reason}
            onChangeText={setReason}
            placeholder="e.g., The bottle has a large crack at the bottom and cannot hold water..."
            placeholderTextColor={darkTheme ? BRAND.gray400 : BRAND.gray500}
            className={`p-4 rounded-2xl min-h-[120px] font-semibold text-base border ${darkTheme ? "bg-white/5 border-white/10 text-white" : "bg-white border-gray-200 text-black"}`}
            style={{ textAlignVertical: "top" }}
         />
      </ScrollView>

      <View className="p-5 border-t border-gray-100 dark:border-white/5" style={{ paddingBottom: insets.bottom + 90 }}>
        <PressableScale
          onPress={submitRejection}
          disabled={isSubmitting}
          className="py-4 rounded-xl items-center shadow-sm"
          style={{ backgroundColor: TOAST.error }}
        >
          <Text className="text-white font-bold text-lg">{isSubmitting ? "Submitting for Review..." : "Submit Report"}</Text>
        </PressableScale>
      </View>
    </SafeAreaView>
  );
}
