import 'react-native-gesture-handler';
import { ClerkProvider, useUser as useClerkUser } from '@clerk/clerk-expo';
import { tokenCache } from '@clerk/clerk-expo/token-cache';
import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import ModernToast from '@/components/ui/ModernToast';
import PopupModal from '@/components/ui/PopupModal';
import { QueryClient, focusManager } from '@tanstack/react-query';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { useKeepAwake } from 'expo-keep-awake';
import { Stack } from "expo-router";
import * as SplashScreen from 'expo-splash-screen';
import React, { useEffect } from 'react';
import { Dimensions, LogBox, AppState, AppStateStatus } from "react-native";
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { useFonts } from 'expo-font';

// `asyncStoragePersister` is shared with `useSessionCleanup`, which erases the
// on-disk snapshot when a session ends — see config/queryPersister.ts.
import { asyncStoragePersister } from '@/config/queryPersister';
import { retryTransientOnly } from '@/API/errors';
import { useSessionCleanup } from '@/hooks/useSessionCleanup';

import { BottomSheetModalProvider } from '@gorhom/bottom-sheet';

import { ErrorBoundary } from '../components/common/ErrorBoundary';
import ThemeContextProvider from '../context/ThemeContext';
import { initSentry, setSentryUser, clearSentryUser } from '../utils/sentry';
import OfflineBanner from '../components/ui/OfflineBanner';
import "../global.css";
import { initAnalytics } from '../utils/analytics';
import { checkForAppUpdate } from '../utils/appUpdate';
import { UIThemeContext } from '../context/ThemeContext';
import { BRAND } from '../constants/brandColors';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,       // 5 minutes
      gcTime: 1000 * 60 * 15,         // 15 minutes GC
      retry: retryTransientOnly(2),
      refetchOnWindowFocus: true,     // Enables refetch on app foreground
      networkMode: 'offlineFirst',
    },
    mutations: {
      networkMode: 'offlineFirst',
    },
  },
});

import { useColorScheme } from '@/hooks/use-color-scheme';

SplashScreen.preventAutoHideAsync().catch(() => {
  // Silently fail in Expo Go where keep-awake is unavailable
});

LogBox.ignoreLogs([
  'SafeAreaView has been deprecated',
  'App update check failed',
]);
 
const { height, width } = Dimensions.get("window");
import * as NavigationBar from 'expo-navigation-bar';
import { Platform } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

/**
 * Attaches the signed-in identity to Sentry so a crash report names the account
 * it came from, and drops it on sign-out so the next session is not attributed
 * to the previous user. Must live inside ClerkProvider.
 */
const SentryUserSync = () => {
  const { user, isLoaded } = useClerkUser();

  useEffect(() => {
    if (!isLoaded) return;
    if (user) {
      setSentryUser(user.id, user.primaryEmailAddress?.emailAddress);
    } else {
      clearSentryUser();
    }
  }, [isLoaded, user?.id]);

  return null;
};

/**
 * Erases the previous account's cached data whenever a session ends — including
 * the sign-outs nobody taps, such as `useApiClient`'s 401 handler and a session
 * revoked by Clerk. Must live inside both providers.
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
        <PersistQueryClientProvider client={queryClient} persistOptions={{ persister: asyncStoragePersister, maxAge: 1000 * 60 * 60 * 24 }}>
          <SentryUserSync />
          <SessionCleanup />
          <BottomSheetModalProvider>
            <OfflineBanner />
            <ErrorBoundary>
              <Stack screenOptions={{ 
                headerShown: false, 
                animation: 'fade',
                contentStyle: { backgroundColor: isDark ? BRAND.bgDark : BRAND.bgLight }
              }}>
                <Stack.Screen name="index" options={{ headerShown: false }} />
                <Stack.Screen name="(screens)" options={{ headerShown: false }} />
                <Stack.Screen name="(Auth)" options={{ headerShown: false }} />
              </Stack>
            </ErrorBoundary>
          </BottomSheetModalProvider>
        </PersistQueryClientProvider>
      </ClerkProvider>
    </ThemeProvider>
  );
};

export default function Layout() {
  // Keep screen awake during app usage
  useKeepAwake();

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

  // <------------------HOOKES------------------>
  const darkTheme = useColorScheme() === "dark"

  // Hide the native splash screen once fonts are ready
  useEffect(() => {
    if (fontsLoaded) {
      SplashScreen.hideAsync();
    }
  }, [fontsLoaded]);

  // Production tools — exactly once. Keyed on `fontsLoaded` these ran twice per
  // launch, double-initialising Sentry and firing two update checks.
  useEffect(() => {
    initSentry();
    initAnalytics(null);
    checkForAppUpdate();
  }, []);

  useEffect(() => {
    if (Platform.OS === 'android') {
      NavigationBar.setButtonStyleAsync(darkTheme ? 'light' : 'dark');
    }
  }, [darkTheme]);

  // <------------------STATES------------------>
  // waits for the native splash screen to hide before starting its timer.
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
