import React, { useContext, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, ScrollView, ActivityIndicator } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import Animated, { useAnimatedStyle, withSpring } from 'react-native-reanimated';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { useUserDetails, useUpdateUser } from "@/hooks/queries/useUser";
import { useUser } from "@clerk/clerk-expo";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";
import { InputFieldProps } from "@/types/components";

/**
 * A labelled text field.
 *
 * Declared here, at module scope, and **not** inside `PersonalDetails` — that is
 * the whole point of it being here rather than three lines from where it is used.
 *
 * React reconciles by component *type*. A function defined in a render body is a
 * new function object on every render, so it is a new type every time, so React
 * unmounts the previous subtree and mounts a fresh one instead of updating it.
 * For a `TextInput` that means the native view is destroyed and recreated on
 * every keystroke: the field loses focus, the keyboard closes, and the caret
 * jumps to the end. Typing "Wanjiru" required tapping the field seven times.
 *
 * It looks correct, it type-checks, and it is invisible until somebody types
 * more than one character — which nobody does while building the screen.
 */
const InputField = ({
    label,
    value,
    onChangeText = () => {},
    keyboardType = "default",
    editable = true,
    maxLength,
    darkTheme,
}: InputFieldProps & { darkTheme: boolean }) => (
    <View className="mb-5">
        <Text className={`font-sans-semibold mb-2 text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
            {label}
        </Text>
        <View className={`px-4 py-3 rounded-2xl border ${darkTheme ? "bg-gray-900 border-gray-800" : "bg-white border-gray-200"} ${!editable ? "opacity-50" : ""}`}>
            <TextInput
                value={value}
                onChangeText={onChangeText}
                keyboardType={keyboardType}
                editable={editable}
                maxLength={maxLength}
                className={`text-base ${darkTheme ? "text-white" : "text-black"}`}
                placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
            />
        </View>
        {!editable && <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>Managed by your login provider</Text>}
    </View>
);

export default function PersonalDetails() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const { data: User } = useUserDetails();
    const { user } = useUser();
    const updateUserMutation = useUpdateUser();

    const [name, setName] = useState(User?.full_name || user?.fullName || "");
    const [phone, setPhone] = useState(User?.phone_number || "");
    const [floor, setFloor] = useState(User?.floor_level || 0);
    const [hasElevator, setHasElevator] = useState(User?.has_elevator || false);
    const [isSaving, setIsSaving] = useState(false);

    /**
     * Seed the form once the profile actually arrives.
     *
     * `useState(User?.full_name || "")` reads the query on the *first* render and
     * never again — that is what an initialiser is. On a warm cache the profile is
     * already there and the screen looks right, which is why this survived; on a
     * cold one (first install, or after `useSessionCleanup` wipes the persister on
     * sign-out) the query is still in flight, every field seeds empty, and nothing
     * fills them in when it resolves.
     *
     * The screen then shows a customer with saved details a set of blank boxes, and
     * saving from that state writes the blanks back: `phone_number` to null,
     * `floor_level` to 0, `has_elevator` to false. The floor and the lift are what
     * the rider reads to find the door, so the damage is silent and lands on a
     * delivery days later. `full_name` alone survived, because `handleSave` refuses
     * an empty one.
     *
     * Guarded on `!isSaving` so a reply landing mid-save cannot overwrite what the
     * customer is in the middle of typing — the same shape `StoreProfile` and
     * `VehicleDetails` already use.
     */
    React.useEffect(() => {
        if (User && !isSaving) {
            setName(User.full_name || user?.fullName || "");
            setPhone(User.phone_number || "");
            setFloor(User.floor_level || 0);
            setHasElevator(User.has_elevator || false);
        }
    }, [User, user?.fullName, isSaving]);

    const elevatorToggleStyle = useAnimatedStyle(() => {
        return {
            transform: [{ translateX: withSpring(hasElevator ? 24 : 0, { mass: 1, damping: 15, stiffness: 300 }) }]
        };
    }, [hasElevator]);

    const handleSave = async () => {
        if (!name.trim()) {
            Toast.error("Validation Error", "Name cannot be empty.");
            return;
        }
        
        const phoneTrimmed = phone.trim();
        // Regex validates Kenyan formats: 07XX, 01XX, +2547XX, +2541XX or generic E.164 up to 15 digits
        const phoneRegex = /^(\+254|0)[17]\d{8}$|^\+?[1-9]\d{1,14}$/;
        if (phoneTrimmed && !phoneRegex.test(phoneTrimmed)) {
            Toast.error("Invalid Phone", "Please enter a valid phone number.");
            return;
        }

        setIsSaving(true);
        try {
            await updateUserMutation.mutateAsync({
                full_name: name.trim(),
                phone_number: phoneTrimmed || null,
                floor_level: floor,
                has_elevator: hasElevator
            });
            Toast.success("Saved", "Your details have been updated.");
        } catch (error: unknown) {
            Toast.error("Update Failed", (error as Error).message || "Network error.");
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <Stack.Screen options={{ headerShown: false }} />
            <View style={{ overflow: "hidden", paddingBottom: 4 }}>
            <View 
                className="flex-row items-center px-4 py-3 pb-4 mb-2"
                style={{ 
    backgroundColor: darkTheme ? "#000" : "#fff",
    borderBottomWidth: 1, 
    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
}}
            >
                <PressableScale onPress={() => router.back()} className="mr-4">
                    <BackButtonMinimal />
                </PressableScale>
                <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                    Personal Details
                </Text>
            </View>
            </View>
            <ScrollView 
                contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 20, paddingBottom: 120 }}
                keyboardShouldPersistTaps="handled"
            >
                <InputField darkTheme={darkTheme} label="Full Name" value={name} onChangeText={setName} maxLength={50} />
                <InputField darkTheme={darkTheme} label="Email Address" value={User?.email || user?.emailAddresses?.[0]?.emailAddress || ""} onChangeText={() => {}} editable={false} />
                <InputField darkTheme={darkTheme} label="Phone Number" value={phone} onChangeText={setPhone} keyboardType="phone-pad" maxLength={15} />

                {/* ── Address Anti-Fraud Details ── */}
                <Text className={`font-sans-semibold mt-4 mb-4 text-lg ${darkTheme ? "text-white" : "text-black"}`}>Delivery Details</Text>
                
                <InputField darkTheme={darkTheme} label="Floor Level (0 = Ground Floor)" value={String(floor)} onChangeText={(text: string) => setFloor(parseInt(text) || 0)} keyboardType="number-pad" maxLength={3} />
                
                <View className={`flex-row justify-between items-center mb-5 px-4 py-3 rounded-2xl border ${darkTheme ? "bg-gray-900 border-gray-800" : "bg-white border-gray-200"}`}>
                    <Text className={`text-base font-sans-medium ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Has Elevator</Text>
                    <PressableScale onPress={() => setHasElevator(!hasElevator)} className={`w-14 h-8 rounded-full justify-center px-1 ${hasElevator ? "bg-sky-500" : (darkTheme ? "bg-gray-700" : "bg-gray-300")}`}>
                        <Animated.View className="w-6 h-6 rounded-full bg-white" style={elevatorToggleStyle} />
                    </PressableScale>
                </View>

                <PressableScale
                    activeOpacity={0.8}
                    onPress={handleSave}
                    disabled={isSaving}
                >
                    <View className={`mt-4 py-4 rounded-2xl items-center ${isSaving ? "bg-sky-400" : "bg-sky-500"}`}>
                        {isSaving ? (
                            <ActivityIndicator color={BRAND.white} />
                        ) : (
                            <Text className="text-white text-lg font-sans-bold">Save Changes</Text>
                        )}
                    </View>
                </PressableScale>
            </ScrollView>
        </SafeAreaView>
    );
}
