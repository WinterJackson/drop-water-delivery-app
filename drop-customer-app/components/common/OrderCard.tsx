import { UIThemeContext } from "@/context/ThemeContext";
import { useAddToCart, isVendorConflict, vendorConflictInfo } from "@/hooks/queries/useCart";
import { useCancelOrder, matchesOrderFilter, CANCELLABLE_ORDER_STATUSES } from "@/hooks/queries/useOrders";
import { useAuth } from "@clerk/clerk-expo";
import { format, parseISO } from 'date-fns';
import { useRouter } from "expo-router";
import React, { useContext, useState, useMemo } from "react";
import { Image, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";
import { errorMessage } from "@/API/errors";
import { PressableScale } from "@/components/ui/PressableScale";
import { Skeleton } from "@/components/ui/Skeleton";
import { Ionicons } from "@expo/vector-icons";
import { formatMoney, isNegativeMoney, isZeroMoney, multiplyMoney, subtractMoney, sumMoney } from "@/utils/money";

type Props = {
  order: any;
};

// FIX-RERENDER-08: Extract LiveETA into its own React.memo component.
const LiveETA = React.memo(({ createdAt, status, deliveryTime }: { createdAt: string, status: string, deliveryTime?: number }) => {
   const [timeLeft, setTimeLeft] = useState("");

   React.useEffect(() => {
      if (!createdAt) return;
      const slaMins = deliveryTime || 30; // Use API provided time or fallback to 30 mins
      const targetTime = new Date(createdAt).getTime() + slaMins * 60000;
      
      const updateTimer = () => {
         const now = new Date().getTime();
         const diff = targetTime - now;
         
         if (status === "picked_up") {
            setTimeLeft("5-10 mins");
            return;
         }

         if (diff <= 0) {
            setTimeLeft("Almost there!");
            return;
         }
         const mins = Math.floor(diff / 60000);
         const secs = Math.floor((diff % 60000) / 1000);
         setTimeLeft(`${mins}:${secs < 10 ? '0' : ''}${secs}`);
      };

      updateTimer();
      // FIX-RERENDER-09: For statuses that show a static string, don't run the interval.
      if (status === "picked_up") return;
      const interval = setInterval(updateTimer, 1000);
      return () => clearInterval(interval);
   }, [createdAt, status, deliveryTime]);

   return (
       <View className="flex-row items-center bg-sky-500/10 px-2 py-1 rounded-md border border-sky-500/20">
         <Text className="text-sky-600 dark:text-sky-400 font-sans-bold mr-1 text-[10px] uppercase tracking-wider">ETA</Text>
         <Text className="text-sky-600 dark:text-sky-400 font-sans-bold text-xs">{timeLeft}</Text>
       </View>
   )
});

// FIX-RERENDER-10: Wrap entire OrderCard in React.memo.
const OrderCard = React.memo(({ order }: Props) => {
  const router = useRouter();
  const { userId } = useAuth();
  const { mutate: addToCart } = useAddToCart();
  const { mutate: cancelOrderMutation, isPending: cancelLoading } = useCancelOrder();

  const {currentTheme} = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark"

  const [showItems, setShowItems] = useState(false);
  const [reorderLoading, setReorderLoading] = useState(false);

  // FIX-RERENDER-11: Compute action as a memoized value
  const action = useMemo(() => {
    // Cancellation first: `accepted` is both cancellable and in progress, and the
    // backend allows exactly pending/unassigned/accepted (a late cancel on
    // `accepted` carries a fee), so offering Cancel there is the useful action.
    if (CANCELLABLE_ORDER_STATUSES.includes(order.order_status)) return 'Cancel Order';
    // Anything else still in flight is trackable. This used to name statuses
    // inline and omitted `preparing` and `ready`, so an order being packed showed
    // no action at all — the customer could not open its tracking view from here.
    if (matchesOrderFilter(order.order_status, 'In Transit')) return 'Track Order';
    if (order.order_status === "delivered" && !order.is_rated) return 'Rate Delivery';
    if (order.order_status === "cancelled") return 'Re-Order';
    return '';
  }, [order.order_status, order.is_rated]);

  const getStatusStyle = (status: string) => {
      const s = status.toLowerCase();
      if (s === 'delivered' || s === 'completed') return { badge: 'bg-green-500/20 border-green-500/30', text: 'text-green-500' };
      if (s === 'picked_up') return { badge: 'bg-blue-500/20 border-blue-500/30', text: 'text-blue-500' };
      if (s === 'cancelled' || s === 'rejected') return { badge: 'bg-red-500/20 border-red-500/30', text: 'text-red-500' };
      if (s === 'mismatch_pending') return { badge: 'bg-amber-500/20 border-amber-500/30', text: 'text-amber-600 dark:text-amber-400' };
      return { badge: 'bg-yellow-500/20 border-yellow-500/30', text: 'text-yellow-600 dark:text-yellow-400' };
  };

  const cancelOrder = (orderId: string) => {
    const isAccepted = order.order_status === "accepted";
    const message = isAccepted 
      // No figure. The penalty is two settings rows — one before pickup, a
      // larger one after — and it is waived entirely while the customer still
      // has a free cancellation in the last 30 days. This app knows none of
      // those three things, and the sentence it used to state ("a KSH 50
      // cancellation penalty") was wrong on two of the four penalised statuses
      // and wrong again for anybody's first cancellation of the month. What
      // was actually charged comes back from the server below.
      ? "Are you sure you want to cancel this order? The vendor has already accepted it, so a cancellation fee may apply."
      : "Are you sure you want to cancel this order? This action cannot be undone.";
      
    Popup.show({
      title: "Cancel Order",
      message,
      cancelText: "No, Keep It",
      confirmText: "Yes, Cancel",
      isDestructive: true,
      onConfirm: () => {
        Popup.setLoading(true);
        cancelOrderMutation(orderId, {
          onSuccess: (result) => {
            Popup.hide();
            Toast.success(
              "Order cancelled",
              isZeroMoney(result?.penalty_charged)
                ? "Your order has been cancelled."
                : `A ${formatMoney(result.penalty_charged)} cancellation fee has been added to your balance and will be collected on your next order.`,
            );
          },
          onError: (error: Error) => {
            Popup.hide();
            Toast.error("Couldn't cancel order", errorMessage(error, "Please try again."));
          }
        });
      }
    });
  };

  const handleReorder = async (forceReplace = false) => {
    setReorderLoading(true);
    try {
      const items = order?.order_item || [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        await new Promise((resolve, reject) => {
          addToCart(
            { id: item.product_id, quantity: item.quantity, force_replace: i === 0 ? forceReplace : false },
            { onSuccess: resolve as any, onError: reject }
          );
        });
      }
      Toast.success("Cart Updated", "Items accurately re-added to your cart!");
      router.push("/(screens)/Cart");
    } catch (e: unknown) {
      // The vendor name is on `ApiError.detail`, not on the error itself — the
      // old read rendered "Your cart has items from undefined."
      if (isVendorConflict(e)) {
        const { existingVendor } = vendorConflictInfo(e);
        Popup.show({
          title: "Replace Cart?",
          message: `Your cart has items from ${existingVendor}. Re-ordering will replace your current cart.`,
          cancelText: "Cancel",
          confirmText: "Replace & Reorder",
          isDestructive: true,
          onConfirm: () => {
              Popup.hide();
              handleReorder(true);
          }
        });
      } else {
        if (__DEV__) console.error(e);
        // The backend names the actual blocker (out of stock, MOQ, vendor
        // closed); the fixed "may no longer be available" hid all of them.
        Toast.error("Couldn't re-order", errorMessage(e, "Some items may no longer be available."));
      }
    } finally {
      setReorderLoading(false);
    }
  };

  // FIX-RERENDER-12: Memoize date formatting
  const { dateStr, timeStr } = useMemo(() => {
    if (!order.created_at) return { dateStr: 'Unknown', timeStr: '' };
    const parsedDate = parseISO(order.created_at);
    return {
      dateStr: format(parsedDate, 'dd MMM yyyy'),
      timeStr: format(parsedDate, 'HH:mm'),
    };
  }, [order.created_at]);
    
  return (
    <PressableScale
      activeOpacity={0.95}
      onPress={() => router.push({ pathname: "/(screens)/OrderDetail", params: { orderId: order.id } })}
      className="mb-4"
    >
      <View className={`flex-1 ${darkTheme ? "bg-[#1C1C1E]" : "bg-white"} rounded-2xl p-4 shadow-sm border ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
        
        {/* HEADER: Date & Total */}
        <View className="flex-row justify-between items-start mb-3">
          <View className="flex-1 mr-2">
            <Text className={`text-[10px] uppercase tracking-wider font-sans-bold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Date</Text>
            <Text className={`text-sm font-sans-semibold mt-0.5 ${darkTheme ? "text-white" : "text-black"}`}>{dateStr}</Text>
          </View>
          <View className="items-end flex-shrink-0">
            <Text className={`text-[10px] uppercase tracking-wider font-sans-bold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Total Amt</Text>
            <Text className={`text-sm font-sans-bold mt-0.5 ${darkTheme ? "text-white" : "text-black"}`}>
              {/* `total_amount` is the figure the customer was actually charged,
                  frozen on the order at creation. This used to re-add the
                  components — a second pricing formula on the client, and one
                  that omitted the bottle deposit and any settled balance, so a
                  customer comparing this card with their M-Pesa message saw two
                  different numbers for the same order. */}
              {formatMoney(order.total_amount, "Ksh")}
            </Text>
          </View>
        </View>

        {/* STATUS & ITEMS ROW */}
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center flex-wrap gap-2 flex-1 mr-2">
            <View className={`px-2 py-1 rounded-md border ${getStatusStyle(order.order_status).badge}`}>
              <Text className={`text-[10px] font-sans-bold uppercase tracking-wider ${getStatusStyle(order.order_status).text}`}>
                {order.order_status.replace('_', ' ')}
              </Text>
            </View>
            {["accepted", "preparing", "ready", "picked_up", "mismatch_pending"].includes(order.order_status) && (
               <LiveETA createdAt={order.created_at} status={order.order_status} deliveryTime={order.delivery_time} />
            )}
          </View>
          <Text className={`text-xs font-sans-semibold flex-shrink-0 ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>
            {order?.order_item?.length || 0} item{(order?.order_item?.length !== 1) ? 's' : ''}
          </Text>
        </View>

        {/* VENDOR ROW (Only when details are hidden) */}
        {!showItems && (
          <View className={`p-3 rounded-xl flex-row justify-between items-center mb-3 ${darkTheme ? "bg-white/5" : "bg-gray-50"}`}>
            <View className="flex-1">
              <Text className={`text-[10px] uppercase tracking-wider font-sans-bold mb-0.5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Vendor Location</Text>
              <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-200" : "text-gray-800"}`} numberOfLines={1}>
                {order.vendor?.location_address || 'Location not available'}
              </Text>
            </View>
          </View>
        )}

        {/* PAYMENT & ACTIONS */}
        <View className="flex-row items-center justify-between">
          <View className="flex-1 mr-2">
            <Text className={`text-[10px] uppercase tracking-wider font-sans-bold mb-0.5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Payment Status</Text>
            <Text className={`text-xs font-sans-bold uppercase tracking-wider ${order.payment_status === 'paid' ? 'text-green-500' : 'text-amber-500'}`}>
              {order.payment_status}
            </Text>
          </View>
          
          {action != "" && (
            <PressableScale
              activeOpacity={0.7}
              disabled={action === "Cancel Order" && cancelLoading}
              onPress={() => {
                if(action === "Rate Delivery") router.push({ pathname: "/(screens)/RateOrder", params: { orderId: order.id, vendorId: order.vendor_id, riderId: order.deliverer_id } });
                else if(action === "Cancel Order") cancelOrder(order.id);
                else if(action === "Re-Order") handleReorder();
                else if(action === "Track Order") router.push({ pathname: "/(screens)/OrderDetail", params: { orderId: order.id } });
              }}
            >
              <View className={`py-1.5 px-3 rounded-full border ${darkTheme ? "border-white/20 bg-white/5" : "border-gray-200 bg-gray-50"}`}>
                {action === "Cancel Order" && cancelLoading ? (
                  <View className="flex-row items-center gap-2">
                     <Skeleton width={12} height={12} borderRadius={6} />
                    <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Wait...</Text>
                  </View>
                ) : (
                  <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-200" : "text-gray-800"}`}>{action}</Text>
                )}
              </View>
            </PressableScale>
          )}
        </View>

        {/* RE-ORDER BUTTON */}
        {(order.order_status === "delivered" || order.order_status === "completed" || order.order_status === "cancelled") && 
          <PressableScale 
            activeOpacity={0.6}
            disabled={reorderLoading}
            onPress={() => handleReorder()}
            className="mt-3"
          >
            <View className={`py-2.5 px-4 rounded-xl items-center flex-row justify-center gap-2 ${darkTheme ? "bg-sky-500/20" : "bg-sky-500/10"}`}>
              {reorderLoading ? (
                 <Skeleton width={14} height={14} borderRadius={7} />
              ) : (
                 <Text className="text-sky-500 font-sans-bold text-lg leading-none mt-[-2px]">↻</Text>
              )}
              <Text className={`font-sans-bold text-xs text-sky-500`}>
                {reorderLoading ? "Reordering..." : "Re-Order Items"}
              </Text>
            </View>
          </PressableScale>
        }

        {/* ORDER ITEMS LIST */}
        {showItems && (
          <View className={`mt-4 border-t pt-3 ${darkTheme ? "border-gray-800" : "border-gray-100"}`}>
            {order?.order_item?.map((item: any, index: any) => (
              <View key={index} className="flex-row py-2 gap-3 items-center">
                <View className="h-12 w-12 bg-gray-100 dark:bg-gray-800 rounded-lg overflow-hidden items-center justify-center">
                  {item.product?.image_url ? (
                    <Image source={{ uri: item.product.image_url }} className="w-full h-full" resizeMode="cover" />
                  ) : (
                    <Text>📦</Text>
                  )}
                </View>
                <View className="flex-1 justify-center py-0.5">
                  <Text className={`text-xs font-sans-bold mb-1 ${darkTheme ? "text-gray-100" : "text-gray-800"}`} numberOfLines={2}>
                    {item.product?.name || "Product"}
                  </Text>
                  <View className="flex-row justify-between items-end mt-1">
                    <Text className={`text-[10px] font-sans-semibold uppercase tracking-wider ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                      Qty: {item.quantity}  •  {formatMoney(item.price, "Ksh")}
                    </Text>
                    <Text className={`text-xs font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                      {formatMoney(multiplyMoney(item.price, item.quantity ?? 0), "Ksh")}
                    </Text>
                  </View>
                </View>
              </View>
            ))}

            <View className={`mt-2 pt-3 border-t ${darkTheme ? "border-gray-800" : "border-gray-100"} gap-1.5`}>
              <View className="flex-row justify-between items-center">
                <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Subtotal</Text>
                <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-200" : "text-gray-700"}`}>{formatMoney(!isZeroMoney(order.product_subtotal) ? order.product_subtotal : sumMoney((order.order_item ?? []).map((i: any) => multiplyMoney(i.price, i.quantity ?? 0))), "Ksh")}</Text>
              </View>
              <View className="flex-row justify-between items-center">
                <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Delivery Fee</Text>
                <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-200" : "text-gray-700"}`}>{formatMoney(order.delivery_fee, "Ksh")}</Text>
              </View>
              {!isZeroMoney(order.service_fee) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Service Fee</Text>
                  <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-200" : "text-gray-700"}`}>{formatMoney(order.service_fee, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.surge_fee) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Surge Pricing</Text>
                  <Text className={`text-xs font-sans-bold text-orange-500`}>{formatMoney(order.surge_fee, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.payload_surcharge) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Large Order Surcharge</Text>
                  <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-200" : "text-gray-700"}`}>{formatMoney(order.payload_surcharge, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.staircase_surcharge) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Staircase Surcharge</Text>
                  <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-200" : "text-gray-700"}`}>{formatMoney(order.staircase_surcharge, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.bottle_deposit) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Bottle Deposit</Text>
                  <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-200" : "text-gray-700"}`}>{formatMoney(order.bottle_deposit, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.debt_settlement) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Previous Balance</Text>
                  <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-200" : "text-gray-700"}`}>{formatMoney(order.debt_settlement, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.welcome_discount) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Welcome Offer</Text>
                  <Text className={`text-xs font-sans-bold text-green-500`}>-{formatMoney(order.welcome_discount, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.wallet_discount) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Wallet Applied</Text>
                  <Text className={`text-xs font-sans-bold text-green-500`}>-{formatMoney(order.wallet_discount, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.mpesa_discount) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>M-Pesa Discount</Text>
                  <Text className={`text-xs font-sans-bold text-green-500`}>-{formatMoney(order.mpesa_discount, "Ksh")}</Text>
                </View>
              )}
              {!isZeroMoney(order.rounding_adjustment) && (
                <View className="flex-row justify-between items-center">
                  <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Rounding</Text>
                  <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>
                    {isNegativeMoney(order.rounding_adjustment)
                      ? `- ${formatMoney(subtractMoney("0", order.rounding_adjustment), "Ksh")}`
                      : `+ ${formatMoney(order.rounding_adjustment, "Ksh")}`}
                  </Text>
                </View>
              )}
              <View className="flex-row justify-between items-center mt-1 pt-2 border-t border-gray-800/50 dark:border-gray-100/10">
                <Text className={`text-sm font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Total Amount</Text>
                <Text className={`text-sm font-sans-bold text-sky-500`}>
                  {/* The frozen figure the customer was charged, not a second
                      sum of the lines above — that one omitted the deposit and
                      any settled balance. */}
                  {formatMoney(order.total_amount, "Ksh")}
                </Text>
              </View>
            </View>
          </View>
        )}

        {/* TOGGLE DETAILS */}
        <PressableScale
          activeOpacity={0.8}
          onPress={() => setShowItems(!showItems)}
          className="mt-4"
        >
          <View className={`py-3 px-4 rounded-xl flex-row justify-center items-center gap-2 ${darkTheme ? "bg-white/5 border border-white/10" : "bg-gray-50 border border-gray-100"}`}>
             <Text className={`text-[11px] font-sans-bold uppercase tracking-wider ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>
               {showItems ? "Hide Order Details" : "See Order Details"}
             </Text>
             <Ionicons name={showItems ? "chevron-up" : "chevron-down"} size={14} color={darkTheme ? "#d1d5db" : "#4b5563"} />
          </View>
        </PressableScale>

      </View>
    </PressableScale>
  );
});

export default OrderCard;
