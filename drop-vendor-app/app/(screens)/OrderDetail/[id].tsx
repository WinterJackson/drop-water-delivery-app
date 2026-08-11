import { Skeleton } from "@/components/ui/Skeleton";
import { UIThemeContext } from "@/context/ThemeContext";
import { useOrderReview, useUpdateOrderStatus, useVendorOrder } from "@/hooks/queries/useVendorOrders";
import { isUnderReview, orderStatusStyle } from "@/constants/orderStatus";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useContext, useState } from "react";
import { ScrollView, StatusBar, View, Linking } from "react-native";
import { Text } from '@/components/ui/Text';
import { BottomSheetModal, BottomSheetBackdrop, BottomSheetView } from "@gorhom/bottom-sheet";
import { SafeAreaView } from "react-native-safe-area-context";
import PressableScale from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import { errorMessage } from "@/API/errors";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { useVendorRiders } from "@/hooks/queries/useVendorRiders";
import { Toast } from "@/lib/toast";
import { useQueryClient } from "@tanstack/react-query";
import { Image } from "expo-image";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { VendorOrderDetailSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { BRAND } from "@/constants/brandColors";
import { useOrderContacts, ContactInfo } from "@/hooks/queries/useOrderContacts";
import { PERMISSIONS, useCan } from "@/hooks/queries/useVendorProfile";
import { useWalletSummary } from "@/hooks/queries/useWallet";
import { useRef, useMemo, useCallback } from "react";
import { compareMoney, formatMoney, isZeroMoney, subtractMoney, sumMoney } from "@/utils/money";

export default function OrderDetail() {
  const { id } = useLocalSearchParams();
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  // Fetched by id, not searched for in a list the dashboard happened to load —
  // see `useVendorOrder`.
  const { data: order, isLoading } = useVendorOrder((id as string) || null);
  const { mutateAsync: updateStatusMutation } = useUpdateOrderStatus();
  const queryClient = useQueryClient();
  const { put } = useApiRequest();

  // Every write on this screen — accept, reject, prep, ready, cancel, assign —
  // is `require_permission("manage_orders")` on the server. `Orders.tsx` already
  // checked before firing; this screen, which is where the buttons actually
  // live, offered all six to a staff member holding only `manage_bottles` and
  // let each one fail. Hiding a control is a courtesy, not a control, but
  // offering one that always refuses is worse than not offering it.
  const canManageOrders = useCan(PERMISSIONS.manageOrders);

  // The float a cash order commits, and whether this store has it.
  //
  // `view_finances` governs the figures: a staff member trusted with orders is
  // not necessarily trusted with the store's balance, so they get the rule
  // without the numbers. `useWalletSummary` is only asked when they hold it —
  // requesting anyway would 403 on every open of an order.
  const canSeeFinances = useCan(PERMISSIONS.viewFinances);
  const { data: walletSummary } = useWalletSummary(canSeeFinances);

  // The roster comes from the shared hook, which already refetches and caches
  // it; this screen used to keep a third copy in `useState`.
  const { data: allRiders = [] } = useVendorRiders();
  const riders = useMemo(
    () => allRiders.filter((r: any) => r.status === "approved" && r.is_available),
    [allRiders]
  );

  const assignRiderSheetRef = useRef<BottomSheetModal>(null);
  const snapPoints = useMemo(() => ["50%", "75%"], []);

  const renderBackdrop = useCallback((props: any) => (
    <BottomSheetBackdrop {...props} disappearsOnIndex={-1} appearsOnIndex={0} opacity={0.5} />
  ), []);

  // Cross-party contact info (only fetched during active states)
  const { data: contactsData } = useOrderContacts(order?.id || null, order?.order_status || null);
  // Only fetched for the two states that can actually park an order.
  const { data: review } = useOrderReview(order?.id || null, order?.order_status || null);
  const contacts = contactsData?.contacts || [];
  const customerContact = contacts.find((c: ContactInfo) => c.role === "customer");
  const riderContact = contacts.find((c: ContactInfo) => c.role === "rider");

  const handleCall = (phone: string, role: string) => {
      if (!phone || phone === "N/A") {
          import("@/lib/toast").then(({ Toast }) => {
              Toast.error("Unavailable", `${role} phone number is not available.`);
          });
          return;
      }
      Linking.openURL(`tel:${phone}`);
  };

  const invalidateOrder = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["vendorOrder", id] });
    queryClient.invalidateQueries({ queryKey: ["vendorOrders"] });
    queryClient.invalidateQueries({ queryKey: ["vendorOrdersPaginated"] });
  }, [queryClient, id]);

  const handleAssignRider = async (riderId: string) => {
    assignRiderSheetRef.current?.dismiss();
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    try {
      await put(VendorApiRoutes.AssignRider(id as string).path, { deliverer_id: riderId });
      invalidateOrder();
      Toast.success("Rider assigned", "They have been notified.");
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      // `assign_order_rider` refuses an unapproved or unavailable rider with a
      // reason. The previous version checked `res.ok` and, when it was false,
      // did nothing at all — the sheet closed and the order stayed unassigned.
      Toast.error("Couldn't assign", errorMessage(e, "That rider couldn't take this order."));
    }
  };

  const updateStatus = async (status: string) => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    try {
      await updateStatusMutation({ orderId: id as string, status });
    } catch (e: unknown) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      // `errorMessage`, not `e.response?.data?.detail` — an `ApiError` has no
      // `.response`, so that path always fell through to the generic string.
      Toast.error("Update Failed", errorMessage(e, "Couldn't update that order."));
    }
  };

  const cancelOrder = async () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    try {
      await put(VendorApiRoutes.CancelOrder(id as string).path);
      invalidateOrder();
      Toast.success("Cancelled", "Order has been cancelled.");
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      Toast.error("Error", errorMessage(e, "Couldn't cancel that order."));
    }
  };

  // `platform_total` is the same figure `update_order_status` compares against,
  // and `available_for_withdrawal` is the same one `settlement_service` refuses
  // on — so this preview cannot disagree with the refusal. Deriving either
  // differently here would be worse than showing nothing.
  const floatRequired =
    order?.payment_method === "cash" && order?.platform_total != null
      ? order.platform_total
      : null;
  const availableFloat = walletSummary?.available_for_withdrawal ?? null;
  const isShortOnFloat =
    floatRequired !== null &&
    availableFloat !== null &&
    compareMoney(availableFloat, floatRequired) < 0;
  const shortfall = isShortOnFloat ? subtractMoney(floatRequired, availableFloat) : "0";

  if (isLoading) {
    return (
      <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
        <VendorOrderDetailSkeleton />
      </SafeAreaView>
    );
  }

  if (!order) {
    return (
      <SafeAreaView className={`flex-1 items-center justify-center ${darkTheme ? "bg-black" : ""}`}>
        <View className={`w-24 h-24 rounded-full items-center justify-center mb-6 shadow-sm border ${darkTheme ? "bg-slate-800 border-slate-700" : "bg-white border-slate-200"}`}>
            <Ionicons name="document-text-outline" size={48} color={BRAND.primary} />
        </View>
        <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Order not found</Text>
        <PressableScale onPress={() => router.back()} className="mt-6 bg-accentbg px-8 py-3.5 rounded-full shadow-sm">
          <Text className="text-white font-sans-bold">Go Back</Text>
        </PressableScale>
      </SafeAreaView>
    );
  }

  return (
    <>
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
              <View>
                  <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                      Order #{order.id?.substring(0, 8)}
                  </Text>
              </View>
          </View>
        </View>

        <ScrollView className="flex-1 px-5 pt-6" contentContainerStyle={{ paddingBottom: 120 }} showsVerticalScrollIndicator={false}>
          {/* Status indicator */}
          <View className="items-center mb-6">
            <View className={`px-5 py-2.5 rounded-full border border-transparent ${orderStatusStyle(order.order_status).pill}`}>
              <Text className={`text-sm font-sans-bold tracking-wider ${orderStatusStyle(order.order_status).text}`}>
                {orderStatusStyle(order.order_status).label}
              </Text>
            </View>
          </View>

          {/* Why this order stopped.

              `mismatch_pending` and `pending_review` are reachable in ordinary
              operation — a rider flags a damaged empty, or reports the customer
              understated their floor — and neither string appeared anywhere in
              this app. The vendor saw a blank pill over an order whose stock was
              committed and whose payment was pending, with nothing to read and
              nothing to do. */}
          {isUnderReview(order.order_status) && (
            <View className={`p-5 rounded-[24px] mb-5 border ${darkTheme ? "bg-amber-500/10 border-amber-500/20" : "bg-amber-50 border-amber-200"}`}>
              <View className="flex-row items-center mb-3">
                <Ionicons name="pause-circle-outline" size={22} color="#d97706" />
                <Text className={`font-sans-bold text-lg ml-2 ${darkTheme ? "text-amber-200" : "text-amber-900"}`}>
                  {orderStatusStyle(order.order_status).label}
                </Text>
              </View>
              <Text className={`text-sm leading-relaxed ${darkTheme ? "text-amber-100/80" : "text-amber-800"}`}>
                {orderStatusStyle(order.order_status).explanation}
              </Text>

              {order.order_status === "mismatch_pending" && review?.actual_floor_level != null && (
                <Text className={`text-sm mt-3 font-sans-semibold ${darkTheme ? "text-amber-200" : "text-amber-900"}`}>
                  Rider reports floor {review.actual_floor_level}.
                </Text>
              )}

              {review?.bottle_rejection && (
                <View className="mt-4">
                  <Text className={`text-xs font-sans-bold uppercase tracking-wider mb-1 ${darkTheme ? "text-amber-300/70" : "text-amber-700"}`}>
                    Rider&apos;s reason
                  </Text>
                  <Text className={`text-sm leading-relaxed ${darkTheme ? "text-amber-100" : "text-amber-900"}`}>
                    {review.bottle_rejection.reason_text}
                  </Text>

                  {review.bottle_rejection.photo_urls.length > 0 && (
                    <ScrollView
                      horizontal
                      showsHorizontalScrollIndicator={false}
                      className="mt-3"
                      contentContainerStyle={{ gap: 8 }}
                    >
                      {review.bottle_rejection.photo_urls.map((url: string) => (
                        <Image
                          key={url}
                          source={{ uri: url }}
                          style={{ width: 110, height: 110, borderRadius: 16 }}
                          contentFit="cover"
                        />
                      ))}
                    </ScrollView>
                  )}
                </View>
              )}

              <Text className={`text-xs mt-4 ${darkTheme ? "text-amber-300/60" : "text-amber-600"}`}>
                Nothing to do here — support resolves this and the order continues
                on its own. Your stock stays reserved in the meantime.
              </Text>
            </View>
          )}

          {/* Customer Details */}
          <View className={`p-5 rounded-[24px] mb-5 border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
            <Text className={`font-sans-bold text-lg mb-3 ${darkTheme ? "text-white" : "text-gray-900"}`}>Customer Details</Text>
            
            <View className="flex-row items-center mb-3">
              <View className="w-10 h-10 rounded-full items-center justify-center bg-accentbg/10 mr-3">
                 <Ionicons name="person" size={18} color="white" />
              </View>
              <View>
                <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Name</Text>
                <Text className={`text-base font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>{order.user?.username || order.user?.first_name || "Guest"}</Text>
              </View>
            </View>

            {order.user?.phone_number && (
               <View className="flex-row items-center mb-3">
                 <View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${darkTheme ? "bg-slate-800" : "bg-white"}`}>
                    <Ionicons name="call" size={18} color={BRAND.primary} />
                 </View>
                 <View>
                   <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Phone</Text>
                   <Text className={`text-base font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>{order.user.phone_number}</Text>
                 </View>
               </View>
            )}

            {order.delivery_location && (
              <View className="flex-row items-center">
                 <View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${darkTheme ? "bg-slate-800" : "bg-white"}`}>
                    <Ionicons name="location" size={18} color={BRAND.primary} />
                 </View>
                 <View className="flex-1">
                   <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Delivery Address</Text>
                   <Text className={`text-base font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>{order.delivery_location.street || "Not specified"}</Text>
                 </View>
               </View>
            )}
          </View>

          {/* ── Cross-Party Contact Cards ────────────────────────── */}
          {contacts.length > 0 && (
            <View className={`p-5 rounded-[24px] mb-5 border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
              <Text className={`font-sans-bold text-lg mb-4 ${darkTheme ? "text-white" : "text-gray-900"}`}>Contact</Text>
              <View className="gap-3">
                {customerContact && (
                  <PressableScale
                    onPress={() => handleCall(customerContact.phone, "Customer")}
                    className="flex-row items-center gap-3 p-3 rounded-xl"
                    style={{
                      backgroundColor: darkTheme ? 'rgba(2, 149, 247, 0.08)' : 'rgba(2, 149, 247, 0.06)',
                      borderWidth: 1,
                      borderColor: darkTheme ? 'rgba(2, 149, 247, 0.15)' : 'rgba(2, 149, 247, 0.12)',
                    }}
                  >
                    <View className="w-11 h-11 rounded-full items-center justify-center" style={{ backgroundColor: BRAND.primary + '20' }}>
                      <Ionicons name="person" size={20} color={BRAND.primary} />
                    </View>
                    <View className="flex-1">
                      <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-slate-900"}`}>{customerContact.name}</Text>
                      <Text className={`text-xs ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Tap to call customer</Text>
                    </View>
                    <View className="w-10 h-10 rounded-full items-center justify-center" style={{ backgroundColor: BRAND.primary }}>
                      <Ionicons name="call" size={18} color="#fff" />
                    </View>
                  </PressableScale>
                )}
                {riderContact && (
                  <PressableScale
                    onPress={() => handleCall(riderContact.phone, "Rider")}
                    className="flex-row items-center gap-3 p-3 rounded-xl"
                    style={{
                      backgroundColor: darkTheme ? 'rgba(14, 165, 233, 0.08)' : 'rgba(14, 165, 233, 0.06)',
                      borderWidth: 1,
                      borderColor: darkTheme ? 'rgba(14, 165, 233, 0.15)' : 'rgba(14, 165, 233, 0.12)',
                    }}
                  >
                    <View className="w-11 h-11 rounded-full items-center justify-center" style={{ backgroundColor: 'rgba(14, 165, 233, 0.2)' }}>
                      <Ionicons name="bicycle" size={20} color="#0ea5e9" />
                    </View>
                    <View className="flex-1">
                      <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-slate-900"}`}>{riderContact.name}</Text>
                      <Text className={`text-xs ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                        {riderContact.vehicle_details ? `${riderContact.vehicle_details} • ` : ""}Tap to call rider
                      </Text>
                    </View>
                    <View className="w-10 h-10 rounded-full items-center justify-center" style={{ backgroundColor: '#0ea5e9' }}>
                      <Ionicons name="call" size={18} color="#fff" />
                    </View>
                  </PressableScale>
                )}
              </View>
            </View>
          )}

          {/* Order Items */}
          <View className={`p-5 rounded-[24px] mb-5 border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
            <Text className={`font-sans-bold text-lg mb-4 ${darkTheme ? "text-white" : "text-gray-900"}`}>Order Items</Text>
            {order.order_item?.map((item: any, index: number) => (
              <View key={index} className={`flex-row justify-between items-center py-2 ${index !== order.order_item.length - 1 ? (darkTheme ? "border-b border-slate-800" : "border-b border-slate-100") : ""}`}>
                <View className="flex-row items-center">
                  <View className={`w-8 h-8 rounded-lg items-center justify-center mr-3 ${darkTheme ? "bg-slate-800" : "bg-white"}`}>
                     <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>{item.quantity}x</Text>
                  </View>
                  <Text className={`text-base font-sans-semibold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
                    {item.product?.name || "Product"}
                  </Text>
                </View>
                <Text className={`font-sans-extrabold ${darkTheme ? "text-white" : "text-gray-900"}`}>
                  KSH {item.price * item.quantity}
                </Text>
              </View>
            ))}
          </View>

          {/* Delivery Type Info */}
          {order.delivery_type && (
            <View className={`p-5 rounded-[24px] mb-5 border shadow-sm ${darkTheme ? "bg-amber-900/10 border-amber-500/20" : "bg-amber-50 border-amber-200"}`} style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
              <View className="flex-row items-center mb-3">
                 <Ionicons name="water-outline" size={20} color={BRAND.primary} style={{ marginRight: 8 }} />
                 <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-gray-900"}`}>Delivery Flow</Text>
              </View>
              
              <View className="flex-row justify-between mb-2">
                <Text className={`font-sans-semibold ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Type</Text>
                <View className={`px-3 py-1 rounded-full flex-row items-center gap-1.5 ${order.delivery_type === 'quick_swap' ? 'bg-blue-500/20' : 'bg-green-500/20'}`}>
                  <Ionicons 
                    name={order.delivery_type === 'quick_swap' ? 'flash' : 'lock-closed'} 
                    size={12} 
                    color={order.delivery_type === 'quick_swap' ? '#3b82f6' : 'green-500'} 
                  />
                  <Text className={`font-sans-bold text-xs ${order.delivery_type === 'quick_swap' ? 'text-blue-500' : 'text-green-500'}`}>
                    {order.delivery_type === 'quick_swap' ? 'Quick Swap' : 'Keep My Bottle'}
                  </Text>
                </View>
              </View>
              <View className="flex-row justify-between mb-2">
                <Text className={`font-sans-semibold ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Instruction</Text>
                <Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-gray-900"}`}>
                  {order.delivery_type === 'quick_swap' ? 'Swap empties for full' : 'Deliver new bottle(s)'}
                </Text>
              </View>
              {order.is_welcome_offer && (
                <View className="mt-3 p-3 bg-green-500/10 rounded-[16px] border border-green-500/20 flex-row items-center gap-2">
                  <Ionicons name="gift" size={20} color="green-500" />
                  <Text className="text-green-500 text-xs font-sans-bold flex-1 leading-5">
                    Welcome Offer (30% off) applied to this order.
                  </Text>
                </View>
              )}
            </View>
          )}

          {/* Financials */}
          <View className={`p-5 rounded-[24px] mb-5 border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
            <Text className={`font-sans-bold text-lg mb-3 ${darkTheme ? "text-white" : "text-gray-900"}`}>Payment Summary</Text>
            <View className="flex-row justify-between mb-3">
              <Text className={`font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Subtotal</Text>
              <Text className={`font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>{formatMoney(order.product_subtotal)}</Text>
            </View>
            <View className="flex-row justify-between mb-3">
              <Text className={`font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Delivery Fee</Text>
              <Text className={`font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>{formatMoney(order.delivery_fee)}</Text>
            </View>
            {!isZeroMoney(order.service_fee) && (
              <View className="flex-row justify-between mb-3">
                <Text className={`font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Service Fee</Text>
                <Text className={`font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>{formatMoney(order.service_fee)}</Text>
              </View>
            )}
            {!isZeroMoney(order.surge_fee) && (
              <View className="flex-row justify-between mb-3">
                <Text className={`font-sans-medium text-orange-500`}>Surge Fee</Text>
                <Text className={`font-sans-bold text-orange-500`}>{formatMoney(order.surge_fee)}</Text>
              </View>
            )}
            {Number(order.payload_surcharge || 0) > 0 && (
              <View className="flex-row justify-between mb-3">
                <Text className={`font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Payload Surcharge</Text>
                <Text className={`font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>{formatMoney(order.payload_surcharge)}</Text>
              </View>
            )}
            {Number(order.staircase_surcharge || 0) > 0 && (
              <View className="flex-row justify-between mb-3">
                <Text className={`font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Staircase Surcharge</Text>
                <Text className={`font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>{formatMoney(order.staircase_surcharge)}</Text>
              </View>
            )}
            {!isZeroMoney(order.welcome_discount) && (
              <View className="flex-row justify-between mb-3">
                <Text className={`font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Welcome Discount</Text>
                <Text className="font-sans-bold text-green-500">-{formatMoney(order.welcome_discount)}</Text>
              </View>
            )}
            {!isZeroMoney(order.wallet_discount) && (
              <View className="flex-row justify-between mb-3">
                <Text className={`font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Wallet Applied</Text>
                <Text className="font-sans-bold text-green-500">-{formatMoney(order.wallet_discount)}</Text>
              </View>
            )}
            <View className={`h-[1px] my-3 ${darkTheme ? "bg-slate-800" : "bg-slate-100"}`} />
            <View className="flex-row justify-between items-center">
              <Text className={`font-sans-extrabold text-xl ${darkTheme ? "text-white" : "text-gray-900"}`}>Total</Text>
              {/* The order's own frozen total, not a sum of the lines above.
                  Re-adding them here was a second pricing formula, missing the
                  deposit and any settled balance — so the store's screen and
                  the customer's disagreed about one order. */}
              <Text className={`font-sans-extrabold text-2xl text-accentbg`}>{formatMoney(order.total_amount)}</Text>
            </View>
          </View>

          {/* Rider Info if assigned */}
          {order.rider && (
            <View className={`p-5 rounded-[24px] mb-10 border shadow-sm ${darkTheme ? "bg-sky-500/10 border-sky-500/20" : "bg-sky-500/5 border-sky-500/10"}`} style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
              <View className="flex-row items-center mb-4">
                 <Ionicons name="bicycle" size={24} color={BRAND.primary} style={{ marginRight: 8 }} />
                 <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-gray-900"}`}>Assigned Rider</Text>
              </View>
              <View className="flex-row items-center mb-2">
                 <View className="w-10 h-10 rounded-full items-center justify-center bg-sky-500/20 mr-3">
                    <Ionicons name="person" size={18} color={BRAND.primary} />
                 </View>
                 <View>
                   <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Name</Text>
                   <Text className={`text-base font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>{order.rider.username || "Assigned Rider"}</Text>
                 </View>
               </View>
               <View className="flex-row items-center">
                 <View className="w-10 h-10 rounded-full items-center justify-center bg-sky-500/20 mr-3">
                    <Ionicons name="car" size={18} color={BRAND.primary} />
                 </View>
                 <View>
                   <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Vehicle</Text>
                   <Text className={`text-base font-sans-bold uppercase ${darkTheme ? "text-white" : "text-slate-900"}`}>{order.rider.vehicle_type || "N/A"}</Text>
                 </View>
               </View>
            </View>
          )}

        </ScrollView>

        {/* Action Buttons */}
        <View className={`px-5 pb-8 pt-4 border-t ${darkTheme ? "bg-black border-slate-800" : "bg-white border-gray-100"}`}>
          {order.order_status === "pending" && order.payment_method === "cash" && (
            <View
              className={`p-4 mb-4 rounded-xl border ${
                isShortOnFloat
                  ? darkTheme ? "bg-red-900/20 border-red-500/30" : "bg-red-50 border-red-200"
                  : darkTheme ? "bg-amber-900/20 border-amber-500/30" : "bg-amber-50 border-amber-200"
              }`}
            >
               <View className="flex-row items-center mb-2">
                 <Ionicons
                   name={isShortOnFloat ? "alert-circle" : "warning"}
                   size={20}
                   color={isShortOnFloat ? "#ef4444" : "#f59e0b"}
                   style={{ marginRight: 8 }}
                 />
                 <Text className={`font-sans-bold text-sm ${isShortOnFloat ? (darkTheme ? "text-red-400" : "text-red-700") : (darkTheme ? "text-amber-500" : "text-amber-700")}`}>
                   {isShortOnFloat ? "Not enough float to accept this" : "Cash Float Required"}
                 </Text>
               </View>

               {/* The backend refuses with the exact shortfall — but only after
                   the vendor has already tapped Accept, in front of a waiting
                   customer. `platform_total` is on the order and the available
                   figure is the same one `settlement_service` refuses on, so the
                   answer can be given before the tap rather than after it. */}
               {floatRequired !== null && canSeeFinances ? (
                 <>
                   <View className="flex-row justify-between mb-1">
                     <Text className={`text-xs ${darkTheme ? "text-amber-200/70" : "text-amber-700/80"}`}>
                       Commission on this order
                     </Text>
                     <Text className={`text-xs font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                       {formatMoney(floatRequired)}
                     </Text>
                   </View>
                   <View className="flex-row justify-between">
                     <Text className={`text-xs ${darkTheme ? "text-amber-200/70" : "text-amber-700/80"}`}>
                       Your available float
                     </Text>
                     <Text className={`text-xs font-sans-bold ${isShortOnFloat ? "text-red-500" : "text-green-500"}`}>
                       {formatMoney(availableFloat)}
                     </Text>
                   </View>

                   {isShortOnFloat ? (
                     <PressableScale
                       onPress={() => router.push("/(screens)/WalletScreen" as any)}
                       className="mt-3 py-2.5 rounded-xl items-center"
                       style={{ backgroundColor: BRAND.primary }}
                     >
                       <Text className="text-white font-sans-bold text-xs">
                         Top up {formatMoney(shortfall)} to accept
                       </Text>
                     </PressableScale>
                   ) : null}
                 </>
               ) : (
                 <Text className={`text-xs ${darkTheme ? "text-amber-200/70" : "text-amber-700/80"}`}>
                   This is a Cash order. The store must have enough float to cover
                   the platform&apos;s commission before it can be accepted.
                 </Text>
               )}
            </View>
          )}

          {!canManageOrders && (
            <View className={`p-4 mb-4 rounded-xl border flex-row items-center gap-3 ${darkTheme ? "bg-slate-800/60 border-slate-700" : "bg-slate-50 border-slate-200"}`}>
              <Ionicons name="lock-closed-outline" size={20} color={darkTheme ? "#94a3b8" : "#64748b"} />
              <Text className={`flex-1 text-xs ${darkTheme ? "text-slate-300" : "text-slate-600"}`}>
                You can view this order but not act on it. Ask the store owner to
                enable &ldquo;Accept and update orders&rdquo; for you.
              </Text>
            </View>
          )}

          {canManageOrders && order.order_status === "pending" && (
            <View className="flex-row gap-3">
               <PressableScale
                onPress={() => updateStatus("rejected")}
                className="flex-1 bg-red-500/10 border border-red-500/20 py-4 rounded-[16px] items-center shadow-sm"
              >
                <Text className="text-red-500 font-sans-bold text-lg">Reject</Text>
              </PressableScale>
              <PressableScale
                onPress={() => updateStatus("accepted")}
                className="flex-[1.5] bg-accentbg py-4 rounded-[16px] items-center shadow-sm"
              >
                <Text className="text-white font-sans-bold text-lg">Accept Order</Text>
              </PressableScale>
            </View>
          )}

          {canManageOrders && order.order_status === "accepted" && (
            <View className="flex-row gap-3">
               {!order.rider && (
                <PressableScale
                  onPress={() => assignRiderSheetRef.current?.present()}
                  className={`flex-1 py-4 rounded-[16px] items-center shadow-sm border ${darkTheme ? "bg-slate-800 border-slate-700" : "bg-white border-slate-200"}`}
                >
                  <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-slate-900"}`}>Assign Fleet</Text>
                </PressableScale>
              )}
              <PressableScale
                onPress={() => updateStatus("preparing")}
                className="flex-[1.5] bg-purple-500 py-4 rounded-[16px] items-center shadow-sm"
              >
                <Text className="text-white font-sans-bold text-lg">Start Prep</Text>
              </PressableScale>
            </View>
          )}

          {canManageOrders && order.order_status === "preparing" && (
            <PressableScale
              onPress={() => updateStatus("ready")}
              className="w-full bg-green-500 py-4 rounded-[16px] items-center shadow-sm"
            >
              <Text className="text-white font-sans-bold text-lg">Mark as Ready</Text>
            </PressableScale>
          )}

          {canManageOrders && (order.order_status === "accepted" || order.order_status === "preparing") && (
             <PressableScale
                onPress={() => {
                  import("@/lib/popup").then(({ Popup }) => {
                     Popup.show({
                       title: "Cancel Order",
                       message: "Are you sure you want to cancel this order? This cannot be undone.",
                       cancelText: "No, Go Back",
                       confirmText: "Yes, Cancel Order",
                       isDestructive: true,
                       onConfirm: () => {
                         import("@/lib/popup").then(({ Popup }) => Popup.hide());
                         cancelOrder();
                       }
                     });
                  });
                }}
                className={`mt-4 py-4 rounded-[16px] items-center shadow-sm border ${darkTheme ? "bg-red-500/10 border-red-500/20" : "bg-red-50 border-red-200"}`}
              >
                <Text className="text-red-500 font-sans-bold text-lg">Cancel Order</Text>
              </PressableScale>
          )}

          {(order.order_status === "ready" || order.order_status === "picked_up" || order.order_status === "delivered") && (
            <>
              {order.order_status === "delivered" ? (
                <View className={`w-full py-4 rounded-[16px] items-center border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-slate-100"}`}>
                  <Text className={`font-sans-bold text-lg ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                    Order Delivered
                  </Text>
                </View>
              ) : (
                <PressableScale
                  onPress={() => router.push(`/(screens)/Map/${order.id}` as any)}
                  className="w-full bg-accentbg py-4 rounded-[16px] items-center shadow-sm"
                >
                  <Text className="text-white font-sans-bold text-lg">Track Delivery</Text>
                </PressableScale>
              )}
            </>
          )}
        </View>

      </SafeAreaView>

      {/* Fleet Rider Assignment Sheet */}
      <BottomSheetModal
        ref={assignRiderSheetRef}
        index={0}
        snapPoints={snapPoints}
        backdropComponent={renderBackdrop}
        backgroundStyle={{ backgroundColor: darkTheme ? "#1E293B" : "#FFFFFF" }}
        handleIndicatorStyle={{ backgroundColor: darkTheme ? "#475569" : "#CBD5E1", width: 40 }}
      >
        <BottomSheetView style={{ flex: 1, padding: 24 }}>
          <View className="flex-row justify-between items-center mb-6">
            <Text className={`text-2xl font-heading-semibold ${darkTheme ? "text-white" : "text-slate-900"}`}>Assign Fleet Rider</Text>
            <PressableScale accessibilityLabel="Close the rider list" onPress={() => { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); assignRiderSheetRef.current?.dismiss(); }} className={`p-2 rounded-full ${darkTheme ? "bg-slate-800" : "bg-white"}`}>
                <Ionicons name="close" size={20} color={BRAND.primary} />
            </PressableScale>
          </View>

          <ScrollView style={{ flex: 1 }} showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 40 }}>
            {riders.length === 0 ? (
              <View className="items-center py-10">
                  <Ionicons name="warning-outline" size={48} color={BRAND.primary} className="mb-4" />
                  <Text className={`text-center font-sans-semibold text-lg ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>No available riders</Text>
                  <Text className={`text-center mt-2 px-10 ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Ensure riders are 'Approved' and marked as 'Available' in your Fleet Management.</Text>
              </View>
            ) : riders.map((r: any) => (
              <PressableScale
                key={r.deliverer_id}
                onPress={() => handleAssignRider(r.deliverer_id)}
                className={`p-4 rounded-[20px] mb-3 border flex-row justify-between items-center shadow-sm ${darkTheme ? "border-slate-800 bg-[#0F172A]" : "border-slate-100 bg-white"}`}>
                <View className="flex-row items-center">
                  <View className="w-12 h-12 rounded-full bg-accentbg/10 mr-4 items-center justify-center border border-accentbg/20">
                    {r.profile_pic ? (
                      <Image source={{ uri: r.profile_pic }} className="w-full h-full rounded-full" />
                    ) : (
                      <Ionicons name="person" size={20} color={BRAND.primary} />
                    )}
                  </View>
                  <View>
                    <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-slate-900"}`}>{r.name}</Text>
                    <Text className={`text-xs mt-1 font-sans-bold tracking-widest uppercase ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>{r.vehicle_type} • {r.plate_number || "No Plate"}</Text>
                  </View>
                </View>
                <View className="bg-accentbg/10 px-4 py-2.5 rounded-[12px] border border-accentbg/20">
                  <Text className="text-accentbg font-sans-bold">Assign</Text>
                </View>
              </PressableScale>
            ))}
          </ScrollView>
        </BottomSheetView>
      </BottomSheetModal>

    </>
  );
}
