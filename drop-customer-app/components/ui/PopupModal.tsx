import React, { useContext } from "react";
import { Modal, View, Text, ActivityIndicator } from "react-native";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import * as Haptics from "expo-haptics";
import { usePopupStore } from "@/stores/popupStore";
import { PressableScale } from "@/components/ui/PressableScale";

export default function PopupModal() {
    const { visible, config, isLoading, hide } = usePopupStore();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";

    if (!visible || !config) return null;

    const {
        title,
        message,
        cancelText = "Cancel",
        confirmText = "OK",
        isDestructive = false,
        isAlertOnly = false,
        onCancel,
        onConfirm
    } = config;

    const handleCancel = () => {
        Haptics.selectionAsync();
        if (onCancel) onCancel();
        hide();
    };

    const handleConfirm = () => {
        Haptics.selectionAsync();
        if (onConfirm) onConfirm();
        // Don't auto-hide on confirm if there's an action (the action might set loading and close it itself).
        // If it's just an alert, hide it.
        if (isAlertOnly && !onConfirm) {
            hide();
        }
    };

    return (
        <Modal
            transparent
            animationType="fade"
            visible={visible}
            onRequestClose={handleCancel}
        >
            {/* Background Overlay */}
            <View className="flex-1 justify-center items-center px-6" style={{ backgroundColor: "rgba(0, 0, 0, 0.5)" }}>
                {/* Modal Container */}
                <View 
                    className={`w-full max-w-sm rounded-[24px] p-6 shadow-lg ${darkTheme ? "bg-gray-900 border border-gray-800" : "bg-white"}`}
                >
                    <Text className={`text-xl font-bold mb-3 text-center ${darkTheme ? "text-white" : "text-black"}`}>
                        {title}
                    </Text>
                    
                    <Text className={`text-base mb-6 text-center ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
                        {message}
                    </Text>

                    <View className="flex-row gap-4">
                        {!isAlertOnly && (
                            /* Cancel Button */
                            <PressableScale 
                                disabled={isLoading}
                                onPress={handleCancel} 
                                className={`flex-1 py-3.5 items-center rounded-xl border ${darkTheme ? "border-gray-700 bg-gray-800" : "border-gray-300 bg-white"}`}
                            >
                                <Text className={`font-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}>
                                    {cancelText}
                                </Text>
                            </PressableScale>
                        )}

                        {/* Confirm / OK Button */}
                        <PressableScale 
                            disabled={isLoading}
                            onPress={handleConfirm} 
                            className={`flex-1 py-3.5 items-center rounded-xl ${isDestructive ? "bg-red-500" : ""}`}
                            style={!isDestructive ? { backgroundColor: BRAND.primary } : {}}
                        >
                            {isLoading ? (
                                <ActivityIndicator color={BRAND.white} />
                            ) : (
                                <Text className="text-white font-bold text-lg">
                                    {confirmText}
                                </Text>
                            )}
                        </PressableScale>
                    </View>
                </View>
            </View>
        </Modal>
    );
}
