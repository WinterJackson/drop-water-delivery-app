import TabIcon from "@/components/ui/TabIcon";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useNetworkQueue } from "@/hooks/useNetworkQueue";
import { useRiderLocationTracking } from "@/hooks/useRiderLocationTracking";
import { useAuth } from "@clerk/clerk-expo";
import { Stack, usePathname, useRouter, Redirect } from "expo-router";
import { useContext, useEffect } from "react";
import { useRiderStore } from "@/stores/useRiderStore";
import { PressableScale } from "@/components/ui/PressableScale";
import { ActivityIndicator, Dimensions, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useQueryClient } from "@tanstack/react-query";
import { Ionicons } from "@expo/vector-icons";
import { NOT_A_RIDER, useKycStatus } from "@/hooks/queries/useKycStatus";

const { width } = Dimensions.get("window");

export default function ScreensLayout() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const router = useRouter();
  const path = usePathname();
  // One destructure. This was two separate `useAuth()` calls, which is how
  // `isLoaded` came to be missing from the guard below without anyone noticing.
  const { isSignedIn, isLoaded, signOut } = useAuth();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();

  useNetworkQueue();
  useRiderLocationTracking();
  const { clearPushToken } = usePushNotifications('rider');

  // Muted vendors are device-local and read by TripRadar and DiscoverVendors,
  // neither of which is guaranteed to mount first.
  useEffect(() => { useRiderStore.getState().hydrateMutedVendors(); }, []);

  // KYC & operational status, shared with Profile and VerificationWall through
  // one cache entry so the gate and the wall can never disagree.
  const { data: statusData, isError, error, refetch, isFetching } = useKycStatus(
    !!isSignedIn && isLoaded
  );

  const active = (pathname: string) => {
    return pathname === path;
  };

  const bg = darkTheme ? BRAND.bgDark : BRAND.bgLight;

  // Nothing in this group may mount until Clerk has resolved. Every rider query
  // fires on mount, and while `isLoaded` is false `getToken()` yields nothing —
  // so a deep link straight into this group sent a burst of token-less requests,
  // each 401'd, and each 401 handler calls `signOut()`. Opening a link destroyed
  // a valid session.
  if (!isLoaded) {
    return (
      <View className="flex-1 items-center justify-center" style={{ backgroundColor: bg }}>
        <ActivityIndicator size="large" color={BRAND.primary} />
      </View>
    );
  }

  if (isSignedIn === false) {
    return <Redirect href={'/(Auth)'} />
  }

  // If KYC fails with 403, rider is not registered at all.
  if (isError && (error as Error).message === NOT_A_RIDER) {
    return <Redirect href={'/(Auth)/Onboarding' as any} />
  }

  // ── The verification gate ────────────────────────────────────────────────
  // This gate fails *closed*. It used to read `if (!statusLoading && statusData)`,
  // so any failure of the status query — a network blip, a 500, a timeout — left
  // `statusData` undefined, skipped the branch entirely, and dropped the rider
  // into the full app including Trip Radar. Turning wifi off at the right moment
  // was enough to bypass KYC. The backend now refuses independently
  // (`get_verified_rider`), but the client must not depend on that to behave.
  //
  // So: approval has to be *positively* confirmed. Anything else blocks.
  if (!statusData && !isError) {
    return (
      <View className="flex-1 items-center justify-center" style={{ backgroundColor: bg }}>
        <ActivityIndicator size="large" color={BRAND.primary} />
        <Text className={`mt-4 text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
          Checking your verification…
        </Text>
      </View>
    );
  }

  // A blocking gate needs a way forward, or a five-minute outage strands a
  // working rider mid-shift with a dead screen. Retry, and sign out as the
  // escape hatch.
  if (isError) {
    return (
      <View className="flex-1 items-center justify-center px-6" style={{ backgroundColor: bg }}>
        <Ionicons name="cloud-offline-outline" size={48} color={BRAND.primary} />
        <Text className={`text-lg font-sans-bold text-center mt-4 ${darkTheme ? "text-white" : "text-black"}`}>
          Can't confirm your verification
        </Text>
        <Text className={`text-sm text-center mt-2 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
          You need to be online for a moment so we can check your account status. Check your
          connection and try again.
        </Text>
        <PressableScale
          onPress={() => refetch()}
          disabled={isFetching}
          className="mt-6 bg-accentbg px-6 py-3 rounded-xl min-w-[140px] items-center"
        >
          {isFetching
            ? <ActivityIndicator size="small" color="#fff" />
            : <Text className="text-white font-sans-bold">Try again</Text>}
        </PressableScale>
        <PressableScale
          onPress={async () => {
            await clearPushToken();
            queryClient.clear();
            await signOut();
          }}
          className="mt-4 p-2"
        >
          <Text className="text-accentbg font-sans-bold">Sign out</Text>
        </PressableScale>
      </View>
    );
  }

  // Support is reachable before verification, and that is the point: a rider
  // waiting four days on KYC is exactly the person who needs to ask why. Sending
  // them back to the wall they are already stuck behind leaves them with the app
  // store review page as their only way to reach anybody.
  //
  // `SupportTicket` is listed even though the match below is a substring one
  // that already lets it through — reading the *answer* matters at least as much
  // as asking the question, and relying on one screen's name being a prefix of
  // the other's is a rename away from stranding exactly this rider.
  const allowedWhileUnverified = ["VerificationWall", "Support", "SupportTicket"];

  if (
    statusData?.kyc_status !== "approved" &&
    !allowedWhileUnverified.some((screen) => path.includes(screen))
  ) {
    return <Redirect href={'/(screens)/VerificationWall'} />
  }

  const isOperational = statusData?.kyc_status === "approved" && !!statusData?.employer_vendor_id;

  return (
      <View
        className={`flex-1`}
        style={[{ minWidth: width, backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }]}
      >
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
          <Stack.Screen name="TripRadar" />
          <Stack.Screen name="ActiveDelivery" />
          <Stack.Screen name="Profile" />
          
          {/* General Pages (Slide) */}
          <Stack.Screen name="Orders" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="Earnings" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="Cashout" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="Transactions" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="Notifications" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="SettingsMain" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="EarningsHistory" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="Performance" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="BottleRejection" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="Reviews" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="MyVendors" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="OperationBase" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="DiscoverVendors" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="VerificationWall" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="PendingSync" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="Support" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="SupportTicket" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="rider/VehicleDetails" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="rider/BankDetails" options={{ animation: 'slide_from_right' }} />
          <Stack.Screen name="rider/Preferences" options={{ animation: 'slide_from_right' }} />
        </Stack>

        {/* Bottom Navigation Bar — hidden wherever there is nowhere to go.
            An unverified rider can reach exactly two screens, and offering tabs
            that bounce straight back to the wall reads as a broken app. */}
        {path !== "/VerificationWall" && statusData?.kyc_status === "approved" && (
        <View 
          className="bg-transparent items-center px-gutter w-full absolute z-50 pointer-events-box-none"
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
            
            {/* Radar - Hidden if not operational */}
            {isOperational && (
              <PressableScale onPress={() => router.push("/(screens)/TripRadar")}>
                <View className={`w-14 h-14 items-center justify-center ${active("/TripRadar") ? "bg-primary-container rounded-full" : ""}`}>
                  <TabIcon name="radar" active={active("/TripRadar")} />
                </View>
              </PressableScale>
            )}
            
            {/* Active Delivery - Hidden if not operational */}
            {isOperational && (
              <PressableScale onPress={() => router.push("/(screens)/ActiveDelivery")}>
                <View className={`w-14 h-14 items-center justify-center ${active("/ActiveDelivery") ? "bg-primary-container rounded-full" : ""}`}>
                  <TabIcon name="delivery" active={active("/ActiveDelivery")} />
                </View>
              </PressableScale>
            )}
            

            {/* Profile */}
            <PressableScale onPress={() => router.push("/(screens)/Profile")}>
              <View className={`w-14 h-14 items-center justify-center ${active("/Profile") ? "bg-primary-container rounded-full" : ""}`}>
                <TabIcon name="profile" active={active("/Profile")} />
              </View>
            </PressableScale>
          </View>
        </View>
        )}
      </View>
  );
}
