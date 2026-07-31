import { ClerkProvider } from "@clerk/clerk-expo";
import { tokenCache } from "@clerk/clerk-expo/token-cache";
import ModernToast from '@/components/ui/ModernToast';
import PopupModal from '@/components/ui/PopupModal';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { DarkTheme, DefaultTheme, ThemeProvider } from "@react-navigation/native";
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import React, { useEffect } from "react";
import { useColorScheme, LogBox, AppState, AppStateStatus, Platform } from "react-native";
import { configureReanimatedLogger, ReanimatedLogLevel } from 'react-native-reanimated';
import { useFonts } from 'expo-font';
import { ErrorBoundary } from '../components/common/ErrorBoundary';
import { useSessionCleanup } from '@/hooks/useSessionCleanup';
import ThemeContextProvider, { UIThemeContext } from "../context/ThemeContext";
import { BottomSheetModalProvider } from "@gorhom/bottom-sheet";
import "../global.css";
import { BRAND } from "../constants/brandColors";

LogBox.ignoreLogs([
  "Clerk: Clerk has been loaded with development keys",
  "SafeAreaView has been deprecated",
  "App update check failed",
]);

configureReanimatedLogger({
  level: ReanimatedLogLevel.warn,
  strict: false, // Disable strict mode to avoid noisy "Writing to value during component render" warnings from Gorhom BottomSheet
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 2,
      gcTime: 1000 * 60 * 10,
      retry: 2,
      refetchOnWindowFocus: true, // Enables refetch on app foreground
    },
  },
});

SplashScreen.preventAutoHideAsync();

/**
 * Erases the previous store's cached data whenever a session ends — including
 * the sign-outs nobody taps, such as the 401 handler in every vendor query and a
 * session revoked by Clerk. Must live inside both providers.
 */
const SessionCleanup = () => {
  useSessionCleanup();
  return null;
};

const RootAppNavigation = () => {
  const { currentTheme } = React.useContext(UIThemeContext);
  const isDark = currentTheme === 'dark';

  return (
    <ThemeProvider value={isDark ? DarkTheme : DefaultTheme}>
      <ClerkProvider publishableKey={process.env.EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY} tokenCache={tokenCache}>
        <QueryClientProvider client={queryClient}>
          <SessionCleanup />
          <BottomSheetModalProvider>
            <ErrorBoundary>
              <Stack screenOptions={{ 
                headerShown: false,
                contentStyle: { backgroundColor: isDark ? BRAND.bgDark : BRAND.bgLight }
              }}>
                <Stack.Screen name="index" options={{ headerShown: false }} />
                <Stack.Screen name="(screens)" options={{ headerShown: false }} />
                <Stack.Screen name="(Auth)" options={{ headerShown: false }} />
              </Stack>
            </ErrorBoundary>
          </BottomSheetModalProvider>
        </QueryClientProvider>
      </ClerkProvider>
    </ThemeProvider>
  );
};

export default function Layout() {
  const colorScheme = useColorScheme();
  const darkTheme = colorScheme === "dark";

  // ── Font loading ──
  const [fontsLoaded] = useFonts({
    'Inter_400Regular': require('../assets/fonts/Inter-Regular.ttf'),
    'Inter_500Medium': require('../assets/fonts/Inter-Medium.ttf'),
    'Inter_600SemiBold': require('../assets/fonts/Inter-SemiBold.ttf'),
    'Inter_700Bold': require('../assets/fonts/Inter-Bold.ttf'),
  });

  // ── AppState Focus Manager for React Query ──
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (status: AppStateStatus) => {
      if (Platform.OS !== 'web') {
        focusManager.setFocused(status === 'active');
      }
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (fontsLoaded) {
      SplashScreen.hideAsync();
      import('../utils/sentry').then(({ initSentry }) => initSentry());
    }
  }, [fontsLoaded]);

  if (!fontsLoaded) return null;

  return (
    <SafeAreaProvider>
      <GestureHandlerRootView style={{ flex: 1, backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }}>
        <ThemeContextProvider>
          <RootAppNavigation />
          <ModernToast />
          <PopupModal />
        </ThemeContextProvider>
      </GestureHandlerRootView>
    </SafeAreaProvider>
  );
}
