import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useContext } from "react";
import { Text, View } from "react-native";

import PressableScale from "@/components/ui/PressableScale";
import { UIThemeContext } from "@/context/ThemeContext";

export interface LowStockProduct {
  id: string;
  name: string;
  stock: number;
  low_stock_threshold: number;
}

/**
 * What needs restocking, before a customer finds out instead.
 *
 * `stock` was captured on create and rendered on the products list, and nothing
 * else in the platform referenced it — no threshold, no badge, no dashboard
 * signal. A vendor's stock reaching zero silently means orders keep being
 * accepted against nothing and then cancelled, which restores the stock and
 * refunds the customer at the cost of the vendor's rating and the platform's
 * cut. Nothing warned anyone first.
 *
 * Renders nothing when there is nothing to say — a permanent "All good" card is
 * noise the vendor learns to skip past, which defeats the point of the card that
 * actually matters.
 */
export default function LowStockCard({ products }: { products?: LowStockProduct[] }) {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const router = useRouter();

  if (!products || products.length === 0) return null;

  const outOfStock = products.filter((p) => p.stock === 0);
  const running = products.filter((p) => p.stock > 0);

  return (
    <PressableScale onPress={() => router.push("/Products")}>
      <View
        className={`mt-6 mx-4 p-5 rounded-[24px] border ${
          darkTheme ? "bg-amber-500/10 border-amber-500/20" : "bg-amber-50 border-amber-200"
        }`}
      >
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center">
            <Ionicons name="alert-circle" size={22} color="#d97706" />
            <Text className={`font-bold text-lg ml-2 ${darkTheme ? "text-amber-100" : "text-amber-900"}`}>
              Needs restocking
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#d97706" />
        </View>

        {outOfStock.length > 0 && (
          <Text className={`text-sm font-semibold mb-2 ${darkTheme ? "text-red-300" : "text-red-700"}`}>
            {outOfStock.length === 1
              ? `${outOfStock[0].name} is out of stock — customers can't order it.`
              : `${outOfStock.length} products are out of stock — customers can't order them.`}
          </Text>
        )}

        {running.slice(0, 4).map((product) => (
          <View key={product.id} className="flex-row items-center justify-between py-1.5">
            <Text
              numberOfLines={1}
              className={`flex-1 text-sm mr-3 ${darkTheme ? "text-amber-100/90" : "text-amber-900"}`}
            >
              {product.name}
            </Text>
            <Text className={`text-sm font-bold ${darkTheme ? "text-amber-200" : "text-amber-800"}`}>
              {product.stock} left
            </Text>
          </View>
        ))}

        {running.length > 4 && (
          <Text className={`text-xs mt-2 ${darkTheme ? "text-amber-300/70" : "text-amber-700"}`}>
            and {running.length - 4} more
          </Text>
        )}
      </View>
    </PressableScale>
  );
}
