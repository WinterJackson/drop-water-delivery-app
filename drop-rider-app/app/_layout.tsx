import ModernToast from "@/components/ui/ModernToast";
import PopupModal from "@/components/ui/PopupModal";
import { ClerkProvider } from "@clerk/clerk-expo";
import { tokenCache } from "@clerk/clerk-expo/token-cache";
import {
    DarkTheme,
    DefaultTheme,
    ThemeProvider,
} from "@react-navigation/native";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { LogBox, useColorScheme, AppState, AppStateStatus, Platform } from "react-native";
import "react-native-gesture-handler";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import "react-native-reanimated";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { ErrorBoundary } from "../components/common/ErrorBoundary";
import { retryTransientOnly } from "@/API/errors";
import { useSessionCleanup } from "@/hooks/useSessionCleanup";
import { initDB } from "../config/database";
// Imported for its side effect: `TaskManager.defineTask` must run before the OS
// delivers a location update, including when Android relaunches the app
// headlessly to feed the foreground service. Registering it inside the screen
// that starts tracking would be too late.
import "@/services/locationTracking";
import ThemeContextProvider from "../context/ThemeContext";
import "../global.css";
import { BRAND } from "../constants/brandColors";

LogBox.ignoreLogs([
  "Clerk: Clerk has been loaded with development keys",
  "SafeAreaView has been deprecated",
  "App update check failed",
]);

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 1000 * 60 * 2,
            gcTime: 1000 * 60 * 10,
            // A 4xx is a refusal, not a dropped packet. A plain `retry: 2` made
            // every refusal cost three round-trips before the rider saw it —
            // and, because the client signs out on a 401, fired the sign-out
            // handler three times for one expired session.
            retry: retryTransientOnly(2),
            refetchOnWindowFocus: true, // Enables refetch on app foreground
        },
        mutations: {
            retry: retryTransientOnly(0),
        },
    },
});

SplashScreen.preventAutoHideAsync();

const clerkPublishableKey = process.env.EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";

if (__DEV__ && !clerkPublishableKey) {
    console.warn(
        "[Clerk] EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY is missing. Set it in .env for auth to work.",
    );
}

/**
 * Erases the previous rider's cached data whenever a session ends — including
 * the sign-outs nobody taps, such as the 401 handler in every rider query and a
 * session revoked by Clerk. Clears the on-disk offline manifest too. Must live
 * inside both providers.
 */
const SessionCleanup = () => {
    useSessionCleanup();
    return null;
};

export default function Layout() {
    const colorScheme = useColorScheme();

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
      Karla_200ExtraLight: require('../assets/fonts/Karla_200ExtraLight.ttf'),
      Karla_300Light: require('../assets/fonts/Karla_300Light.ttf'),
      Karla_400Regular: require('../assets/fonts/Karla_400Regular.ttf'),
      Karla_500Medium: require('../assets/fonts/Karla_500Medium.ttf'),
      Karla_600SemiBold: require('../assets/fonts/Karla_600SemiBold.ttf'),
      Karla_700Bold: require('../assets/fonts/Karla_700Bold.ttf'),
      Karla_800ExtraBold: require('../assets/fonts/Karla_800ExtraBold.ttf'),

      // Fredoka
      Fredoka_400Regular: require('../assets/fonts/Fredoka_400Regular.ttf'),
      Fredoka_500Medium: require('../assets/fonts/Fredoka_500Medium.ttf'),
      Fredoka_600SemiBold: require('../assets/fonts/Fredoka_600SemiBold.ttf'),

      // JetBrainsMono
      JetBrainsMono_100Thin: require('../assets/fonts/JetBrainsMono_100Thin.ttf'),
      JetBrainsMono_200ExtraLight: require('../assets/fonts/JetBrainsMono_200ExtraLight.ttf'),
      JetBrainsMono_300Light: require('../assets/fonts/JetBrainsMono_300Light.ttf'),
      JetBrainsMono_400Regular: require('../assets/fonts/JetBrainsMono_400Regular.ttf'),
      JetBrainsMono_500Medium: require('../assets/fonts/JetBrainsMono_500Medium.ttf'),
      JetBrainsMono_600SemiBold: require('../assets/fonts/JetBrainsMono_600SemiBold.ttf'),
      JetBrainsMono_700Bold: require('../assets/fonts/JetBrainsMono_700Bold.ttf'),
      JetBrainsMono_800ExtraBold: require('../assets/fonts/JetBrainsMono_800ExtraBold.ttf'),
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
        const prepare = async () => {
            try {
                await initDB();
            } catch (e) {
                // expo-sqlite may fail in Expo Go or if the native module isn't linked.
                // This is non-fatal — offline caching just won't be available.
                if (__DEV__) console.warn('[initDB] SQLite init failed (non-fatal):', e);
            } finally {
                if (fontsLoaded) {
                    await SplashScreen.hideAsync();
                    import('../utils/sentry').then(({ initSentry }) => initSentry());
                }
            }
        };
        prepare();
    }, [fontsLoaded]);

    if (!fontsLoaded) return null;

    return (
        <SafeAreaProvider>
            <GestureHandlerRootView style={{ flex: 1, backgroundColor: colorScheme === "dark" ? BRAND.bgDark : BRAND.bgLight }}>
                <ClerkProvider
                    publishableKey={clerkPublishableKey}
                    tokenCache={tokenCache}
                >
                    <QueryClientProvider client={queryClient}>
                        <SessionCleanup />
                        <ThemeProvider
                            value={
                                colorScheme === "dark"
                                    ? DarkTheme
                                    : DefaultTheme
                            }
                        >
                            <ThemeContextProvider>
                                <ErrorBoundary>
                                    <Stack
                                        screenOptions={{
                                            headerShown: false,
                                            contentStyle: { backgroundColor: colorScheme === "dark" ? BRAND.bgDark : BRAND.bgLight }
                                        }}
                                    >
                                        <Stack.Screen
                                            name="index"
                                            options={{ headerShown: false }}
                                        />
                                        <Stack.Screen
                                            name="(screens)"
                                            options={{ headerShown: false }}
                                        />
                                        <Stack.Screen
                                            name="(Auth)"
                                            options={{ headerShown: false }}
                                        />
                                    </Stack>
                                </ErrorBoundary>
                                <ModernToast />
                                <PopupModal />
                            </ThemeContextProvider>
                        </ThemeProvider>
                    </QueryClientProvider>
                </ClerkProvider>
            </GestureHandlerRootView>
        </SafeAreaProvider>
    );
}
