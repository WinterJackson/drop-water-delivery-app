import { useContext, useEffect, useState } from "react";
import { useAuth } from "@clerk/clerk-expo";
import { apiFetch } from "@/API/apiFetch";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { Redirect } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { AnimatedSplash } from "@/components/splash/AnimatedSplash";

export default function Index() {
  const { isSignedIn, isLoaded, getToken } = useAuth();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const [splashDone, setSplashDone] = useState(false);
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


  // Show splash until both animation completes AND Clerk auth resolves
  // We also wait for the profile verification to finish cleanly if they are signed in.
  const canProceed = splashDone && isLoaded;
  const isFullyReady = canProceed && (!isSignedIn || readyToRoute !== null);

  if (!isFullyReady) {
    return (
      <AnimatedSplash
        variant="rider"
        isDark={darkTheme}
        onComplete={() => setSplashDone(true)}
      />
    );
  }

  // EXACT emulation of customer app fallback routing
  if (isSignedIn) {
    if (readyToRoute === "onboarding") return <Redirect href={"/(Auth)/Onboarding" as any} />;
    return <Redirect href={"/(screens)" as any} />;
  } else {
    return <Redirect href={"/(Auth)" as any} />;
  }
}

