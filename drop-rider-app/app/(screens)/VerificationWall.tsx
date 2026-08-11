import React, { useState, useContext, useEffect, useRef } from 'react';
import { View, ScrollView, TouchableOpacity, Image, ActivityIndicator, StatusBar } from 'react-native';
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from 'react-native-safe-area-context';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND } from '@/constants/brandColors';
import * as ImagePicker from 'expo-image-picker';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '@clerk/clerk-expo';
import { useRouter } from 'expo-router';
import RiderApiRoutes from '@/API/routes/RiderApiRoutes';
import { Toast } from '@/lib/toast';
import { PressableScale } from '@/components/ui/PressableScale';
import { Popup } from "@/lib/popup";
import { RiderVerificationSkeleton } from '@/components/skeletons/ContextualSkeletons';
import { useInvalidateKycStatus, useKycStatus } from '@/hooks/queries/useKycStatus';
import { apiFetch } from '@/API/apiFetch';
import { errorMessage } from '@/API/errors';

export default function VerificationWall() {
  const { currentTheme } = useContext<any>(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { getToken } = useAuth();
  const router = useRouter();

  const [submitting, setSubmitting] = useState(false);

  // The same cache entry the `(screens)` gate reads. This screen used to hold
  // the status in `useState` from its own fetch, so after an approval the wall
  // saw "approved" and pushed to `/(screens)` while the gate's cache still said
  // "pending" and pushed straight back — a redirect loop.
  const { data: status, isPending, isError, refetch, isFetching } = useKycStatus();
  const invalidateKycStatus = useInvalidateKycStatus();
  const kycStatus = status?.kyc_status ?? "unsubmitted";
  const checkStatus = () => { refetch(); };

  const [vehicleType, setVehicleType] = useState("motorbike");
  const [plateNumber, setPlateNumber] = useState("");
  const [idFront, setIdFront] = useState<string | null>(null);
  const [idBack, setIdBack] = useState<string | null>(null);
  const [driverLicense, setDriverLicense] = useState<string | null>(null);

  // Prefill from whatever the rider already told us, so a resubmission after a
  // rejection is not a blank form.
  const prefilled = useRef(false);
  useEffect(() => {
    if (prefilled.current || !status) return;
    prefilled.current = true;
    if (status.vehicle_type) setVehicleType(status.vehicle_type);
    if (status.plate_number) setPlateNumber(status.plate_number);
  }, [status]);

  useEffect(() => {
    if (kycStatus === "approved") router.replace("/(screens)");
  }, [kycStatus, router]);

  const pickImage = async (setter: React.Dispatch<React.SetStateAction<string | null>>) => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Popup.show({
        title: 'Permission Denied', 
        message: 'Sorry, we need camera roll permissions to make this work!',
        isAlertOnly: true
      });
      return;
    }

    let result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      quality: 0.7,
    });

    if (!result.canceled) {
      setter(result.assets[0].uri);
    }
  };

  const handleSubmit = async () => {
    if (!plateNumber.trim()) {
      Toast.error("Required", "Please enter your vehicle plate number.");
      return;
    }
    if (!idFront || !idBack) {
      Toast.error("Required", "Please upload both front and back of your National ID.");
      return;
    }
    if ((vehicleType === "motorbike" || vehicleType === "truck") && !driverLicense) {
      Toast.error("Required", "Driver License is required for this vehicle type.");
      return;
    }

    setSubmitting(true);
    try {
      const token = await getToken();
      const formData = new FormData();
      
      formData.append("plate_number", plateNumber);
      formData.append("vehicle_type", vehicleType);
      
      formData.append("id_card_front", {
        uri: idFront,
        name: 'id_front.jpg',
        type: 'image/jpeg',
      } as any);

      formData.append("id_card_back", {
        uri: idBack,
        name: 'id_back.jpg',
        type: 'image/jpeg',
      } as any);

      if (driverLicense) {
        formData.append("driver_license", {
          uri: driverLicense,
          name: 'license.jpg',
          type: 'image/jpeg',
        } as any);
      }

      // Identity documents over a phone connection need more than the default
      // 15s, and a timeout here restarts the whole submission.
      await apiFetch(RiderApiRoutes.KycUpload.path, {
        method: "POST",
        token,
        formData,
        timeoutMs: 120_000,
      });

      // Refetch rather than patching local state: the gate reads this same
      // cache entry and must move to "pending" with us.
      await invalidateKycStatus();
      Toast.success("Success", "Documents uploaded. Your profile is now under review.");
    } catch (e) {
      // The backend names the file it rejected — "ID card front must be a
      // genuine JPG, PNG, or PDF file" — which is the only way the rider can
      // fix it.
      Toast.error("Upload Failed", errorMessage(e, "Could not connect to the server."));
    } finally {
      setSubmitting(false);
    }
  };

  if (isPending) {
    return (
      <SafeAreaView className={`flex-1 ${darkTheme ? "bg-[#0A0A0A]" : ""}`}>
        <StatusBar translucent barStyle={darkTheme ? "light-content" : "dark-content"} />
        <View className="px-5 pt-4 pb-2 border-b border-gray-200 dark:border-gray-800">
          <Text className={`text-2xl font-heading-semibold ${darkTheme ? "text-white" : "text-black"}`}>Verify Identity</Text>
          <Text className={`text-sm mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
            To maintain platform safety, please verify your identity before accessing deliveries.
          </Text>
        </View>
        <ScrollView className="flex-1" contentContainerStyle={{ paddingBottom: 100 }}>
            <RiderVerificationSkeleton />
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (isError) {
    return (
      <SafeAreaView className={`flex-1 items-center justify-center px-8 ${darkTheme ? "bg-[#0A0A0A]" : ""}`}>
        <StatusBar translucent barStyle={darkTheme ? "light-content" : "dark-content"} />
        <Ionicons name="cloud-offline-outline" size={48} color={BRAND.primary} />
        <Text className={`text-lg font-sans-bold mt-4 text-center ${darkTheme ? "text-white" : "text-black"}`}>
          Couldn't check your verification status
        </Text>
        <PressableScale onPress={checkStatus} disabled={isFetching} className="mt-6 h-[48px] px-8 rounded-full items-center justify-center bg-gray-100 dark:bg-gray-800" style={{ backgroundColor: BRAND.primary }}>
          {isFetching
            ? <ActivityIndicator size="small" color="#fff" />
            : <Text className="text-white font-sans-bold">Retry</Text>}
        </PressableScale>
      </SafeAreaView>
    );
  }

  if (kycStatus === "pending") {
    return (
      <SafeAreaView className={`flex-1 ${darkTheme ? "bg-[#0A0A0A]" : ""}`}>
        <StatusBar translucent barStyle={darkTheme ? "light-content" : "dark-content"} />
        <View className="flex-1 items-center justify-center px-6">
          <View className="w-24 h-24 rounded-full bg-orange-500/10 items-center justify-center mb-6">
            <Ionicons name="time-outline" size={48} color="#f97316" />
          </View>
          <Text className={`text-2xl font-heading-semibold text-center mb-3 ${darkTheme ? "text-white" : "text-gray-900"}`}>
            Verification Pending
          </Text>
          <Text className={`text-center text-base leading-relaxed ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
            Your documents have been received and are currently under review by our compliance team. This usually takes less than 24 hours.
          </Text>
          <PressableScale onPress={checkStatus} disabled={isFetching} className="mt-10 px-8 py-3 rounded-full bg-gray-100 dark:bg-gray-800">
             {isFetching
               ? <ActivityIndicator size="small" color={BRAND.primary} />
               : <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>Refresh Status</Text>}
          </PressableScale>

          {/* "Less than 24 hours" is a promise, and the rider on hour 70 has
              nowhere to take it. This is the one way out of this screen. */}
          <PressableScale
            onPress={() => router.push("/(screens)/Support" as any)}
            className="mt-4 px-6 py-3"
          >
            <Text className="font-sans-semibold" style={{ color: BRAND.primary }}>
              Waiting too long? Contact support
            </Text>
          </PressableScale>
        </View>
      </SafeAreaView>
    );
  }

  const renderImageUpload = (title: string, subtitle: string, uri: string | null, setter: any) => (
    <View className="mb-6">
      <Text className={`text-sm font-sans-bold mb-1 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>{title}</Text>
      <Text className={`text-xs mb-3 ${darkTheme ? "text-gray-500" : "text-gray-500"}`}>{subtitle}</Text>
      
      <TouchableOpacity 
        onPress={() => pickImage(setter)}
        className={`h-40 rounded-xl border-2 border-dashed items-center justify-center overflow-hidden
          ${darkTheme ? "border-gray-700 bg-[#151515]" : "border-gray-300 bg-white"}
          ${uri ? "border-solid border-primary" : ""}`}
        style={uri ? { borderColor: BRAND.primary } : {}}
      >
        {uri ? (
          <Image source={{ uri }} className="w-full h-full" resizeMode="cover" />
        ) : (
          <View className="items-center">
            <Ionicons name="camera-outline" size={32} color={BRAND.primary} />
            <Text className={`mt-2 font-sans-medium ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Tap to Upload Image</Text>
          </View>
        )}
      </TouchableOpacity>
    </View>
  );

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-[#0A0A0A]" : ""}`}>
      <StatusBar translucent barStyle={darkTheme ? "light-content" : "dark-content"} />
      
      <View className="px-5 pt-4 pb-2 border-b border-gray-200 dark:border-gray-800">
        <Text className={`text-2xl font-heading-semibold ${darkTheme ? "text-white" : "text-black"}`}>Verify Identity</Text>
        <Text className={`text-sm mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
          To maintain platform safety, please verify your identity before accessing deliveries.
        </Text>
      </View>

      <ScrollView className="flex-1 px-5 pt-6" contentContainerStyle={{ paddingBottom: 100 }}>
        
        {kycStatus === "rejected" && (
          <View className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl mb-6">
            <Text className="text-red-500 font-sans-bold mb-1">Verification Failed</Text>
            {/* The reviewer's actual words, when we have them. The generic
                sentence below is a fallback for rejections recorded before the
                reason was stored — on its own it tells the rider nothing they
                can act on, so they resubmit the same document and wait again. */}
            <Text className="text-red-400 text-sm">
              {status?.rejection_reason?.trim()
                ? status.rejection_reason
                : "Your previous submission was rejected. Please ensure all documents are clear, valid, and unexpired."}
            </Text>
          </View>
        )}

        <Text className={`text-sm font-sans-bold mb-3 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Vehicle Type</Text>
        <View className="flex-row gap-2 mb-6">
          {["motorbike", "tuktuk", "truck"].map((type) => (
            <PressableScale 
              key={type}
              onPress={() => setVehicleType(type)}
              className={`flex-1 py-3 rounded-lg border items-center justify-center ${vehicleType === type ? 'border-primary bg-primary/10' : (darkTheme ? 'border-gray-800 bg-[#151515]' : 'border-gray-200 bg-white')}`}
              style={vehicleType === type ? { borderColor: BRAND.primary, backgroundColor: darkTheme ? `${BRAND.primary}20` : `${BRAND.primary}10` } : {}}
            >
              <Text className={`capitalize font-sans-semibold ${vehicleType === type ? 'text-primary' : (darkTheme ? 'text-gray-400' : 'text-gray-500')}`} style={vehicleType === type ? { color: BRAND.primary } : {}}>
                {type}
              </Text>
            </PressableScale>
          ))}
        </View>

        <View className="mb-8">
          <Text className={`text-sm font-sans-bold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>License Plate Number</Text>
          <TextInput
            value={plateNumber}
            onChangeText={setPlateNumber}
            placeholder="e.g., KCA 123G"
            placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3b8"}
            className={`px-4 py-4 rounded-xl border ${darkTheme ? "bg-[#151515] border-gray-800 text-white" : "bg-white border-gray-200 text-gray-900"} font-sans-medium`}
            autoCapitalize="characters"
          />
        </View>

        {renderImageUpload("National ID (Front)", "Clear photo of the front of your ID card", idFront, setIdFront)}
        {renderImageUpload("National ID (Back)", "Clear photo of the back of your ID card", idBack, setIdBack)}
        
        {vehicleType !== "tuktuk" && renderImageUpload("Driver's License", "Clear photo of your valid driver's license", driverLicense, setDriverLicense)}

        <PressableScale 
          onPress={handleSubmit} 
          disabled={submitting}
          className="w-full py-4 rounded-xl items-center justify-center mt-4"
          style={{ backgroundColor: BRAND.primary, opacity: submitting ? 0.7 : 1 }}
        >
          {submitting ? (
            <ActivityIndicator color={BRAND.white} />
          ) : (
            <Text className="text-white font-sans-bold text-lg">Submit Documents</Text>
          )}
        </PressableScale>

      </ScrollView>
    </SafeAreaView>
  );
}
