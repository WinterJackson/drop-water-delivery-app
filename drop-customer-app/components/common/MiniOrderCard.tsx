import { BRAND } from '@/constants/brandColors';
import { UIThemeContext } from '@/context/ThemeContext';
import { useOrderContacts, type ContactInfo } from '@/hooks/queries/useOrderContacts';
import { Toast } from '@/lib/toast';
import type { Order } from '@/types/models';
import { formatMoney } from '@/utils/money';
import Ionicons from "@expo/vector-icons/Ionicons";
import React, { useContext } from 'react';
import { Linking, View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { PressableScale } from "@/components/ui/PressableScale";

type Props = {
  /** The order being tracked. Without one there is nothing to summarise. */
  data?: Order | null;
};

/**
 * The floating summary over the tracking map.
 *
 * This component used to render a mock-up — order `#57v8V8V585J390-248HVQ08`,
 * "2:00pm Feb 25, 2024", "3 items", "Ksh 300", a rider called John Doe — and it
 * was mounted on the live tracking screen, beside a real order, with `data`
 * declared as a prop and read nowhere. So a customer watching their delivery
 * saw a fabricated order described in confident detail, and the two buttons
 * offering to call and message the rider had no `onPress` at all.
 *
 * Every figure here now comes from the order or from `useOrderContacts`, which
 * is the only source of a counterparty's number and is withheld by the server
 * outside active fulfilment.
 */
const MiniOrderCard = ({ data }: Props) => {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const { data: contactsData } = useOrderContacts(
    data?.id ?? null,
    data?.order_status ?? null,
  );
  const rider = (contactsData?.contacts ?? []).find(
    (c: ContactInfo) => c.role === "rider",
  );

  if (!data) return null;

  const placedAt = data.created_at
    ? new Date(data.created_at).toLocaleString(undefined, {
        hour: "numeric",
        minute: "2-digit",
        day: "numeric",
        month: "short",
      })
    : "—";

  const lines = data.order_item?.length ?? 0;
  const units = (data.order_item ?? []).reduce(
    (total, item: any) => total + (Number(item?.quantity) || 0),
    0,
  );
  // Units when we have them, lines otherwise — "3 items" should mean three
  // bottles, not three rows that happen to add up to eleven.
  const itemCount = units || lines;

  const reach = (scheme: "tel" | "sms") => {
    if (!rider?.phone || rider.phone === "N/A") {
      Toast.error("Unavailable", "The rider's number isn't available yet.");
      return;
    }
    Linking.openURL(`${scheme}:${rider.phone}`);
  };

  return (
    <View
      className={`${darkTheme ? "bg-black" : "bg-white"} self-end w-full gap-2 p-4 rounded-3xl shadow-xl border-gray-50 shadow-black/40`}
    >
      <View className=' flex-row justify-between items-start'>
        <View className="flex-1 mr-3">
          <Text className={`${darkTheme ? "text-white" : "text-black"}`}>Order Id</Text>
          <Text
            numberOfLines={1}
            className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}
          >
            #{data.id?.slice(0, 8).toUpperCase()}
          </Text>
        </View>
        <View className={`px-6 py-1 ${darkTheme ? "bg-accentbg/20" : "bg-black"} rounded-full`}>
          <Text className={`font-sans-bold text-white`}>In Transit</Text>
        </View>
      </View>
      <View className={`flex-row gap-2 pb-3 border-b ${darkTheme ? "border-gray-600" : "border-gray-200"}`}>
        <View className={`gap-2 flex-1`}>
          <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Placed At</Text>
          <Text className={`${darkTheme ? "text-gray-400" : "text-gray-600"}`}>{placedAt}</Text>
        </View>
        <View className={`gap-2 flex-1`}>
          <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Items</Text>
          <Text className={`${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
            {itemCount} {itemCount === 1 ? "item" : "items"}
          </Text>
        </View>
        <View className={`gap-2 flex-1`}>
          <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Amount</Text>
          {/* `total_amount` verbatim — never the sum of the lines, which omits
              the bottle deposit and any settled balance. */}
          <Text className={`${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
            {formatMoney(data.total_amount)}
          </Text>
        </View>
      </View>
      <View className={`flex-row w-full py-2 items-center justify-between`}>
        <View className={`flex-row gap-2 items-center flex-1 mr-3`}>
          <Ionicons name="person" size={24} color={BRAND.primary} />
          <View className={`gap-1 flex-1`}>
            <Text className={`${darkTheme ? "text-white" : "text-black"}`}>Delivery Man</Text>
            <Text
              numberOfLines={1}
              className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}
            >
              {rider?.name ?? "Being assigned…"}
            </Text>
          </View>
        </View>
        {rider && (
          <View className={`flex-row gap-3`}>
            <PressableScale
              activeOpacity={0.7}
              onPress={() => reach("tel")}
              accessibilityRole="button"
              accessibilityLabel={`Call ${rider.name}`}
            >
              <View className="w-12 h-12 shadow-lg shadow-black bg-green-500 rounded-2xl items-center justify-center">
                <Ionicons name="call" size={24} color={darkTheme ? "black" : "white"} />
              </View>
            </PressableScale>
            <PressableScale
              activeOpacity={0.7}
              onPress={() => reach("sms")}
              accessibilityRole="button"
              accessibilityLabel={`Send ${rider.name} a message`}
            >
              <View className={`w-12 h-12 shadow-lg shadow-black bg-blue-500 rounded-2xl items-center justify-center`}>
                <Ionicons name="chatbubble" size={24} color={darkTheme ? "black" : "white"} />
              </View>
            </PressableScale>
          </View>
        )}
      </View>
    </View>
  )
}

export default MiniOrderCard
