import { View, Image } from "react-native";
import { Text, TextInput, type TextInputRef } from '@/components/ui/Text';
import React, { useContext, useEffect, useRef } from "react";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";

type Props = {
	width: string;
	height: string;
	buttonStyle: string;
	setFunc: (value: string) => void;
};

const SearchBar = ({ width, buttonStyle, height, setFunc }: Props) => {
	const inputRef = useRef<TextInputRef>(null);
	const {currentTheme} = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark"

	useEffect(() => {
		const timeout = setTimeout(() => {
			inputRef.current?.focus();
		}, 100); // Delay is sometimes needed to ensure the keyboard opens smoothly

		return () => clearTimeout(timeout);
	}, []);

	return (
		<View
			className={`px-4 flex-1 border ${darkTheme ? "border-transparent bg-gray-200/20" : "bg-white border-gray-200"} rounded-full ${width} ${height}`}
			style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
		>
			<TextInput
				ref={inputRef}
				placeholder="Search for products or vendors"
				placeholderTextColor={darkTheme ? BRAND.searchPlaceholderDark : BRAND.searchPlaceholderLight}
				className="flex-1"
				style={{
					color: darkTheme ? BRAND.searchPlaceholderDark : BRAND.searchPlaceholderLight
				}}
				enterKeyHint={"search"}
				onChangeText={(text) => setFunc(text)}
			/>
		</View>
	);
};

export default SearchBar;
