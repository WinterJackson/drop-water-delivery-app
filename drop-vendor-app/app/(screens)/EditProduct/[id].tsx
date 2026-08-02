import { errorMessage } from "@/API/errors";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { UIThemeContext } from "@/context/ThemeContext";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useContext, useState, useEffect } from "react";
import { useImageUpload } from "@/hooks/useImageUpload";
import { Toast } from "@/lib/toast";
import * as Haptics from "expo-haptics";
import {
    ActivityIndicator,
    KeyboardAvoidingView, Platform,
    ScrollView, StatusBar,
    Text, TextInput, View,
} from "react-native";
import { Image } from "expo-image";
import { BRAND } from "@/constants/brandColors";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import PressableScale from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { useQueryClient } from "@tanstack/react-query";
import { VendorEditProductSkeleton } from "@/components/skeletons/ContextualSkeletons";

export default function EditProduct() {
  const { id } = useLocalSearchParams();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { get, put } = useApiRequest();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { imageUri, uploading: imageUploading, error, pickImage, handleImageUpload } = useImageUpload();

  const [loadingData, setLoadingData] = useState(true);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  /**
   * What the server last gave us for this product's image.
   *
   * The API returns a **presigned** URL, valid for 15 minutes. Sending it back
   * unchanged would store an expiring URL as the product's permanent image, and
   * the photo would 403 for every customer a quarter of an hour later. So when
   * the vendor has not touched the image, `image_url` is simply left out of the
   * update — it is optional on the server and an absent field means "unchanged".
   */
  const [serverImageUrl, setServerImageUrl] = useState("");
  const [price, setPrice] = useState("");
  const [discount, setDiscount] = useState("0");
  const [capacity, setCapacity] = useState("");
  const [weightKg, setWeightKg] = useState("20");
  const [minQty, setMinQty] = useState("1");
  const [unit, setUnit] = useState("litres");
  const [stock, setStock] = useState("");
  const [lowStockThreshold, setLowStockThreshold] = useState("5");
  const [loading, setLoading] = useState(false);

  const [loadError, setLoadError] = useState<string | null>(null);

  const fetchProduct = useCallback(async () => {
    setLoadError(null);
    try {
      const data = await get<any>(VendorApiRoutes.GetProduct(id as string).path);
      setName(data.name || "");
      setDescription(data.description || "");
      setImageUrl(data.image_url || "");
      setServerImageUrl(data.image_url || "");
      setPrice(data.price?.toString() || "");
      setDiscount(data.discount?.toString() || "0");
      setCapacity(data.capacity?.toString() || "");
      setWeightKg(data.weight_kg?.toString() || "20");
      setMinQty(data.minimum_order_qty?.toString() || "1");
      setUnit(data.unit || "litres");
      setStock(data.stock?.toString() || "");
      setLowStockThreshold(data.low_stock_threshold?.toString() ?? "5");
    } catch (e) {
      // The form must not render half-populated: saving it would blank whatever
      // failed to load. Previously the fields simply stayed empty and the
      // vendor could submit them over a perfectly good product.
      setLoadError(errorMessage(e, "Could not load this product."));
    } finally {
      setLoadingData(false);
    }
  }, [id, get]);

  useEffect(() => {
    if (id) fetchProduct();
  }, [id, fetchProduct]);

  const handleSubmit = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    if (!name || !price || !capacity || !stock || !weightKg) {
      Toast.error("Validation Error", "Please fill in all required fields (Name, Price, Capacity, Weight, Stock).");
      return;
    }
    
    let finalImageUrl = imageUrl;
    if (imageUri && !imageUrl.startsWith('http')) {
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
    const payload: Record<string, unknown> = {
      name, description,
      price: parseFloat(price), discount: parseFloat(discount || "0"),
      capacity: parseFloat(capacity),
      weight_kg: parseFloat(weightKg),
      minimum_order_qty: parseInt(minQty || "1"),
      unit, stock: parseInt(stock),
      low_stock_threshold: parseInt(lowStockThreshold || "0") || 0,
    };
    // Only send the image when it actually changed — see `serverImageUrl`.
    if (finalImageUrl && finalImageUrl !== serverImageUrl) {
      payload.image_url = finalImageUrl;
    }

    try {
      await put(VendorApiRoutes.UpdateProduct(id as string).path, payload);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      Toast.success("Product updated!", "Your product details have been saved.");
      queryClient.invalidateQueries({ queryKey: ["vendorProducts"] });
      router.back();
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      Toast.error("Error", errorMessage(e, "Could not save those changes."));
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = `px-5 py-4 rounded-[16px] text-base font-bold border ${darkTheme ? "bg-surface-container text-white border-outline-variant focus:border-accentbg" : "bg-white text-slate-900 border-slate-200 focus:border-accentbg"}`;
  const labelStyle = `text-xs font-bold mb-2 ml-1 uppercase tracking-wider ${darkTheme ? "text-slate-400" : "text-slate-500"}`;

  if (loadingData) {
    return (
      <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
          <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
          <View className="flex-row items-center px-4 py-3 pb-4 mb-2">
            <PressableScale onPress={() => router.back()} className="mr-4">
              <BackButtonMinimal />
            </PressableScale>
            <Text className={`text-xl font-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Edit Product</Text>
          </View>
          <VendorEditProductSkeleton />
      </SafeAreaView>
    );
  }

  if (loadError) {
    return (
      <SafeAreaView className={`flex-1 items-center justify-center px-8 ${darkTheme ? "bg-black" : ""}`}>
        <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
        <Ionicons name="cloud-offline-outline" size={44} color={darkTheme ? BRAND.gray400 : BRAND.gray500} />
        <Text className={`text-lg font-bold mt-4 mb-2 text-center ${darkTheme ? "text-white" : "text-slate-900"}`}>
          Couldn&apos;t load this product
        </Text>
        <Text className={`text-center mb-6 ${darkTheme ? "text-slate-400" : "text-slate-600"}`}>{loadError}</Text>
        <View className="flex-row gap-3">
          <PressableScale onPress={() => { setLoadingData(true); fetchProduct(); }} className="bg-accentbg px-6 py-3 rounded-xl">
            <Text className="text-white font-bold">Try again</Text>
          </PressableScale>
          <PressableScale onPress={() => router.back()} className={`px-6 py-3 rounded-xl border ${darkTheme ? "border-slate-700" : "border-slate-200"}`}>
            <Text className={`font-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Go back</Text>
          </PressableScale>
        </View>
      </SafeAreaView>
    );
  }

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
          <PressableScale onPress={() => router.back()} className="mr-4">
            <BackButtonMinimal />
          </PressableScale>
          <Text className={`text-xl font-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Edit Product</Text>
        </View>
      </View>

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} className="flex-1">
         <ScrollView className="flex-1" contentContainerStyle={{ paddingBottom: 120, paddingTop: 24, paddingHorizontal: 20 }} showsVerticalScrollIndicator={false}>
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
                {imageUri || imageUrl ? (
                  <View className="gap-3">
                    <View className="aspect-[4/3] w-full bg-slate-100 dark:bg-slate-800 rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-700">
                      <Image source={{ uri: imageUri || imageUrl }} style={{ width: '100%', height: '100%' }} contentFit="cover" cachePolicy="disk" transition={200} />
                    </View>
                    {error ? <Text className="text-sm text-red-500 font-medium">{error}</Text> : null}
                    <PressableScale 
                      activeOpacity={0.8}
                      onPress={pickImage}
                      className={`py-3 px-4 rounded-xl items-center ${imageUploading ? "bg-slate-200 dark:bg-slate-800" : "bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700"}`}
                      disabled={imageUploading}
                    >
                      <Text className={`font-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>{imageUploading ? "Uploading..." : "Change Image"}</Text>
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
                      <Text className={`font-semibold ${darkTheme ? "text-slate-300" : "text-slate-600"}`}>
                        {imageUploading ? "Uploading..." : "Tap to upload image"}
                      </Text>
                    </PressableScale>
                    
                    <View className="flex-row items-center gap-4">
                      <View className={`flex-1 h-[1px] ${darkTheme ? "bg-slate-800" : "bg-slate-200"}`} />
                      <Text className={`text-xs font-semibold uppercase ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>OR</Text>
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
              <Text className="text-white font-bold text-lg">{loading ? "Saving..." : "Save Changes"}</Text>
            </PressableScale>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
