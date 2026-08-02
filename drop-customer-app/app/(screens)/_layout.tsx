import TabIcon from "@/components/ui/TabIcon";
import { UIThemeContext } from "@/context/ThemeContext";
import Context from "@/context/context";
import { BRAND } from "@/constants/brandColors";
import { useCart } from "@/hooks/queries/useCart";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useAuth } from "@clerk/clerk-expo";
import { useQueryClient } from "@tanstack/react-query";
import { Redirect, Stack, usePathname, useRouter } from "expo-router";
import { useContext } from "react";
import { PressableScale } from "@/components/ui/PressableScale";
import {
    ActivityIndicator,
    Dimensions,
    StatusBar,
    View,
} from "react-native";
import { useSafeAreaInsets } from 'react-native-safe-area-context';






const { width, height } = Dimensions.get("window");

const Layout = () => {
	// <--------------------HOOKES------------------->
  const {currentTheme} = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark"  
  const router = useRouter();
  const path = usePathname();
  const { isSignedIn, isLoaded, getToken, signOut } = useAuth()
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  
	// <--------------------STATES------------------->
  const { data: Cart } = useCart();
  
  // NOTIF-01 FIX: Register push notifications for the customer app
  usePushNotifications();
  
  const active = (pathname: string) => {
    return pathname === path;
  };

  const fetchCart = async () => {
    await queryClient.invalidateQueries({ queryKey: ['cart'] });
  };

  const SignOut = async () => {
    queryClient.clear();
    await signOut();
  };
  
  // <------------------VARIABLES------------------>
  const statusbarHieght = StatusBar.currentHeight || 0;
  

  
  // Nothing in this group may mount until Clerk has resolved. Every query below
  // fires on mount, and while `isLoaded` is false `getToken()` yields nothing —
  // so a deep link straight into this group (the app registers the
  // `drop-customer` scheme) sent a burst of token-less requests, each 401'd, and
  // the 401 interceptor signs the user out. A valid session was destroyed by the
  // act of opening a link.
  if (!isLoaded) {
    return (
      <View className="flex-1 items-center justify-center" style={{ backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }}>
        <ActivityIndicator size="large" color={BRAND.primary} />
      </View>
    );
  }

  if (isSignedIn === false) {
    return <Redirect href={'/(Auth)'} />
  }
  return (
      <View
        className={`flex-1`}
        style={[{
          minWidth: width,
          backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight
        }]}
      >

				<Context.Provider value={{ fetchCart, SignOut }}>
          <Stack
            screenOptions={{
              headerShown: false,
              animation: 'fade', // Default to fade for the main custom tab transitions
              statusBarAnimation: "slide",
              contentStyle: { backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }
            }}
          >
            {/* Main Tabs (Fade) */}
            <Stack.Screen name="index" />
            <Stack.Screen name="Search" />
            <Stack.Screen name="Cart" />
            <Stack.Screen name="Orders" />
            
            {/* General Pages (Slide) */}
            <Stack.Screen name="Profile" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="Notifications" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="PaymentHistory" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="BottleWallet" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="Transactions" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="OrderDetail" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="SettingsMain" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="Support" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="SupportTicket" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="VendorDirectory" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="Offers" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="repeat-order" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="settings/PersonalDetails" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="settings/SavedLocations" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="settings/PaymentMethods" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="settings/NotificationPreferences" options={{ animation: 'slide_from_right' }} />
            
            {/* Dynamic Drill-Downs (Slide) */}
            <Stack.Screen name="product-details/[id]" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="vendor/[id]" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="Map/[id]" options={{ animation: 'slide_from_right' }} />
            <Stack.Screen name="LocationSearch" options={{ animation: 'slide_from_right' }} />
            
            {/* Modals & Dialogs */}
            <Stack.Screen name="order-confirmation" options={{ animation: 'fade_from_bottom', presentation: 'transparentModal' }} />
            <Stack.Screen name="RateOrder" options={{ animation: 'fade_from_bottom', presentation: 'transparentModal' }} />
          </Stack>
        
        </Context.Provider>

        {/* Bottom Navigation Bar */}
        <View 
          className="bg-transparent items-center px-gutter w-full absolute z-50"
          style={{ bottom: insets.bottom + 8 }}
        >
          <View 
            className={`rounded-full px-4 flex-row justify-around items-center w-full max-w-[350px] h-[64px] ${ darkTheme? "bg-surface-container border" : "bg-white border border-gray-100"}`}
            style={darkTheme ? { borderColor: 'rgba(255,255,255,0.1)' } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
          >
            {/* Home */}
            <PressableScale onPress={() => router.push("/(screens)")}>
              <View className={`w-14 h-14 items-center justify-center ${active("/") ? "bg-primary-container rounded-full" : ""}`}>
                <TabIcon name="home" active={active("/")} />
              </View>
            </PressableScale>
            
            {/* Search */}
            <PressableScale onPress={() => router.push("/(screens)/Search")}>
              <View className={`w-14 h-14 items-center justify-center ${active("/Search") ? "bg-primary-container rounded-full" : ""}`}>
                <TabIcon name="search" active={active("/Search")} />
              </View>
            </PressableScale>
            
            {/* Cart */}
            <PressableScale onPress={() => router.push("/(screens)/Cart")}>
              <View className={`w-14 h-14 items-center justify-center ${active("/Cart") ? "bg-primary-container rounded-full" : ""}`}>
                <TabIcon name="cart" active={active("/Cart")} count={Cart?.items_count} />
              </View>
            </PressableScale>
            
            {/* Orders */}
            <PressableScale onPress={() => router.push("/(screens)/Orders")}>
              <View className={`w-14 h-14 items-center justify-center ${active("/Orders") ? "bg-primary-container rounded-full" : ""}`}>
                <TabIcon name="order" active={active("/Orders")} />
              </View>
            </PressableScale>
          </View>
        </View>
      </View>

    //   <Context.Provider value={{ fetchCart }}>
    //     ... (Dead Tabs code removed for clarity and performance) ...
    //   </Context.Provider>
  );
};

export default Layout;
