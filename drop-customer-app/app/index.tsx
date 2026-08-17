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
import { ActivityIndicator, View } from "react-native";

/**
 * Has the launch animation already played in this process?
 *
 * Module scope on purpose: component state resets on remount, and this
 * route is remounted by every redirect to "/". The splash belongs to the
 * app launch, not to one mounting of one screen.
 */
let hasPlayedSplash = false;

export default function Index() {
	const router = useRouter();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const { getToken, isSignedIn, isLoaded } = useAuth();
	const api = useApiRequest();

	// ── State ──
	const [splashComplete, setSplashComplete] = useState(hasPlayedSplash);
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
	//
	// The splash is a *launch* animation, not a loading spinner, and these two
	// cases are deliberately separated because they used to be one.
	//
	// This route is re-entered every time anything redirects to "/", which the
	// sign-in screen does the moment a session is created. `useState(false)`
	// gave the freshly mounted component a fresh `splashComplete`, so the whole
	// SPLASH_DURATION_MS — ten seconds — played again *after* the user had
	// signed in, and only then did routing continue. `hasPlayedSplash` lives at
	// module scope so it survives a remount inside the same process, which is
	// exactly the lifetime "this app has launched" describes.
	if (!splashComplete) {
		return (
			<AnimatedSplash
				variant="customer"
				isDark={darkTheme}
				onComplete={() => {
					hasPlayedSplash = true;
					setSplashComplete(true);
				}}
			/>
		);
	}

	// Splash already shown, but Clerk or the profile check is still resolving.
	// That is a wait, not a launch: it gets a spinner rather than ten more
	// seconds of brand. Previously this branch fell back into <AnimatedSplash>,
	// which is why signing in replayed the animation a second time.
	if (!isLoaded || (isSignedIn && readyToRoute === null)) {
		return (
			<View
				className="flex-1 items-center justify-center"
				style={{ backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }}
			>
				<ActivityIndicator size="large" color={BRAND.primary} />
			</View>
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
		return <Redirect href="/(Auth)/sign-in/screen" />;
	}
}
