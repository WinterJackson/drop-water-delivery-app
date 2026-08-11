import React, { useContext, useState } from "react";
import { View, Modal, TouchableOpacity, FlatList, Platform } from "react-native";
import { Text } from '@/components/ui/Text';
import { UIThemeContext } from "@/context/ThemeContext";
import { Ionicons } from "@expo/vector-icons";
import PressableScale from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";

interface Option {
    label: string;
    value: string;
    icon: string;
}

const VEHICLE_OPTIONS: Option[] = [
    { label: "Motorbike", value: "motorbike", icon: "bicycle-outline" },
    { label: "TukTuk", value: "tuktuk", icon: "car-sport-outline" },
    { label: "Truck", value: "truck", icon: "bus-outline" },
];

interface VehicleDropdownProps {
    value: string;
    onValueChange: (value: string) => void;
    label?: string;
    placeholder?: string;
    containerStyle?: any;
    buttonStyle?: any;
}

const VehicleDropdown: React.FC<VehicleDropdownProps> = ({ 
    value, 
    onValueChange, 
    label, 
    placeholder = "Select Vehicle Type",
    containerStyle,
    buttonStyle
}) => {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const [modalVisible, setModalVisible] = useState(false);

    const selectedOption = VEHICLE_OPTIONS.find(opt => opt.value === value);

    const renderItem = ({ item }: { item: Option }) => {
        const isSelected = item.value === value;
        return (
            <TouchableOpacity 
                className={`flex-row items-center px-5 py-4 border-b ${darkTheme ? "border-white/10" : "border-gray-100"} ${isSelected ? (darkTheme ? "bg-white/5" : "bg-primary/5") : ""}`}
                onPress={() => {
                    onValueChange(item.value);
                    setModalVisible(false);
                }}
                activeOpacity={0.7}
            >
                <View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${darkTheme ? "bg-white/10" : "bg-gray-100"}`}>
                    <Ionicons name={item.icon as any} size={20} color={BRAND.primary} />
                </View>
                <Text className={`text-lg font-sans-semibold flex-1 ${darkTheme ? "text-white" : "text-gray-900"}`}>
                    {item.label}
                </Text>
                {isSelected && (
                    <Ionicons name="checkmark-circle" size={24} color={BRAND.primary} />
                )}
            </TouchableOpacity>
        );
    };

    return (
        <View className={containerStyle ? "" : "mb-4 w-[90%] max-w-[350px]"} style={containerStyle}>
            {label && (
                <Text className={`font-sans-semibold mb-2 ml-2 text-base ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                    {label}
                </Text>
            )}
            
            <PressableScale 
                activeOpacity={0.8}
                onPress={() => setModalVisible(true)}
                className={`flex-row items-center border ${darkTheme ? "border-gray-100/20 bg-gray-200/20" : "border-gray-500 bg-gray-100"} ${buttonStyle ? "" : "rounded-full h-[50px] px-5"}`}
                style={buttonStyle}
            >
                {selectedOption ? (
                    <>
                        <Ionicons name={selectedOption.icon as any} size={20} color={BRAND.primary} style={{ marginRight: 10 }} />
                        <Text className={`flex-1 font-sans-semibold ${darkTheme ? "text-white" : "text-gray-900"}`}>
                            {selectedOption.label}
                        </Text>
                    </>
                ) : (
                    <Text 
                        className="flex-1"
                        style={{ color: darkTheme ? BRAND.searchPlaceholderDark : BRAND.gray500 }}
                    >
                        {placeholder}
                    </Text>
                )}
                <Ionicons name="chevron-down" size={20} color={BRAND.primary} />
            </PressableScale>

            <Modal
                visible={modalVisible}
                transparent={true}
                animationType="fade"
                onRequestClose={() => setModalVisible(false)}
            >
                <TouchableOpacity 
                    className="flex-1 justify-end bg-black/50" 
                    activeOpacity={1}
                    onPress={() => setModalVisible(false)}
                >
                    <View className={`w-full max-h-[50%] rounded-t-3xl pt-2 pb-6 ${darkTheme ? "bg-black" : "bg-white"}`}>
                        <View className="items-center mb-4">
                            <View className={`w-12 h-1.5 rounded-full mt-2 ${darkTheme ? "bg-gray-800" : "bg-gray-300"}`} />
                        </View>
                        <Text className={`text-xl font-sans-bold px-5 mb-4 ${darkTheme ? "text-white" : "text-gray-900"}`}>
                            Select Vehicle Type
                        </Text>
                        <FlatList
                            data={VEHICLE_OPTIONS}
                            keyExtractor={item => item.value}
                            renderItem={renderItem}
                            showsVerticalScrollIndicator={false}
                        />
                    </View>
                </TouchableOpacity>
            </Modal>
        </View>
    );
};

export default VehicleDropdown;
