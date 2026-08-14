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
import { retryTransientOnly } from '@/API/errors';
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
      // A 4xx is a refusal, not a dropped packet. A plain `retry: 2` — which is
      // what this was, while the customer and rider apps had both already been
      // corrected — made every refusal cost three round trips before the vendor
      // saw it, and because the client signs out on a 401, fired the sign-out
      // handler **three times for one expired session**. On the surface where a
      // shop that cannot see its orders is losing money by the minute.
      retry: retryTransientOnly(2),
      refetchOnWindowFocus: true, // Enables refetch on app foreground
      // Read from cache first and fire the request behind it, rather than
      // suspending on the network. A store's counter is often the worst
      // reception in the building; the orders it already has must render while
      // the refresh is in flight, not after it.
      networkMode: 'offlineFirst',
    },
    mutations: {
      // A mutation is an *action*. Retrying a refused one changes nothing and
      // retrying a timed-out one risks applying it twice, so replay belongs to
      // the queue that can carry an idempotency key, not to a blind retry.
      retry: retryTransientOnly(0),
      networkMode: 'offlineFirst',
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
  /**
   * Karla for body and UI, Fredoka for headings, JetBrains Mono for figures.
   *
   * Every weight is its own file: React Native has no variable-font weight
   * axis and no `font-synthesis-weight`, so the only way to avoid the OS
   * faking a weight is to load the real face and name it. That is why the
   * Tailwind tokens in `tailwind.config.js` are per weight rather than one
   * family plus `font-sans-bold`.
   *
   * Fredoka stops at 600 deliberately — its heavier weights read as a
   * children's brand, and this app handles people's money. 600 is the
   * heaviest heading weight the platform uses anywhere.
   *
   * Inter is gone. Nothing names it any more — the last references were the
   * `StyleSheet` scale in `constants/typography.ts` and the avatar's initials.
   * A registered face nothing asks for is dead weight in the bundle, and a
   * second body font is how two screens quietly stop matching.
   */
  const [fontsLoaded] = useFonts({
    // Karla
    'Karla_200ExtraLight': require('../assets/fonts/Karla_200ExtraLight.ttf'),
    'Karla_300Light': require('../assets/fonts/Karla_300Light.ttf'),
    'Karla_400Regular': require('../assets/fonts/Karla_400Regular.ttf'),
    'Karla_500Medium': require('../assets/fonts/Karla_500Medium.ttf'),
    'Karla_600SemiBold': require('../assets/fonts/Karla_600SemiBold.ttf'),
    'Karla_700Bold': require('../assets/fonts/Karla_700Bold.ttf'),
    'Karla_800ExtraBold': require('../assets/fonts/Karla_800ExtraBold.ttf'),

    // Fredoka
    'Fredoka_400Regular': require('../assets/fonts/Fredoka_400Regular.ttf'),
    'Fredoka_500Medium': require('../assets/fonts/Fredoka_500Medium.ttf'),
    'Fredoka_600SemiBold': require('../assets/fonts/Fredoka_600SemiBold.ttf'),

    // JetBrainsMono
    'JetBrainsMono_100Thin': require('../assets/fonts/JetBrainsMono_100Thin.ttf'),
    'JetBrainsMono_200ExtraLight': require('../assets/fonts/JetBrainsMono_200ExtraLight.ttf'),
    'JetBrainsMono_300Light': require('../assets/fonts/JetBrainsMono_300Light.ttf'),
    'JetBrainsMono_400Regular': require('../assets/fonts/JetBrainsMono_400Regular.ttf'),
    'JetBrainsMono_500Medium': require('../assets/fonts/JetBrainsMono_500Medium.ttf'),
    'JetBrainsMono_600SemiBold': require('../assets/fonts/JetBrainsMono_600SemiBold.ttf'),
    'JetBrainsMono_700Bold': require('../assets/fonts/JetBrainsMono_700Bold.ttf'),
    'JetBrainsMono_800ExtraBold': require('../assets/fonts/JetBrainsMono_800ExtraBold.ttf'),
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
