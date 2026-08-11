import React, { useContext } from "react";
import { StatusBar, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import PressableScale from "@/components/ui/PressableScale";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import {
  PERMISSIONS,
  useCan,
  useVendorProfile,
  type PermissionKey,
} from "@/hooks/queries/useVendorProfile";

/** The sentence the owner would need to hear to fix it, per capability. */
const CAPABILITY_LABEL: Record<PermissionKey, string> = {
  [PERMISSIONS.manageOrders]: "Accept and update orders",
  [PERMISSIONS.manageProducts]: "Add and edit products",
  [PERMISSIONS.manageBottles]: "Receive empty bottles",
  [PERMISSIONS.viewFinances]: "See the store's money",
};

/**
 * Wraps a whole screen that one capability governs.
 *
 * Screens whose *entire* purpose is a single gated action — the product form is
 * the case this exists for — should refuse at the door rather than render a
 * complete form that fails at submit. Filling in a name, a price, a stock count
 * and an image, and only then being told you were never allowed to, is the
 * worst version of this. Screens with a *mix* of permitted and gated controls
 * (the order detail) keep rendering and gate the individual buttons instead.
 *
 * The server refuses either way — `require_permission(...)` is the control, this
 * is the courtesy — but the courtesy is what stops the vendor's staff wasting a
 * minute at the counter with a customer waiting.
 *
 * Renders nothing while the profile is loading, so a permitted caller never sees
 * a refusal flash past on a cold start.
 */
export function CapabilityGate({
  permission,
  title,
  children,
}: {
  permission: PermissionKey;
  /** Shown in the header of the refusal, so the screen is still identifiable. */
  title: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const { data: profile, isLoading } = useVendorProfile();
  const allowed = useCan(permission);

  // `permissions` absent entirely means the profile has not arrived yet. Do not
  // refuse on missing data — that is the KYC gate's failure mode inverted, and
  // here it would lock out an owner on a slow connection.
  if (isLoading || !profile?.permissions) return <>{children}</>;
  if (allowed) return <>{children}</>;

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar
        translucent
        backgroundColor={darkTheme ? "black" : "white"}
        barStyle={darkTheme ? "light-content" : "dark-content"}
      />

      <View className="flex-row items-center px-4 py-3">
        <PressableScale accessibilityLabel="Go back" onPress={() => router.back()} className="mr-4">
          <Ionicons
            name="chevron-back"
            size={26}
            color={darkTheme ? "#fff" : "#0f172a"}
          />
        </PressableScale>
        <Text
          className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}
        >
          {title}
        </Text>
      </View>

      <View className="flex-1 items-center justify-center px-8">
        <View
          className={`w-20 h-20 rounded-full items-center justify-center mb-5 ${darkTheme ? "bg-slate-800" : "bg-slate-100"}`}
        >
          <Ionicons name="lock-closed-outline" size={36} color={BRAND.primary} />
        </View>
        <Text
          className={`text-lg font-sans-bold text-center ${darkTheme ? "text-white" : "text-slate-900"}`}
        >
          You don&apos;t have access to this
        </Text>
        <Text
          className={`text-center mt-2 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}
        >
          Ask the store owner to turn on &ldquo;
          {CAPABILITY_LABEL[permission]}&rdquo; for you in Manage Staff.
        </Text>

        <PressableScale
          onPress={() => router.back()}
          className="mt-8 bg-accentbg px-8 py-3.5 rounded-full"
        >
          <Text className="text-white font-sans-bold">Go back</Text>
        </PressableScale>
      </View>
    </SafeAreaView>
  );
}

export default CapabilityGate;
