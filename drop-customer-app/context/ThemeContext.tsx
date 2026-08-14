/** F-025 FIX: Converted from JS to TypeScript with proper types */
import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useEffect, useState, ReactNode } from "react";
import { useColorScheme, ColorSchemeName } from "react-native";

interface UIThemeContextType {
  setTheme: () => Promise<void>;
  currentTheme: ColorSchemeName;
}

export const UIThemeContext = createContext<UIThemeContextType>({
  setTheme: async () => {},
  currentTheme: "light",
});

interface Props {
  children: ReactNode;
}

const ThemeContextProvider = ({ children }: Props) => {
  const theme = useColorScheme();
  const [currentTheme, setCurrentTheme] = useState<ColorSchemeName>(theme);
  const [manualOverride, setManualOverride] = useState(false);

  useEffect(() => {
    const _retrieveTheme = async () => {
      try {
        const value = await AsyncStorage.getItem("THEME");
        if (value !== null && (value === "dark" || value === "light")) {
          setCurrentTheme(value as ColorSchemeName);
          setManualOverride(true);
        }
      } catch (error) {
        // Fail open to the system theme: a preference that cannot be read is a
        // preference, not an outage, and throwing here would take the whole app
        // down at mount. Logged rather than swallowed — silently ignoring a
        // failing AsyncStorage read is how "my dark mode keeps resetting" turns
        // into a bug report with nothing behind it.
        if (__DEV__) console.warn("[ThemeContext] could not read the saved theme", error);
      }
    };
    _retrieveTheme();
  }, []);

  const setTheme = async () => {
    try {
      const newTheme = currentTheme === "dark" ? "light" : "dark";
      setCurrentTheme(newTheme);
      setManualOverride(true);
      await AsyncStorage.setItem("THEME", newTheme);
    } catch (error) {
      if (__DEV__) console.error("Theme toggle error:", error);
    }
  };

  useEffect(() => {
    if (!manualOverride && theme) {
      setCurrentTheme(theme);
    }
  }, [theme, manualOverride]);

  return (
    <UIThemeContext.Provider value={{ setTheme, currentTheme }}>
      {children}
    </UIThemeContext.Provider>
  );
};

export default ThemeContextProvider;
