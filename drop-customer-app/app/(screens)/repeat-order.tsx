import { errorMessage } from "@/API/errors";
import { useTabBarClearance } from '@/constants/layout';
import React, { useContext } from 'react';
import { View, ScrollView, StatusBar } from 'react-native';
import { Text } from '@/components/ui/Text';
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
import { useAddToCart, isVendorConflict, vendorConflictInfo } from '@/hooks/queries/useCart';
import { useUserDetails } from '@/hooks/queries/useUser';
import { Toast } from '@/lib/toast';
import { BRAND, TOAST } from "@/constants/brandColors";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { RepeatOrderSkeleton } from "@/components/skeletons/ContextualSkeletons";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";
import { formatMoney, sumMoney, isZeroMoney, isNegativeMoney, subtractMoney } from "@/utils/money";

export default function RepeatOrderScreen() {
    const tabBarClearance = useTabBarClearance();
  const { vendorId } = useLocalSearchParams<{ vendorId: string }>();
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';
  const { fetchCart } = useContext(Context);
  const { data: User } = useUserDetails();

  const { data: lastOrder, isLoading, isError, refetch } = useLastOrderFromVendor(vendorId || '');

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

  /**
   * A shut shop cannot take this basket, and this screen's whole purpose is to
   * build one in a single tap — so letting it run is the most wasted version of
   * the trip: every item added, then refused at checkout. `is_accepting_orders`
   * is the annotated answer from `vendor_availability`, which is the only thing
   * that decides whether a store is trading; `undefined` means the details have
   * not arrived yet and is deliberately not treated as closed.
   */
  const storeClosed = vendorDetails?.is_accepting_orders === false;

  const handleRepeatOrder = async () => {
    if (!lastOrder?.order_item?.length) return;
    try {
      const results = await Promise.allSettled(
        lastOrder.order_item.map((item) =>
          addToCartMutation({
            id: item.product_id,
            quantity: item.quantity
          })
        )
      );

      const rejected = results.filter(
        (r): r is PromiseRejectedResult => r.status === "rejected"
      );
      fetchCart(); // reflect whatever DID succeed

      // A cart already holding another store's items refuses *every* line here
      // with a 409, which the old message reported as "none of these items are
      // available right now" — the one explanation that is certainly wrong, and
      // it sent the customer looking for a stock problem that does not exist.
      const conflict = rejected.find((r) => isVendorConflict(r.reason));
      if (conflict) {
        const { existingVendor } = vendorConflictInfo(conflict.reason);
        Toast.error(
          'Your cart has another store in it',
          `Empty your cart of ${existingVendor}'s items first, then repeat this order.`
        );
        return;
      }

      const failed = rejected.length;
      if (failed === 0) {
        Toast.success('Added to cart', 'Everything from that order is in your cart.');
        router.push('/(screens)/Cart');
      } else if (failed < results.length) {
        Toast.error(
          'Some items could not be added',
          `${results.length - failed} of ${results.length} went in. The rest are out of stock or no longer sold.`
        );
        router.push('/(screens)/Cart');
      } else {
        // Every line failed for a reason that is not a vendor conflict, so the
        // backend's own words are the most useful thing to show.
        Toast.error(
          'Could not repeat that order',
          errorMessage(rejected[0]?.reason, 'None of these items are available right now.')
        );
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
        ) : isError ? (
          /* `isError` was destructured and never read, so a failed request fell
             through to "No Previous Orders" — telling a customer who orders here
             every week that they never have, with no way to retry. */
          <View className="flex-1 items-center justify-center px-8">
            <Ionicons name="cloud-offline-outline" size={64} color={BRAND.primary} />
            <Text className={`font-sans-bold text-lg mt-4 text-center ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
              Couldn't load your last order
            </Text>
            <Text className={`text-sm text-center mt-2 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
              Check your connection and try again.
            </Text>
            <View className="mt-6 w-full">
              <DropButton title="Try again" onPress={() => refetch()} />
            </View>
          </View>
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

              {/* What that order cost.

                  Two lines and a total used to be drawn here — subtotal,
                  delivery fee, then `total_amount` — and they cannot add up:
                  the service fee, surcharges, deposit, settled balance and every
                  discount were all missing. On a seeded order it read
                  Subtotal 235, Delivery 101.80, Total 1.00, which is the same
                  unexplained difference the cart's `debt_settlement` line was
                  added to prevent. Every charge on the order is now its own
                  line, in the order `OrderDetail` renders them. */}
              <View>
                <Text className={`font-sans-bold text-lg mb-3 ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
                  What you paid last time
                </Text>
                <GlassCard darkTheme={darkTheme} className="p-4 gap-2">
                  {([
                    ['Subtotal', !isZeroMoney(lastOrder.product_subtotal)
                      ? lastOrder.product_subtotal
                      : sumMoney((lastOrder.order_item ?? []).map((i) => i.Subtotal)), false],
                    ['Delivery Fee', lastOrder.delivery_fee, false],
                    ['Service Fee', lastOrder.service_fee, false],
                    ['Surge Fee', lastOrder.surge_fee, false],
                    ['Staircase Surcharge', lastOrder.staircase_surcharge, false],
                    ['Heavy Load Surcharge', lastOrder.payload_surcharge, false],
                    ['Bottle Deposit', lastOrder.bottle_deposit, false],
                    ['Previous Balance Settled', lastOrder.debt_settlement, false],
                    ['Welcome Discount', lastOrder.welcome_discount, true],
                    ['Drop Cashback Applied', lastOrder.wallet_discount, true],
                    ['M-Pesa Payment Discount', lastOrder.mpesa_discount, true],
                  ] as const)
                    .filter(([, value]) => !isZeroMoney(value))
                    .map(([label, value, isDiscount]) => (
                      <View key={label} className="flex-row justify-between">
                        <Text className={`${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>{label}</Text>
                        <Text
                          className={isDiscount ? "font-sans-medium" : (darkTheme ? "text-on-surface" : "text-gray-800")}
                          style={isDiscount ? { color: BRAND.primary } : undefined}
                        >
                          {isDiscount ? '- ' : ''}{formatMoney(value)}
                        </Text>
                      </View>
                    ))}

                  {!isZeroMoney(lastOrder.rounding_adjustment) && (
                    <View className="flex-row justify-between">
                      <Text className={`${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Rounding</Text>
                      <Text className={`${darkTheme ? "text-on-surface" : "text-gray-800"}`}>
                        {isNegativeMoney(lastOrder.rounding_adjustment)
                          ? `- ${formatMoney(subtractMoney("0", lastOrder.rounding_adjustment))}`
                          : `+ ${formatMoney(lastOrder.rounding_adjustment)}`}
                      </Text>
                    </View>
                  )}

                  <View className={`flex-row justify-between pt-2 mt-2 border-t ${darkTheme ? "border-outline-variant/20" : "border-gray-100"}`}>
                    <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Total Paid</Text>
                    <Text className={`font-sans-bold text-lg text-primary`}>
                      {formatMoney(lastOrder.total_amount)}
                    </Text>
                  </View>
                </GlassCard>

                {/* Today's price is not last week's. Prices move, the delivery
                    fee is computed from where the customer is now, and the
                    discounts above were spent — the wallet credit especially.
                    Quoting the old total on the button promised a price the new
                    order will not be. */}
                <Text className={`text-xs mt-2 px-1 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
                  Today's total is worked out at checkout, so it may differ.
                </Text>
              </View>
            </ScrollView>

            {/* Bottom Actions.

                The bar is the last child of a flex column inside `SafeAreaView`,
                so it ended at `insets.bottom` — directly underneath the floating
                tab bar, which occupies the 72px above that. The only control on
                the screen was behind it. Padding the bar rather than lifting it
                keeps one continuous surface under the pill instead of a stripe
                of page background between the two. */}
            <View
              className={`px-5 pt-4 border-t ${darkTheme ? "bg-surface border-outline-variant/10" : "bg-white border-gray-100"}`}
              style={{ paddingBottom: tabBarClearance }}
            >
              <DropButton
                title={
                  isOrdering
                    ? "Adding to cart…"
                    : storeClosed
                      ? "Store is closed"
                      : "Add these items to cart"
                }
                onPress={handleRepeatOrder}
                disabled={isOrdering || storeClosed}
              />
            </View>
          </>
        )}
      </SafeAreaView>
    </>
  );
}
