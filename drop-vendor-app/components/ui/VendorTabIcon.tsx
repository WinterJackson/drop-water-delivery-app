import React from "react";
import { View } from "react-native";
import { Text } from '@/components/ui/Text';
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "@/constants/brandColors";

type TabName = "home" | "products" | "orders" | "profile";

const TAB_ICONS: Record<TabName, { active: keyof typeof Ionicons.glyphMap; inactive: keyof typeof Ionicons.glyphMap }> = {
  home: { active: "grid", inactive: "grid-outline" },
  products: { active: "cube", inactive: "cube-outline" },
  orders: { active: "receipt", inactive: "receipt-outline" },
  profile: { active: "person", inactive: "person-outline" },
};

interface VendorTabIconProps {
  name: TabName;
  active: boolean;
  count?: number;
}

export default function VendorTabIcon({ name, active, count }: VendorTabIconProps) {
  const iconSet = TAB_ICONS[name] || TAB_ICONS.home;
  const iconName = active ? iconSet.active : iconSet.inactive;

  return (
    <View className="items-center justify-center relative">
      <Ionicons
        name={iconName}
        size={24}
        color={active ? "#ffffff" : "#94a3b8"}
      />
      {/* Badge for pending order count */}
      {count != null && count > 0 && (
        <View className="absolute -top-2 -right-3 bg-red-500 rounded-full min-w-[20px] h-[20px] items-center justify-center px-1">
          <Text className="text-white text-[10px] font-sans-extrabold">{count > 99 ? "99+" : count}</Text>
        </View>
      )}
    </View>
  );
}
