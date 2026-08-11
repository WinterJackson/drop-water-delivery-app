import React from "react";
import { View, StyleSheet } from "react-native";
import { Text } from '@/components/ui/Text';
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { AVATAR, BRAND } from '@/constants/brandColors';
interface UserAvatarProps {
    profilePicUrl?: string | null;
    fullName?: string | null;
    size?: number;
    style?: any;
    textStyle?: any;
}

const getInitials = (name?: string | null) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
};

const getRandomGradient = (name: string = "default") => {
    // Generate a pseudo-random index based on name so same user gets same color
    const sum = name.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    const gradients = AVATAR.gradients;
    return gradients[sum % gradients.length];
};

export default function UserAvatar({
    profilePicUrl,
    fullName,
    size = 42,
    style,
    textStyle,
}: UserAvatarProps) {
    const radius = size / 2;

    if (profilePicUrl && profilePicUrl.trim() !== "") {
        return (
            <View
                style={[
                    {
                        width: size,
                        height: size,
                        borderRadius: radius,
                        overflow: "hidden",
                        backgroundColor: AVATAR.placeholder, // placeholder background while loading
                    },
                    style,
                ]}
            >
                <Image
                    source={{ uri: profilePicUrl }}
                    style={{ width: "100%", height: "100%" }}
                    contentFit="cover"
                    transition={200}
                />
            </View>
        );
    }

    const initials = getInitials(fullName);
    const colors = getRandomGradient(fullName || "");

    return (
        <LinearGradient
            colors={(colors as unknown) as [string, string, ...string[]]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={[
                {
                    width: size,
                    height: size,
                    borderRadius: radius,
                    justifyContent: "center",
                    alignItems: "center",
                    elevation: 2,
                    shadowColor: BRAND.bgDark,
                    shadowOffset: { width: 0, height: 2 },
                    shadowOpacity: 0.15,
                    shadowRadius: 3,
                },
                style,
            ]}
        >
            <Text
                style={[
                    {
                        color: AVATAR.text,
                        fontSize: size * 0.45,
                        fontFamily: "Karla_700Bold",
                        letterSpacing: 1,
                    },
                    textStyle,
                ]}
            >
                {initials}
            </Text>
        </LinearGradient>
    );
}
