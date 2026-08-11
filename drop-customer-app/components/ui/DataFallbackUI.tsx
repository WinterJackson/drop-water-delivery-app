import React, { useContext } from "react";
import { View } from "react-native";
import { Text } from '@/components/ui/Text';
import { Ionicons } from "@expo/vector-icons";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { PressableScale } from "@/components/ui/PressableScale";
import { useRouter } from "expo-router";

interface DataFallbackUIProps {
    title?: string;
    message?: string;
    onRetry?: () => void;
    showHomeButton?: boolean;
}

export const DataFallbackUI: React.FC<DataFallbackUIProps> = ({
    title = "Data unavailable",
    message = "We couldn't load your data. This usually happens on reload before authentication finishes or due to a network timeout.",
    onRetry,
    showHomeButton = true
}) => {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    return (
        <View className={`flex-1 items-center justify-center px-6 ${darkTheme ? "bg-black" : "bg-white"}`}>
            <Ionicons name="warning" size={48} color={BRAND.primary} />
            <Text className={`text-lg font-sans-bold text-center mt-4 ${darkTheme ? "text-white" : "text-black"}`}>
                {title}
            </Text>
            <Text className={`text-sm text-center mt-2 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                {message}
            </Text>
            
            {onRetry && (
                <PressableScale onPress={onRetry} className="mt-6 bg-accentbg px-6 py-3 rounded-xl min-w-[120px] items-center">
                    <Text className="text-white font-sans-bold">Retry</Text>
                </PressableScale>
            )}
            
            {showHomeButton && (
                <PressableScale onPress={() => router.replace("/")} className="mt-4 p-2">
                    <Text className="text-accentbg font-sans-bold">Go Home</Text>
                </PressableScale>
            )}
        </View>
    );
};
