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
import { useSessionCleanup } from "@/hooks/useSessionCleanup";
import { initDB } from "../config/database";
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
            retry: 2,
            refetchOnWindowFocus: true, // Enables refetch on app foreground
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
    const [fontsLoaded] = useFonts({
        Inter_400Regular: require("../assets/fonts/Inter-Regular.ttf"),
        Inter_500Medium: require("../assets/fonts/Inter-Medium.ttf"),
        Inter_600SemiBold: require("../assets/fonts/Inter-SemiBold.ttf"),
        Inter_700Bold: require("../assets/fonts/Inter-Bold.ttf"),
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
