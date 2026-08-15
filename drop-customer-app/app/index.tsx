import React, { useContext, useEffect, useState } from "react";
import { Redirect, useRouter } from "expo-router";
import { useAuth } from "@clerk/clerk-expo";

import { AnimatedSplash } from "@/components/splash/AnimatedSplash";
import { UIThemeContext } from "@/context/ThemeContext";
import { useUpdateLocation } from "@/hooks/queries/useUser";
import { useLocation } from "@/hooks/useLocation";
import { ROUTES } from "@/API/routes/ApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { BRAND, TOAST } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";

export default function Index() {
	const router = useRouter();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const { getToken, isSignedIn, isLoaded } = useAuth();
	const api = useApiRequest();

	// ── State ──
	const [splashComplete, setSplashComplete] = useState(false);
	const [isVerifyingProfile, setIsVerifyingProfile] = useState(false);
	const [readyToRoute, setReadyToRoute] = useState<"onboarding" | "main" | null>(null);

	// ── Location ──
	// Shared store, not a private copy. The local implementation this replaced
	// returned silently when the permission was denied, so it never surfaced a
	// prompt and never obtained coordinates — discovery then had nothing to
	// query with. The store distinguishes "permission denied" (showPrompt) from
	// a transient GPS failure, and the screens render the prompt.
	const { location: deviceLocation, requestLocation } = useLocation();
	const { mutateAsync: mutateLocation } = useUpdateLocation();

	// Fire location + update AFTER splash completes and user is signed in
	useEffect(() => {
		const verifyOnboardingAndProceed = async () => {
			if (!isSignedIn) return;
			setIsVerifyingProfile(true);
			try {
				const data = await api.get<{ exists: boolean; missing_fields?: string[] }>(
					ROUTES.GET_PROFILE_STATUS("customer")
				);
				if (!data.exists || (data.missing_fields && data.missing_fields.length > 0)) {
					setReadyToRoute("onboarding");
				} else {
					setReadyToRoute("main");
				}
			} catch (e) {
				// Network failure - safer to route to onboarding where user creation happens
				setReadyToRoute("onboarding");
			} finally {
				setIsVerifyingProfile(false);
			}
		};

		if (splashComplete && isLoaded) {
			if (isSignedIn) {
				verifyOnboardingAndProceed();
				requestLocation().catch(() => {});
			}
		}
	}, [splashComplete, isLoaded, isSignedIn]);

	// Push fresh coordinates to the backend whenever the store resolves them.
	// Non-blocking: a failure here must never gate routing into the app.
	useEffect(() => {
		if (!deviceLocation) return;
		mutateLocation({
			lat: deviceLocation.coords.latitude,
			lng: deviceLocation.coords.longitude,
		}).catch(() => {});
	}, [deviceLocation]);

	// ── Splash gate ──
	// Show splash until both the animation completes AND Clerk auth resolves.
	// We also wait for the profile verification to finish cleanly if they are signed in.
	const canProceed = splashComplete && isLoaded;
	const isFullyReady = canProceed && (!isSignedIn || readyToRoute !== null);

	if (!isFullyReady) {
		return (
			<AnimatedSplash
				variant="customer"
				isDark={darkTheme}
				onComplete={() => setSplashComplete(true)}
			/>
		);
	}

	// A denied permission is no longer a dead end here: routing continues and the
	// home screen renders the store-driven prompt (Open Settings / retry / set the
	// address by hand), so the user can still reach the app and shop.

	// ── Route to correct destination ──
	if (isSignedIn) {
		if (readyToRoute === "onboarding") return <Redirect href="/(Auth)/Onboarding" />;
		return <Redirect href="/(screens)" />;
	} else {
		return <Redirect href="/(Auth)" />;
	}
}
