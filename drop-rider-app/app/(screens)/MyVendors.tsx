import { ApiError, errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import React, { useContext, useEffect, useRef, useState } from "react";
import { View, StatusBar, FlatList, RefreshControl, Image, TouchableOpacity, ActivityIndicator, Linking } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { UIThemeContext } from "@/context/ThemeContext";
import { useRouter } from "expo-router";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { Toast } from "@/lib/toast";
import { BRAND } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
import { FlashList as OriginalFlashList } from "@shopify/flash-list";
import { Popup } from "@/lib/popup";
import { RiderDiscoverVendorCardSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { useDebounce } from "@/hooks/useDebounce";

const FlashList = OriginalFlashList as any;

export default function MyVendors() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const { get, del } = useApiRequest();
  const router = useRouter();
  
  const [vendors, setVendors] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  
  const debouncedSearchQuery = useDebounce(searchQuery, 500);

  /**
   * Which search this component is currently showing.
   *
   * Two searches in flight can finish in either order — "wa" over a slow cell
   * and "waterpoint" over a good one — and the slower, staler one wins simply
   * by landing last. The result is a list that does not match the box above it,
   * which reads as the search being broken. Every response is checked against
   * the term that is current when it arrives, and a stale one is dropped.
   */
  const inFlightFor = useRef<string>("");

  const fetchRegisteredVendors = async (search?: string) => {
    const term = search ?? "";
    inFlightFor.current = term;
    try {
      const rows = await get<any[]>(RiderApiRoutes.RegisteredVendors(search).path);
      if (inFlightFor.current !== term) return;
      setVendors(rows);
    } catch (e) {
      if (inFlightFor.current !== term) return;
      if (e instanceof ApiError && e.status === 401) return;
      Toast.error("Error", errorMessage(e, "Failed to fetch vendors"));
    } finally {
      if (inFlightFor.current === term) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  };

  useEffect(() => {
    fetchRegisteredVendors(debouncedSearchQuery);
  }, [debouncedSearchQuery]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchRegisteredVendors(debouncedSearchQuery);
  };

  const handleWithdraw = async (vendorId: string, businessName: string) => {
    Popup.show({
      title: "Withdraw Application",
      message: `Are you sure you want to withdraw your application to ${businessName}?`,
      cancelText: "Cancel",
      confirmText: "Withdraw",
      isDestructive: true,
      onConfirm: async () => {
          Popup.hide();
          setWithdrawingId(vendorId);
          try {
            await del(RiderApiRoutes.WithdrawApplication(vendorId).path);
            Toast.success("Success", "Application withdrawn");
            setVendors(prev => prev.filter(v => v.vendor_id !== vendorId));
          } catch (e) {
            Toast.error("Cannot Withdraw", errorMessage(e, "Action failed"));
          } finally {
            setWithdrawingId(null);
          }
        }
    });
  };

  const renderStatusBadge = (status: string) => {
    let bgColor = darkTheme ? "bg-yellow-500/20" : "bg-yellow-100";
    let textColor = darkTheme ? "text-yellow-400" : "text-yellow-700";
    let iconName: keyof typeof Ionicons.glyphMap = "time-outline";
    let statusText = "Pending";

    if (status === "approved") {
      bgColor = darkTheme ? "bg-green-500/20" : "bg-green-100";
      textColor = darkTheme ? "text-green-400" : "text-green-700";
      iconName = "checkmark-circle-outline";
      statusText = "Approved";
    } else if (status === "rejected") {
      bgColor = darkTheme ? "bg-red-500/20" : "bg-red-100";
      textColor = darkTheme ? "text-red-400" : "text-red-700";
      iconName = "close-circle-outline";
      statusText = "Rejected";
    }

    return (
      <View className={`flex-row items-center px-3 py-1 rounded-full ${bgColor}`}>
        <Ionicons name={iconName} size={14} color={darkTheme ? (status === 'approved' ? '#4ade80' : status === 'rejected' ? '#f87171' : '#facc15') : (status === 'approved' ? '#15803d' : status === 'rejected' ? '#b91c1c' : '#a16207')} />
        <Text className={`text-xs font-sans-semibold ml-1 ${textColor}`}>
          {statusText}
        </Text>
      </View>
    );
  };

  const renderVendor = ({ item }: { item: any }) => {
    const isWithdrawing = withdrawingId === item.vendor_id;

    return (
      <View className={`p-4 mb-4 rounded-2xl border ${darkTheme ? "bg-gray-900 border-gray-800" : "bg-white border-gray-100 shadow-sm"}`}>
        <View className="flex-row items-center">
          <View className={`w-14 h-14 rounded-xl overflow-hidden border ${darkTheme ? "border-gray-800" : "border-gray-100"}`}>
            {item.profile_pic ? (
              <Image source={{ uri: item.profile_pic }} className="w-full h-full" resizeMode="cover" />
            ) : (
              <View className={`w-full h-full items-center justify-center ${darkTheme ? "bg-gray-800" : "bg-white"}`}>
                <Ionicons name="business-outline" size={24} color={BRAND.gray400} />
              </View>
            )}
          </View>
          
          <View className="flex-1 ml-4">
            <Text className={`text-base font-sans-bold mb-1 ${darkTheme ? "text-white" : "text-gray-900"}`} numberOfLines={1}>
              {item.business_name}
            </Text>
            <View className="flex-row items-center mb-2">
              <Ionicons name="location-outline" size={14} color={BRAND.gray400} />
              <Text className={`text-xs ml-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`} numberOfLines={1}>
                {item.address || "No address provided"}
              </Text>
            </View>
            <View className="self-start">
              {renderStatusBadge(item.status)}
            </View>
          </View>
        </View>

        {item.status === "pending" && (
          <TouchableOpacity
            onPress={() => handleWithdraw(item.vendor_id, item.business_name)}
            disabled={isWithdrawing}
            className={`mt-4 py-3 rounded-xl border flex-row justify-center items-center ${darkTheme ? "border-red-900/50 bg-red-900/20" : "border-red-100 bg-red-50"}`}
          >
            {isWithdrawing ? (
              <ActivityIndicator size="small" color="#ef4444" />
            ) : (
              <>
                <Ionicons name="trash-outline" size={16} color="#ef4444" />
                <Text className="text-red-500 font-sans-semibold ml-2">Withdraw Application</Text>
              </>
            )}
          </TouchableOpacity>
        )}
        
        {item.status === "approved" && (
          <TouchableOpacity
            onPress={() => {
              if (item.phone_number) {
                Linking.openURL(`tel:${item.phone_number}`);
              } else {
                Toast.error("No Phone", "This vendor has no phone number listed.");
              }
            }}
            className={`mt-4 py-3 rounded-xl flex-row justify-center items-center ${darkTheme ? "bg-gray-800" : "bg-white"}`}
          >
            <Ionicons name="call-outline" size={16} color={BRAND.primary} />
            <Text className={`font-sans-semibold ml-2 ${darkTheme ? "text-white" : "text-black"}`}>Contact Vendor</Text>
          </TouchableOpacity>
        )}
      </View>
    );
  };

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : "bg-[#f8f9fa]"}`}>
      <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />
      
      {/* Header */}
      <View 
          className="flex-row items-center px-4 py-3 pb-4"
          style={{ 
              backgroundColor: darkTheme ? "#000" : "#fff",
              borderBottomWidth: 1, 
              borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
              ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }),
              zIndex: 10
          }}
      >
          <TouchableOpacity onPress={() => router.back()} className="mr-4">
              <BackButtonMinimal />
          </TouchableOpacity>
          <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
              My Vendors
          </Text>
      </View>

      {/* Content */}
      <View style={{ flex: 1 }}>
        {/* Search Bar */}
        <View className="px-5 pt-2 pb-4">
          <View className={`flex-row items-center px-4 py-3 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white border border-gray-100 shadow-sm"}`}>
              <Ionicons name="search" size={20} color={BRAND.primary} />
              <TextInput
                  value={searchQuery}
                  onChangeText={setSearchQuery}
                  placeholder="Search your vendors..."
                  placeholderTextColor={darkTheme ? "#9ca3af" : "#6b7280"}
                  className={`flex-1 font-sans-semibold ml-2 ${darkTheme ? "text-white" : "text-black"}`}
              />
          </View>
        </View>

        {loading ? (
        <View className="flex-1 px-4 pt-4">
           {[1, 2, 3, 4, 5].map(i => <RiderDiscoverVendorCardSkeleton key={i} />)}
        </View>
      ) : vendors.length === 0 ? (
        <View className="flex-1 justify-center items-center px-6">
          <View className={`w-24 h-24 rounded-full items-center justify-center mb-6 ${darkTheme ? "bg-gray-900" : "bg-white"}`}>
            <Ionicons name="briefcase-outline" size={48} color={BRAND.gray400} />
          </View>
          <Text className={`text-xl font-sans-bold mb-2 text-center ${darkTheme ? "text-white" : "text-gray-900"}`}>
            No Vendors Yet
          </Text>
          <Text className={`text-center mb-8 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
            You haven't applied to any vendors. Go to the Discover Vendors page to find water suppliers near your operation base.
          </Text>
          <TouchableOpacity 
            onPress={() => router.push("/(screens)/DiscoverVendors")}
            className="px-8 py-4 rounded-xl"
            style={{ backgroundColor: BRAND.primary }}
          >
            <Text className="text-white font-sans-bold text-base">Discover Vendors</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <View className="flex-1 px-4 pt-4">
          <FlashList
            data={vendors}
            renderItem={renderVendor}
            // A row here owns per-vendor state (`withdrawingId`), so recycling one
            // against a different vendor shows the wrong store as withdrawing.
            keyExtractor={(item: any) => String(item.vendor_id)}
            estimatedItemSize={150}
            refreshControl={
              <RefreshControl
                refreshing={refreshing}
                onRefresh={handleRefresh}
                tintColor={BRAND.primary}
                colors={[BRAND.primary]}
              />
            }
            showsVerticalScrollIndicator={false}
            contentContainerStyle={{ paddingBottom: 100 }}
          />
        </View>
      )}
      </View>
    </SafeAreaView>
  );
}
