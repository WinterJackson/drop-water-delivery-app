import { useCallback, useContext, useEffect, useState } from "react";
import { useAuth } from "@clerk/clerk-expo";
import { Redirect } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { Text } from '@/components/ui/Text';

import { apiFetch } from "@/API/apiFetch";
import { ApiError, errorMessage } from "@/API/errors";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import PressableScale from "@/components/ui/PressableScale";
import { AnimatedSplash } from "@/components/splash/AnimatedSplash";
import { UIThemeContext } from "@/context/ThemeContext";
import { useActiveStore } from "@/stores/activeStoreStore";

interface ProfileStatus {
  exists: boolean;
  missing_fields?: string[];
}

interface Store {
  id: string;
}

/**
 * Has the launch animation already played in this process?
 *
 * Module scope on purpose: component state resets on remount, and this
 * route is remounted by every redirect to "/" — which the sign-in screen
 * does the moment a session is created. Seeded into `useState`, this stops
 * the full SPLASH_DURATION_MS (10s) replaying after a successful sign-in.
 */
let hasPlayedSplash = false;

export default function Index() {
  const { isSignedIn, isLoaded, getToken } = useAuth();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const [splashDone, setSplashDone] = useState(hasPlayedSplash);
  const [readyToRoute, setReadyToRoute] = useState<"onboarding" | "main" | null>(null);
  const [startupError, setStartupError] = useState<string | null>(null);

  const hydrateActiveStore = useActiveStore((s) => s.hydrate);
  const reconcileStores = useActiveStore((s) => s.reconcile);

  const verifyOnboardingAndProceed = useCallback(async () => {
    setStartupError(null);
    try {
      const token = await getToken();

      const status = await apiFetch<ProfileStatus>(
        VendorApiRoutes.GetProfileStatus.path,
        { token }
      );

      if (!status.exists || (status.missing_fields && status.missing_fields.length > 0)) {
        setReadyToRoute("onboarding");
        return;
      }

      // Restore the store they were last working in before anything queries it,
      // so the first dashboard request already carries the right `X-Store-Id`.
      await hydrateActiveStore();

      const stores = await apiFetch<Store[]>(VendorApiRoutes.GetStores.path, { token });
      if (!stores.length) {
        setReadyToRoute("onboarding");
        return;
      }

      // Drop a remembered store this account can no longer reach — a different
      // vendor signed in on this device, or the store was deleted. Left in
      // place, every request would carry an id the backend answers 404 for.
      reconcileStores(stores.map((s) => s.id));
      setReadyToRoute("main");
    } catch (err) {
      // Only the server saying "you are not a vendor here" means onboarding. A
      // dropped connection or a 500 does not: sending an established vendor back
      // through sign-up because their train went into a tunnel is the wrong
      // failure, and it was the previous behaviour for *every* error — the
      // `catch` routed to onboarding unconditionally, timeouts included.
      if (err instanceof ApiError && err.status === 403) {
        setReadyToRoute("onboarding");
        return;
      }
      setStartupError(errorMessage(err, "We couldn't reach the server. Check your connection."));
    }
  }, [getToken, hydrateActiveStore, reconcileStores]);

  useEffect(() => {
    if (splashDone && isLoaded && isSignedIn) verifyOnboardingAndProceed();
  }, [splashDone, isLoaded, isSignedIn, verifyOnboardingAndProceed]);

  const canProceed = splashDone && isLoaded;

  if (canProceed && isSignedIn && startupError) {
    return (
      <View className={`flex-1 items-center justify-center px-8 ${darkTheme ? "bg-black" : "bg-white"}`}>
        <Text className={`text-lg font-sans-bold mb-2 text-center ${darkTheme ? "text-white" : "text-black"}`}>
          Couldn&apos;t start up
        </Text>
        <Text className={`text-center mb-6 ${darkTheme ? "text-slate-400" : "text-slate-600"}`}>
          {startupError}
        </Text>
        <PressableScale
          onPress={verifyOnboardingAndProceed}
          className="bg-accentbg px-8 py-3 rounded-xl flex-row items-center"
        >
          <ActivityIndicator animating={false} />
          <Text className="text-white font-sans-bold">Try again</Text>
        </PressableScale>
      </View>
    );
  }

  // ── Splash gate ──
  //
  // Two cases, deliberately separated because they used to be one condition.
  // This route is re-entered whenever anything redirects to "/", which the
  // sign-in screen does as soon as a session exists — so a single
  // `!isFullyReady` check sent a signed-in vendor back into the ten-second
  // launch animation before routing them onward.
  if (!splashDone) {
    return (
      <AnimatedSplash
        variant="vendor"
        isDark={darkTheme}
        onComplete={() => {
          hasPlayedSplash = true;
          setSplashDone(true);
        }}
      />
    );
  }

  // Splash already shown; Clerk or the profile check is still resolving. A wait
  // is not a launch, so it gets a spinner rather than the brand animation.
  if (!isLoaded || (isSignedIn && readyToRoute === null)) {
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: darkTheme ? "#000000" : "#FFFFFF",
        }}
      >
        <ActivityIndicator size="large" color="#2E9BE6" />
      </View>
    );
  }

  if (isSignedIn) {
    if (readyToRoute === "onboarding") return <Redirect href="/(Auth)/Onboarding" />;
    return <Redirect href="/(screens)" />;
  }
  return <Redirect href="/(Auth)/sign-in/screen" />;
}
