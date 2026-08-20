import { errorMessage } from "@/API/errors";
import { useTabBarClearance } from '@/constants/layout';
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { UIThemeContext } from "@/context/ThemeContext";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useContext, useState } from "react";
import { useImageUpload } from "@/hooks/useImageUpload";
import { Toast } from "@/lib/toast";
import * as Haptics from "expo-haptics";
import {
    KeyboardAvoidingView,
    Platform,
    ScrollView,
    StatusBar,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Image } from "expo-image";
import { BRAND } from "@/constants/brandColors";
import { SafeAreaView } from "react-native-safe-area-context";
import CapabilityGate from "@/components/common/CapabilityGate";
import { PERMISSIONS } from "@/hooks/queries/useVendorProfile";
import { Ionicons } from "@expo/vector-icons";
import PressableScale from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";

function AddProductForm() {
    const tabBarClearance = useTabBarClearance();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { post } = useApiRequest();
  const queryClient = useQueryClient();
  const router = useRouter();
  const { imageUri, uploading: imageUploading, error, pickImage, handleImageUpload } = useImageUpload();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [price, setPrice] = useState("");
  const [discount, setDiscount] = useState("0");
  const [capacity, setCapacity] = useState("");
  const [weightKg, setWeightKg] = useState("20");
  const [minQty, setMinQty] = useState("1");
  const [unit, setUnit] = useState("litres");
  const [stock, setStock] = useState("");
  const [lowStockThreshold, setLowStockThreshold] = useState("5");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    // Validate required fields
    if (!name || !price || !capacity || !stock || !weightKg) {
      Toast.error("Validation Error", "Please fill in all required fields (Name, Price, Capacity, Weight, Stock).");
      return;
    }
    
    // Upload the picked photo if it has not been sent yet.
    let finalImageUrl = imageUrl;
    if (imageUri && !imageUrl.startsWith('http')) {
      // Image selected from picker but not yet uploaded
      const uploadedUrl = await handleImageUpload();
      if (!uploadedUrl) {
        Toast.error("Error", "Failed to upload image");
        return;
      }
      finalImageUrl = uploadedUrl;
    } else if (!imageUri && !imageUrl) {
      Toast.error("Error", "Please select or provide an image URL");
      return;
    }

    setLoading(true);
    const payload = {
      name, description, image_url: finalImageUrl,
      // Money goes up as a decimal string, exactly as it comes down as one.
      // `parseFloat` here put the vendor's price through a double on its way to
      // a NUMERIC column — the one number every order total on the platform is
      // built from. The trim matters: the backend takes `Decimal`, and
      // `Decimal(" 1500.55 ")` is not a number.
      price: price.trim(), discount: (discount || "0").trim(),
      capacity: parseFloat(capacity), 
      weight_kg: parseFloat(weightKg),
      minimum_order_qty: parseInt(minQty || "1"),
      unit, stock: parseInt(stock),
      low_stock_threshold: parseInt(lowStockThreshold || "0") || 0,
    };
    try {
      await post(VendorApiRoutes.CreateProduct.path, payload);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      Toast.success("Product created!", "Your product is now live.");
      // The list is cached for 60s server-side and by React Query on the client;
      // without this the vendor returns to Products and does not see what they
      // just created, which reads as the save having failed.
      queryClient.invalidateQueries({ queryKey: ["vendorProducts"] });
      router.back();
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      // The backend rejects a discount at or above the price with the two
      // numbers in the message; "Network error" hid that entirely.
      Toast.error("Error", errorMessage(e, "Could not create that product."));
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = `px-5 py-4 rounded-[16px] text-base font-sans-bold border ${darkTheme ? "bg-surface-container text-white border-outline-variant focus:border-accentbg" : "bg-white text-slate-900 border-slate-200 focus:border-accentbg"}`;
  const labelStyle = `text-xs font-sans-bold mb-2 ml-1 uppercase tracking-wider ${darkTheme ? "text-slate-400" : "text-slate-500"}`;

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
          <PressableScale onPress={() => router.back()} className="mr-4">
            <BackButtonMinimal />
          </PressableScale>
          <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Add Product</Text>
        </View>
      </View>

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} className="flex-1">
         <ScrollView className="flex-1" contentContainerStyle={{ paddingBottom: tabBarClearance, paddingTop: 24, paddingHorizontal: 20 }}>
           <View className="gap-6">
             <View>
               <Text className={labelStyle}>Product Name *</Text>
               <TextInput className={inputStyle} placeholder="e.g., 20L Refill Water" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={name} onChangeText={setName} />
             </View>
             
             <View>
               <Text className={labelStyle}>Description</Text>
               <TextInput className={`${inputStyle} min-h-[100px] text-left align-top`} placeholder="Describe the product..." placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={description} onChangeText={setDescription} multiline textAlignVertical="top" />
             </View>

              <View className="gap-3">
                <Text className={labelStyle}>Product Image *</Text>
                {imageUri ? (
                  <View className="gap-3">
                    <View className="aspect-[4/3] w-full bg-slate-100 dark:bg-slate-800 rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-700">
                      <Image source={{ uri: imageUri }} style={{ width: '100%', height: '100%' }} contentFit="cover" cachePolicy="disk" transition={200} />
                    </View>
                    {error ? <Text className="text-sm text-red-500 font-sans-medium">{error}</Text> : null}
                    <PressableScale 
                      activeOpacity={0.8}
                      onPress={pickImage}
                      className={`py-3 px-4 rounded-xl items-center ${imageUploading ? "bg-slate-200 dark:bg-slate-800" : "bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700"}`}
                      disabled={imageUploading}
                    >
                      <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>{imageUploading ? "Uploading..." : "Change Image"}</Text>
                    </PressableScale>
                  </View>
                ) : (
                  <View className="gap-4">
                    <PressableScale 
                      activeOpacity={0.8}
                      onPress={pickImage}
                      className={`py-8 rounded-2xl border-2 border-dashed items-center justify-center ${imageUploading ? "bg-accentbg/10 border-accentbg" : "bg-slate-50 dark:bg-slate-800/50 border-slate-300 dark:border-slate-700"}`}
                      disabled={imageUploading}
                    >
                      <Ionicons name="cloud-upload-outline" size={32} color={BRAND.primary} className="mb-2" />
                      <Text className={`font-sans-semibold ${darkTheme ? "text-slate-300" : "text-slate-600"}`}>
                        {imageUploading ? "Uploading..." : "Tap to upload image"}
                      </Text>
                    </PressableScale>
                    
                    <View className="flex-row items-center gap-4">
                      <View className={`flex-1 h-[1px] ${darkTheme ? "bg-slate-800" : "bg-slate-200"}`} />
                      <Text className={`text-xs font-sans-semibold uppercase ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>OR</Text>
                      <View className={`flex-1 h-[1px] ${darkTheme ? "bg-slate-800" : "bg-slate-200"}`} />
                    </View>

                    <TextInput 
                      className={inputStyle} 
                      placeholder="Paste Image URL" 
                      placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} 
                      value={imageUrl} 
                      onChangeText={setImageUrl} 
                    />
                  </View>
                )}
              </View>

            <View className="flex-row gap-4">
              <View className="flex-1">
                <Text className={labelStyle}>Price (KSH) *</Text>
                <TextInput className={inputStyle} placeholder="150" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={price} onChangeText={setPrice} keyboardType="numeric" />
              </View>
              <View className="flex-1">
                <Text className={labelStyle}>Discount</Text>
                <TextInput className={inputStyle} placeholder="0" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={discount} onChangeText={setDiscount} keyboardType="numeric" />
              </View>
            </View>

            <View className="flex-row gap-4">
              <View className="flex-1">
                <Text className={labelStyle}>Capacity *</Text>
                <TextInput className={inputStyle} placeholder="20" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={capacity} onChangeText={setCapacity} keyboardType="numeric" />
              </View>
              <View className="flex-1">
                <Text className={labelStyle}>Weight (kg) *</Text>
                <TextInput className={inputStyle} placeholder="20" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={weightKg} onChangeText={setWeightKg} keyboardType="numeric" />
              </View>
            </View>

            <View className="flex-row gap-4">
              <View className="flex-1">
                <Text className={labelStyle}>Min. Qty</Text>
                <TextInput className={inputStyle} placeholder="1" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={minQty} onChangeText={setMinQty} keyboardType="numeric" />
              </View>
              <View className="flex-1">
                <Text className={labelStyle}>Unit</Text>
                <TextInput className={inputStyle} placeholder="L or ml" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={unit} onChangeText={setUnit} />
              </View>
            </View>
            
            <View>
              <Text className={labelStyle}>Stock Quantity *</Text>
              <TextInput className={inputStyle} placeholder="100" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={stock} onChangeText={setStock} keyboardType="numeric" />
            </View>

            {/* Per product, because a shop selling 200 refills a day and one
                selling a dispenser a month cannot share a number. 0 turns the
                warning off for products where "low" means nothing. */}
            <View>
              <Text className={labelStyle}>Warn me at</Text>
              <TextInput className={inputStyle} placeholder="5" placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"} value={lowStockThreshold} onChangeText={setLowStockThreshold} keyboardType="numeric" />
              <Text className={`text-xs mt-2 ml-1 ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                You&apos;ll get one notification when stock drops to this level. Set 0 to turn it off.
              </Text>
            </View>

            <PressableScale
              activeOpacity={0.8}
              onPress={handleSubmit}
              disabled={loading}
              className={`py-4 rounded-2xl items-center mt-6 shadow-sm ${loading ? "bg-accentbg/60" : "bg-accentbg"}`}
            >
              <Text className="text-white font-sans-bold text-lg">{loading ? "Creating..." : "Create Product"}</Text>
            </PressableScale>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

/**
 * `POST /api/vendor/products` is `require_permission("manage_products")`.
 * Refusing at the door beats letting somebody fill in a name, a price, a stock
 * count and an image and only then discovering they were never allowed to.
 */
export default function AddProduct() {
  return (
    <CapabilityGate permission={PERMISSIONS.manageProducts} title="Add Product">
      <AddProductForm />
    </CapabilityGate>
  );
}
