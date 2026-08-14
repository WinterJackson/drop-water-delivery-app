import { View } from "react-native";
import { Text, TextInput, type TextInputRef } from '@/components/ui/Text';
import React, { useContext, useEffect, useRef } from "react";
import { Ionicons } from "@expo/vector-icons";
import { UIThemeContext } from "@/context/ThemeContext";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";

type Props = {
	width: string;
	height: string;
	buttonStyle: string;
	setFunc: (value: string) => void;
	/**
	 * The current term. Supplying it makes the field controlled, which is what
	 * lets the clear button — and anything else that resets the search — actually
	 * empty it. Left off, the field keeps its own text as before.
	 */
	value?: string;
	/**
	 * What this box searches. It said "Search for products or vendors" on every
	 * screen it appeared on, including the wallet ledger, where the placeholder
	 * described a different screen's contents.
	 */
	placeholder?: string;
	/**
	 * Whether to take the keyboard on mount. Only true where searching *is* the
	 * screen. It used to be unconditional, so opening Orders, Products or
	 * Transactions threw the keyboard up over the list somebody came to read and
	 * they had to dismiss it before scrolling.
	 */
	autoFocus?: boolean;
	/** Announced by the screen reader; the icon-only clear button gets its own. */
	accessibilityLabel?: string;
};

const SearchBar = ({
	width,
	buttonStyle,
	height,
	setFunc,
	value,
	placeholder = "Search",
	autoFocus = false,
	accessibilityLabel,
}: Props) => {
	const inputRef = useRef<TextInputRef>(null);
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const controlled = value !== undefined;

	useEffect(() => {
		if (!autoFocus) return;
		// The delay is what lets the keyboard animate in with the screen rather
		// than over it mid-transition.
		const timeout = setTimeout(() => inputRef.current?.focus(), 100);
		return () => clearTimeout(timeout);
	}, [autoFocus]);

	const showClear = controlled && value.length > 0;

	return (
		<View
			className={`px-4 flex-row items-center gap-2 flex-1 border ${darkTheme ? "border-transparent bg-gray-200/20" : "bg-white border-gray-200"} rounded-full ${width} ${height}`}
			style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
		>
			<TextInput
				ref={inputRef}
				placeholder={placeholder}
				accessibilityLabel={accessibilityLabel ?? placeholder}
				placeholderTextColor={darkTheme ? BRAND.searchPlaceholderDark : BRAND.searchPlaceholderLight}
				className="flex-1"
				// The *typed* term is foreground text; only the placeholder is muted.
				// Both were `searchPlaceholder*` — 70% opacity — so what somebody had
				// typed rendered in the same grey as the prompt telling them to type,
				// which reads as the field not having taken the input.
				style={{ color: darkTheme ? BRAND.white : BRAND.gray900 }}
				enterKeyHint={"search"}
				autoCorrect={false}
				autoCapitalize="none"
				{...(controlled ? { value } : {})}
				onChangeText={(text) => setFunc(text)}
			/>
			{showClear && (
				<PressableScale
					accessibilityLabel="Clear search"
					hitSlop={12}
					onPress={() => {
						setFunc("");
						inputRef.current?.focus();
					}}
				>
					<Ionicons
						name="close-circle"
						size={18}
						color={darkTheme ? BRAND.searchPlaceholderDark : BRAND.searchPlaceholderLight}
					/>
				</PressableScale>
			)}
		</View>
	);
};

export default SearchBar;
