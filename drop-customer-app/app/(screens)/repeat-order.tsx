import { errorMessage } from "@/API/errors";
import { useTabBarClearance } from '@/constants/layout';
import React, { useContext } from 'react';
import { View, ScrollView, StatusBar } from 'react-native';
import { Text } from '@/components/ui/Text';
import { Image as ExpoImage } from 'expo-image';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { UIThemeContext } from '@/context/ThemeContext';
import Context from '@/context/context';
import { Ionicons } from '@expo/vector-icons';
import { PressableScale } from '@/components/ui/PressableScale';
import DropButton from '@/components/ui/DropButton';
import GlassCard from '@/components/ui/GlassCard';
import { useLastOrderFromVendor } from '@/hooks/queries/useVendorFavorites';
import { useVendorDetails } from '@/hooks/queries/useProducts';
import { useAddToCart } from '@/hooks/queries/useCart';
import { useUserDetails } from '@/hooks/queries/useUser';
import { Toast } from '@/lib/toast';
import { BRAND, TOAST } from "@/constants/brandColors";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { RepeatOrderSkeleton } from "@/components/skeletons/ContextualSkeletons";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";
import { formatMoney, sumMoney } from "@/utils/money";

export default function RepeatOrderScreen() {
    const tabBarClearance = useTabBarClearance();
  const { vendorId } = useLocalSearchParams<{ vendorId: string }>();
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';
  const { fetchCart } = useContext(Context);
  const { data: User } = useUserDetails();

  const { data: lastOrder, isLoading, isError } = useLastOrderFromVendor(vendorId || '');

  /**
   * The store's live trading state, for the closed notice below.
   *
   * That notice used to be handed `lastOrder.vendor`, which is an
   * `OrderVendorSnippet` and carries none of `is_accepting_orders`,
   * `store_state` or `store_reason` — so it read `undefined !== false`, returned
   * null, and **had never once rendered on this screen**. This is the screen
   * where it matters most: its whole purpose is to rebuild a basket in one tap,
   * and doing that against a shut shop wastes every item added.
   */
  const { data: vendorDetails } = useVendorDetails(vendorId || '');
  const { mutateAsync: addToCartMutation, isPending: isOrdering } = useAddToCart();

  const handleRepeatOrder = async () => {
    if (!lastOrder?.order_item?.length) return;
    try {
      // Add each item from the last order to the cart in parallel
      const results = await Promise.allSettled(
        lastOrder.order_item.map((item) => 
          addToCartMutation({
            id: item.product_id,
            quantity: item.quantity
          })
        )
      );
      
      const failed = results.filter((r) => r.status === "rejected").length;
      fetchCart(); // reflect whatever DID succeed
      
      if (failed === 0) {
        Toast.success('Order Added', 'All items added to your cart!');
        router.push('/(screens)/Cart');
      } else if (failed < results.length) {
        Toast.error('Partially Added', `${results.length - failed} of ${results.length} items were added. Some may no longer be available.`);
        router.push('/(screens)/Cart');
      } else {
        Toast.error('Error', 'None of these items are available right now. Please try ordering them individually.');
      }
    } catch (e: unknown) {
      if (__DEV__) console.error('Repeat order failed:', e);
      Toast.error('Could not re-order', errorMessage(e, 'Failed to add items to cart. Please try again.'));
    }
  };

  const formatDate = (isoDate: string | null) => {
    if (!isoDate) return 'N/A';
    try {
      return new Date(isoDate).toLocaleDateString('en-KE', {
        year: 'numeric', month: 'short', day: 'numeric',
      });
    } catch {
      return isoDate;
    }
  };

  return (
    <>
      <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />
      <SafeAreaView className={`flex-1 ${darkTheme ? "bg-surface" : "bg-white"}`}>
        {/* Header */}
        <View style={{ overflow: "hidden", paddingBottom: 4 }}>
          <View 
            className="flex-row items-center px-4 py-3 pb-4 mb-2 gap-3"
            style={{ 
              backgroundColor: darkTheme ? "#000" : "#fff",
              borderBottomWidth: 1, 
              borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
              ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
            }}
          >
            <PressableScale onPress={() => router.back()} activeOpacity={0.7}>
              <BackButtonMinimal />
            </PressableScale>
            <Text className={`font-sans-bold text-xl ${darkTheme ? "text-white" : "text-black"}`}>
              Repeat Order
            </Text>
          </View>
        </View>

        {isLoading ? (
          <RepeatOrderSkeleton />
        ) : !lastOrder ? (
          <View className="flex-1 items-center justify-center px-8">
            <Ionicons name="receipt-outline" size={64} color={BRAND.primary} />
            <Text className={`font-sans-bold text-lg mt-4 text-center ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
              No Previous Orders
            </Text>
            <Text className={`text-sm text-center mt-2 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
              You haven't ordered from this vendor yet. Browse their products to place your first order!
            </Text>
            <View className="mt-6 w-full">
              <DropButton
                title="Browse Products"
                onPress={() => {
                  router.back();
                  if (vendorId) {
                    router.push(`/(screens)/vendor/${vendorId}`);
                  }
                }}
              />
            </View>
          </View>
        ) : (
          <>
            <ScrollView contentContainerStyle={{ padding: 20, gap: 20, paddingBottom: tabBarClearance }}>
              {/* Vendor Info */}
              <GlassCard darkTheme={darkTheme} className="flex-row items-center gap-4 p-4">
                <View className={`w-12 h-12 rounded-full items-center justify-center ${darkTheme ? "bg-primary-container/20" : "bg-blue-50"}`}>
                  <Ionicons name="storefront-outline" size={24} color={BRAND.primary} />
                </View>
                <View className="flex-1">
                  <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
                    {lastOrder.vendor?.business_name || "Vendor"}
                  </Text>
                  <Text className={`text-sm ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
                    Last Order: {formatDate(lastOrder.created_at)}
                  </Text>
                  {/* This screen exists to put a whole basket together in one
                      tap. Doing that against a shop that is shut is the most
                      wasted version of the trip — every item added, then
                      refused at the last step. */}
                  <View className="mt-1">
                    <StoreClosedNotice store={vendorDetails} compact />
                  </View>
                </View>
              </GlassCard>

              {/* Order Items */}
              <View>
                <Text className={`font-sans-bold text-lg mb-3 ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Order Details</Text>
                <GlassCard darkTheme={darkTheme} className="p-4 gap-4">
                  {(lastOrder.order_item ?? []).map((item, index) => (
                    <View key={item.id} className={`flex-row justify-between items-center ${index !== (lastOrder.order_item?.length ?? 0) - 1 ? "border-b pb-4" : ""} ${darkTheme ? "border-outline-variant/20" : "border-gray-100"}`}>
                      <View className="flex-row items-center gap-3 flex-1">
                        <View className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-surface-container-high" : "bg-white"}`}>
                          <Text className={`font-sans-bold ${darkTheme ? "text-primary" : "text-blue-600"}`}>{item.quantity}x</Text>
                        </View>
                        <Text className={`font-sans-medium flex-1 ${darkTheme ? "text-on-surface" : "text-gray-800"}`} numberOfLines={1}>
                          {item.product?.name || "Item"}
                        </Text>
                      </View>
                      <Text className={`font-sans-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
                        {formatMoney(item.Subtotal)}
                      </Text>
                    </View>
                  ))}
                </GlassCard>
              </View>

              {/* Summary */}
              <View>
                <Text className={`font-sans-bold text-lg mb-3 ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Summary</Text>
                <GlassCard darkTheme={darkTheme} className="p-4 gap-2">
                  <View className="flex-row justify-between">
                    <Text className={`${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Subtotal</Text>
                    <Text className={`${darkTheme ? "text-on-surface" : "text-gray-800"}`}>
                      {formatMoney(sumMoney((lastOrder.order_item ?? []).map((i) => i.Subtotal)))}
                    </Text>
                  </View>
                  <View className="flex-row justify-between">
                    <Text className={`${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Delivery Fee</Text>
                    <Text className={`${darkTheme ? "text-on-surface" : "text-gray-800"}`}>
                      {formatMoney(lastOrder.delivery_fee)}
                    </Text>
                  </View>
                  <View className={`flex-row justify-between pt-2 mt-2 border-t ${darkTheme ? "border-outline-variant/20" : "border-gray-100"}`}>
                    <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Total</Text>
                    <Text className={`font-sans-bold text-lg text-primary`}>
                      {formatMoney(lastOrder.total_amount)}
                    </Text>
                  </View>
                </GlassCard>
              </View>
            </ScrollView>

            {/* Bottom Actions */}
            <View className={`px-5 py-4 border-t ${darkTheme ? "bg-surface border-outline-variant/10" : "bg-white border-gray-100"}`}>
              <DropButton
                title={isOrdering ? "Adding to Cart..." : `Repeat Order • ${formatMoney(lastOrder.total_amount)}`}
                onPress={handleRepeatOrder}
                disabled={isOrdering}
              />
            </View>
          </>
        )}
      </SafeAreaView>
    </>
  );
}
