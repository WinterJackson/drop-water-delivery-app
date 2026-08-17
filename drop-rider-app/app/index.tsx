import { useContext, useEffect, useState } from "react";
import { useAuth } from "@clerk/clerk-expo";
import { apiFetch } from "@/API/apiFetch";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { Redirect } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { AnimatedSplash } from "@/components/splash/AnimatedSplash";
import { ActivityIndicator, View } from "react-native";

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
  const [isVerifyingProfile, setIsVerifyingProfile] = useState(false);
  const [readyToRoute, setReadyToRoute] = useState<"onboarding" | "main" | null>(null);
  
  // Follow Customer App pattern for fallback
  const fallbackTimeoutMs = 5000;

  useEffect(() => {
    const verifyOnboardingAndProceed = async () => {
      if (!isSignedIn) return;
      setIsVerifyingProfile(true);
      
      try {
        const token = await getToken();
        const data = await apiFetch<{ exists?: boolean; missing_fields?: string[] }>(
          RiderApiRoutes.ProfileStatus.path,
          { token, timeoutMs: fallbackTimeoutMs }
        );
        setReadyToRoute(
          !data.exists || (data.missing_fields && data.missing_fields.length > 0)
            ? "onboarding"
            : "main"
        );
      } catch (e) {
        // Fallback to onboarding if network fails or unregistered
        setReadyToRoute("onboarding");
      } finally {
        setIsVerifyingProfile(false);
      }
    };

    if (splashDone && isLoaded) {
      if (isSignedIn) verifyOnboardingAndProceed();
    }
  }, [splashDone, isLoaded, isSignedIn]);


  // ── Splash gate ──
  //
  // Two cases, deliberately separated because they used to be one condition.
  // This route is re-entered whenever anything redirects to "/", which the
  // sign-in screen does as soon as a session exists — so a single
  // `!isFullyReady` check sent a signed-in rider back into the ten-second
  // launch animation before routing them onward.
  if (!splashDone) {
    return (
      <AnimatedSplash
        variant="rider"
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

  // EXACT emulation of customer app fallback routing
  if (isSignedIn) {
    if (readyToRoute === "onboarding") return <Redirect href={"/(Auth)/Onboarding" as any} />;
    return <Redirect href={"/(screens)" as any} />;
  } else {
    return <Redirect href={"/(Auth)/sign-in/screen" as any} />;
  }
}

