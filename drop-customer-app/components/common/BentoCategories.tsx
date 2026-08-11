import React, { useContext } from 'react';
import { View, Image } from 'react-native';
import { Text } from '@/components/ui/Text';
import { UIThemeContext } from '@/context/ThemeContext';
import { PressableScale } from '@/components/ui/PressableScale';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { BRAND, TOAST } from "@/constants/brandColors";
import { useLastCompletedOrder } from '@/hooks/queries/useOrders';

export default function BentoCategories() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';
  const router = useRouter();
  
  const { data: lastOrder } = useLastCompletedOrder();

  return (
    <View className="px-5 mt-2 mb-4">
      <View className="flex-row gap-4 h-[240px]">
        {/* Left Big Card (Refill & Wholesale) */}
        <PressableScale 
          onPress={() => {
            if (lastOrder && lastOrder.vendor) {
              router.push(`/(screens)/repeat-order?vendorId=${lastOrder.vendor.id}`);
            } else {
              router.push(`/(screens)/Search?mode=refill_wholesale&category=dispenser_refill`);
            }
          }}
          style={{ flex: 1 }}
        >
          <View 
            className={`flex-1 rounded-[24px] p-4 flex-col justify-between overflow-hidden border ${darkTheme ? "bg-surface-container" : "bg-white border-gray-100"}`}
            style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
          >
            <View className="z-10">
              {lastOrder && lastOrder.vendor ? (
                <>
                  <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Reorder</Text>
                  <Text className={`text-xs ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`} numberOfLines={1}>From {lastOrder.vendor.business_name}</Text>
                </>
              ) : (
                <>
                  <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Refill &</Text>
                  <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Wholesale</Text>
                  <Text className={`text-xs mt-1 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>20L & Bulk Orders</Text>
                </>
              )}
            </View>
            <View className="self-end z-10 flex-row items-center gap-2">
              {lastOrder && lastOrder.vendor?.profile_pic && (
                <Image source={{ uri: lastOrder.vendor.profile_pic }} className="w-10 h-10 rounded-full bg-gray-200" />
              )}
              <View className={`p-3 rounded-full ${darkTheme ? "bg-[#002d47]" : "bg-accentbg/10"}`}>
                <Ionicons name="water-outline" size={24} color={BRAND.primary} />
              </View>
            </View>
            <View className="absolute -bottom-4 -right-4 opacity-10">
              <Ionicons name="water" size={120} color={BRAND.primary} />
            </View>
          </View>
        </PressableScale>

        {/* Right Column with 2 Smaller Cards */}
        <View className="flex-1 flex-col gap-4">
          {/* Top Small Card */}
          <PressableScale onPress={() => router.push('/(screens)/VendorDirectory')} style={{ flex: 1 }}>
            <View 
              className={`flex-1 rounded-[24px] p-4 flex-row items-center justify-between border ${darkTheme ? "bg-surface-container" : "bg-white border-gray-100"}`}
              style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
            >
              <View className="z-10 flex-1 pr-2">
                <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Nearby Vendors</Text>
                <Text className={`text-xs ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Directory</Text>
              </View>
              <Ionicons name="storefront-outline" size={32} color={BRAND.primary} className="z-10" />
            </View>
          </PressableScale>

          {/* Bottom Small Card */}
          <PressableScale onPress={() => router.push('/(screens)/Search?mode=deals')} style={{ flex: 1 }}>
            <View 
              className={`flex-1 rounded-[24px] p-4 flex-row items-center justify-between border ${darkTheme ? "bg-surface-container" : "bg-white border-gray-100"}`}
              style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
            >
              <View className="z-10 flex-1 pr-2">
                <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Deals & Offers</Text>
                <Text className={`text-xs ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Discounts</Text>
              </View>
              <Ionicons name="pricetag-outline" size={32} color={BRAND.primary} className="z-10" />
            </View>
          </PressableScale>
        </View>
      </View>
    </View>
  );
}
