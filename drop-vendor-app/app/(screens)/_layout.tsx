import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { useVendorOrders } from "@/hooks/queries/useVendorOrders";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useAuth } from "@clerk/clerk-expo";
import { Redirect, Stack, usePathname, useRouter } from "expo-router";
import { useContext } from "react";
import { View, Dimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { PressableScale } from "@/components/ui/PressableScale";
import VendorTabIcon from "@/components/ui/VendorTabIcon";
import * as Haptics from "expo-haptics";
import OfflineBanner from "@/components/ui/OfflineBanner";

const { width } = Dimensions.get("window");

export default function ScreensLayout() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { isSignedIn } = useAuth();

  // NOTIF-02 FIX: Register push notifications for the vendor app
  usePushNotifications('vendor');

  const router = useRouter();
  const path = usePathname();
  const insets = useSafeAreaInsets();

  const active = (pathname: string) => pathname === path;

  const { data: orders = [] } = useVendorOrders();
  const pendingCount = orders.filter((o: any) => o.order_status === "pending").length;

  const handleTabPress = (route: any) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    router.push(route);
  };

  // The customer and rider apps both gate this group; the vendor app did not, so
  // a deep link — or simply staying put after a session ended — rendered the
  // whole store dashboard shell with no session behind it. `=== false` rather
  // than `!isSignedIn`: the value is `undefined` until Clerk resolves, and
  // redirecting then would bounce a signed-in vendor back to the sign-in screen
  // on every cold start.
  if (isSignedIn === false) {
    return <Redirect href={'/(Auth)'} />;
  }

  return (
      <View className="flex-1" style={{ minWidth: width, backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }}>
        <OfflineBanner />
        <Stack
          screenOptions={{
            headerShown: false,
            animation: 'fade',
            contentStyle: { backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }
          }}
        >
        <Stack.Screen name="index" />
        <Stack.Screen name="Products" />
        <Stack.Screen name="Orders" />
        <Stack.Screen name="Profile" />
        
        <Stack.Screen name="WalletScreen" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="Transactions" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="BottleReconciliation" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="MyMap" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="AddProduct" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="Notifications" options={{ animation: 'slide_from_right' }} />

        <Stack.Screen name="OwnerProfile" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="business/OperatingHours" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="business/PayoutSettings" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="business/ManageStaff" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="OrderDetail/[id]" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="EditProduct/[id]" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="Map/[id]" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="StoreProfile" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="RiderManagement" options={{ animation: 'slide_from_right' }} />
      </Stack>
      <View 
        className="bg-transparent items-center px-4 w-full absolute"
        style={{ bottom: insets.bottom + 8 }}
        pointerEvents="box-none"
      >
        <View 
          className={`rounded-full px-4 flex-row justify-around items-center w-full max-w-[350px] h-[64px] z-50 ${ darkTheme ? "bg-surface-container border" : "bg-white border border-gray-100"}`}
          style={darkTheme ? { borderColor: 'rgba(255,255,255,0.1)' } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
        >
          <PressableScale onPress={() => handleTabPress("/")}>
            <View className={`w-14 h-14 items-center justify-center ${active("/") ? "bg-primary-container rounded-full" : ""}`}>
              <VendorTabIcon name="home" active={active("/")} />
            </View>
          </PressableScale>
          
          <PressableScale onPress={() => handleTabPress("/Products")}>
            <View className={`w-14 h-14 items-center justify-center ${active("/Products") ? "bg-primary-container rounded-full" : ""}`}>
              <VendorTabIcon name="products" active={active("/Products")} />
            </View>
          </PressableScale>
          
          <PressableScale onPress={() => handleTabPress("/Orders")}>
            <View className={`w-14 h-14 items-center justify-center ${active("/Orders") ? "bg-primary-container rounded-full" : ""}`}>
              <VendorTabIcon name="orders" active={active("/Orders")} count={pendingCount} />
            </View>
          </PressableScale>
          
          <PressableScale onPress={() => handleTabPress("/Profile")}>
            <View className={`w-14 h-14 items-center justify-center ${active("/Profile") ? "bg-primary-container rounded-full" : ""}`}>
              <VendorTabIcon name="profile" active={active("/Profile")} />
            </View>
          </PressableScale>
        </View>
      </View>
      </View>
  );
}
