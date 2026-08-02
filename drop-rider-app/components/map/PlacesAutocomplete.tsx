/**
 * PlacesAutocomplete — A lightweight, RN-compatible Google Places Autocomplete
 * replacement. Uses `fetch` instead of XMLHttpRequest to avoid the
 * `sendRequest` argument 7 crash on modern React Native / Expo SDK 54+.
 * No `uuid` dependency — avoids `crypto.getRandomValues()` errors.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
	ActivityIndicator,
	FlatList,
	Keyboard,
	Pressable,
	StyleSheet,
	Text,
	TextInput,
	View,
	type TextStyle,
	type ViewStyle,
} from "react-native";
import { Toast } from "@/lib/toast";
import { useAuth } from "@clerk/clerk-expo";
import { apiFetch } from "@/API/apiFetch";
import { ApiError } from "@/API/errors";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { BRAND } from "@/constants/brandColors";

/**
 * Opaque per-search token. Google bills the keystrokes plus the one Details
 * call as a single session when they share one, instead of charging each
 * keystroke separately.
 *
 * Deliberately not `uuid`/`crypto.getRandomValues` — those throw on React
 * Native without a polyfill, which is what the original component was working
 * around. Collision resistance is irrelevant here: the token only has to be
 * unique per in-flight search on one device.
 */
const makeSessionToken = () =>
	`${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;

/** "country:ke" (the Google Places `components` syntax) -> "ke". */
const countryFromComponents = (components?: string): string | null => {
	const match = /country:([a-zA-Z]{2})/.exec(components ?? "");
	return match ? match[1].toLowerCase() : null;
};

const AUTOCOMPLETE_URL = RiderApiRoutes.PlacesAutocomplete.path;
const DETAILS_URL = RiderApiRoutes.PlaceDetails.path;

// ────────────────────────────────────────────────────────────
// Types
// ────────────────────────────────────────────────────────────
interface PlacePrediction {
	place_id: string;
	description: string;
	structured_formatting?: {
		main_text: string;
		secondary_text: string;
	};
}

interface PlaceDetails {
	geometry: {
		location: { lat: number; lng: number };
	};
	formatted_address?: string;
	name?: string;
}

interface PlacesAutocompleteProps {
	/** Google Maps API key */
	/** Placeholder text for the input */
	placeholder?: string;
	/** Called when the user selects a place */
	onPress: (data: PlacePrediction, details: PlaceDetails | null) => void;
	/** ISO language code */
	language?: string;
	/** Restrict results to a country (e.g. "country:ke") */
	components?: string;
	/** Whether to fetch full Place Details on selection */
	fetchDetails?: boolean;
	/** Minimum characters before triggering search */
	minLength?: number;
	/** Debounce delay in ms */
	debounce?: number;
	/** Dark theme flag for styling */
	darkTheme?: boolean;
	/** Custom styles */
	customStyles?: {
		container?: ViewStyle;
		textInput?: TextStyle;
		listView?: ViewStyle;
		row?: ViewStyle;
		description?: TextStyle;
		separator?: ViewStyle;
	};
	/** Custom placeholder text color */
	placeholderTextColor?: string;
}

// ────────────────────────────────────────────────────────────
// Component
// ────────────────────────────────────────────────────────────
export default function PlacesAutocomplete({
	placeholder = "Search for a location...",
	onPress,
	language = "en",
	components = "",
	fetchDetails = true,
	minLength = 2,
	debounce: debounceMs = 300,
	darkTheme = false,
	customStyles = {},
	placeholderTextColor,
}: PlacesAutocompleteProps) {
	const [text, setText] = useState("");
	const [predictions, setPredictions] = useState<PlacePrediction[]>([]);
	const [showList, setShowList] = useState(false);
	const [loading, setLoading] = useState(false);
	const { getToken } = useAuth();
	const sessionToken = useRef(makeSessionToken());
	const abortRef = useRef<AbortController | null>(null);
	const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

	// Cleanup on unmount
	useEffect(() => {
		return () => {
			abortRef.current?.abort();
			if (debounceTimer.current) clearTimeout(debounceTimer.current);
		};
	}, []);

	// ── Autocomplete search ──────────────────────────────────
	const fetchPredictions = useCallback(
		async (input: string) => {
			if (!input || input.length < minLength) {
				setPredictions([]);
				setShowList(false);
				return;
			}

			// Abort any in-flight request
			abortRef.current?.abort();
			const controller = new AbortController();
			abortRef.current = controller;

			setLoading(true);

			try {
				const token = await getToken();
				if (!token) {
					setPredictions([]);
					setShowList(false);
					return;
				}

				const params = new URLSearchParams({
					input,
					session_token: sessionToken.current,
				});
				const country = countryFromComponents(components);
				if (country) params.append("country", country);

				let payload: { predictions?: PlacePrediction[] };
				try {
					payload = await apiFetch<{ predictions?: PlacePrediction[] }>(
						`${AUTOCOMPLETE_URL}?${params.toString()}`,
						{ token, signal: controller.signal }
					);
				} catch (err) {
					// 503 means the server has no Maps key, or Google has cut us
					// off for quota — both are operator problems the user cannot
					// act on, so say something true and short rather than nothing.
					if (err instanceof ApiError && err.status === 503) {
						Toast.error("Search unavailable", "Address search is temporarily unavailable. Enter your location on the map instead.");
					}
					setPredictions([]);
					setShowList(false);
					return;
				}

				const results: PlacePrediction[] = payload?.predictions ?? [];
				setPredictions(results);
				setShowList(results.length > 0);
			} catch (e: unknown) {
				if (__DEV__ && (e as Error).name !== "AbortError") {
					console.warn("PlacesAutocomplete: prediction fetch failed", e);
				}
			} finally {
				setLoading(false);
			}
		},
		[getToken, components, minLength]
	);

	// ── Debounced input handler ──────────────────────────────
	const handleChangeText = useCallback(
		(value: string) => {
			setText(value);
			if (debounceTimer.current) clearTimeout(debounceTimer.current);
			debounceTimer.current = setTimeout(() => {
				fetchPredictions(value);
			}, debounceMs);
		},
		[debounceMs, fetchPredictions]
	);

	// ── Fetch Place Details ──────────────────────────────────
	const fetchPlaceDetails = useCallback(
		async (placeId: string): Promise<PlaceDetails | null> => {
			try {
				const token = await getToken();
				if (!token) return null;

				const params = new URLSearchParams({
					place_id: placeId,
					session_token: sessionToken.current,
				});

				const details = await apiFetch<PlaceDetails>(
					`${DETAILS_URL}?${params.toString()}`,
					{ token }
				);

				// The session ends when a prediction is resolved. Rotating here is
				// what makes Google bill the whole search as one session instead
				// of one charge per keystroke.
				sessionToken.current = makeSessionToken();

				return details;
			} catch (e) {
				if (__DEV__) console.warn("PlacesAutocomplete: details fetch failed", e);
				return null;
			}
		},
		[getToken]
	);

	// ── Row press handler ────────────────────────────────────
	const handleSelect = useCallback(
		async (item: PlacePrediction) => {
			Keyboard.dismiss();
			setText(item.description);
			setShowList(false);
			setPredictions([]);

			if (fetchDetails) {
				const details = await fetchPlaceDetails(item.place_id);
				onPress(item, details);
			} else {
				onPress(item, null);
			}
		},
		[fetchDetails, fetchPlaceDetails, onPress]
	);

	// ── Styles ───────────────────────────────────────────────
	const defaultDark = darkTheme;
	const containerStyle: ViewStyle = {
		flex: 0,
		zIndex: 999,
		...customStyles.container,
	};
	const textInputStyle: TextStyle = {
		height: 48,
		borderRadius: 14,
		paddingHorizontal: 16,
		fontSize: 15,
		fontWeight: "600",
		backgroundColor: defaultDark ? "#1a1a1a" : "#fff",
		color: defaultDark ? "#fff" : "#000",
		borderWidth: 1,
		borderColor: defaultDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.08)",
		...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }),
		...customStyles.textInput,
	};
	const listViewStyle: ViewStyle = {
		position: "absolute",
		top: 52, // 48 (input) + 4 (margin)
		left: 0,
		right: 0,
		zIndex: 1000,
		borderRadius: 14,
		backgroundColor: defaultDark ? "#201f1f" : "#ffffff",
		borderWidth: 1,
		borderColor: defaultDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.1)",
		...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }),
		maxHeight: 220,
		...customStyles.listView,
	};
	const rowStyle: ViewStyle = {
		backgroundColor: defaultDark ? "#201f1f" : "#ffffff",
		padding: 16,
		...customStyles.row,
	};
	const descriptionStyle: TextStyle = {
		color: defaultDark ? "#ffffff" : "#000000",
		fontSize: 15,
		fontWeight: "500",
		...customStyles.description,
	};
	const separatorStyle: ViewStyle = {
		height: StyleSheet.hairlineWidth,
		backgroundColor: defaultDark
			? "rgba(255,255,255,0.05)"
			: "rgba(0,0,0,0.05)",
		...customStyles.separator,
	};

	return (
		<View style={containerStyle}>
			<TextInput
				value={text}
				onChangeText={handleChangeText}
				placeholder={placeholder}
				placeholderTextColor={
					placeholderTextColor || (defaultDark ? "#6b7280" : "#9ca3af")
				}
				onFocus={() => {
					if (predictions.length > 0) setShowList(true);
				}}
				style={textInputStyle}
				returnKeyType="search"
				autoCorrect={false}
				onSubmitEditing={() => {
					if (predictions.length > 0) {
						handleSelect(predictions[0]);
					}
				}}
			/>

			{loading && (
				<View style={{ position: "absolute", right: 16, top: 14 }}>
					<ActivityIndicator size="small" color={defaultDark ? BRAND.white : BRAND.gray500} />
				</View>
			)}

			{showList && predictions.length > 0 && (
				<FlatList
					data={predictions}
					keyExtractor={(item) => item.place_id}
					style={listViewStyle}
					keyboardShouldPersistTaps="always"
					ItemSeparatorComponent={() => <View style={separatorStyle} />}
					renderItem={({ item }) => (
						<Pressable
							onPress={() => handleSelect(item)}
							style={({ pressed }) => [
								rowStyle,
								pressed && { opacity: 0.7 },
							]}
						>
							<Text style={descriptionStyle} numberOfLines={2}>
								{item.description}
							</Text>
						</Pressable>
					)}
				/>
			)}
		</View>
	);
}
