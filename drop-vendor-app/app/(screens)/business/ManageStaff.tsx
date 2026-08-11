import React, { useContext, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import {
    ActivityIndicator,
    KeyboardAvoidingView,
    Platform,
    ScrollView,
    Switch,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { BRAND } from "@/constants/brandColors";
import { errorMessage } from "@/API/errors";
import { useVendorProfile } from "@/hooks/queries/useVendorProfile";
import {
    useInviteStaff,
    useRevokeStaff,
    useUpdateStaffPermissions,
    useVendorStaff,
    type StaffMember,
    type StaffPermission,
} from "@/hooks/queries/useVendorStaff";

/**
 * Who may operate this store, and what they may do here.
 *
 * The previous version of this screen was a single email box and an "Assign
 * Staff" button, over a single `Vendor.staff_clerk_id` column. There was no
 * list — an owner could not see who they had given access to — adding a second
 * person silently replaced the first, and access was all-or-nothing: handing
 * someone the till handed them the catalogue and the wallet balance too.
 */
export default function ManageStaff() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const { data: vendorProfile } = useVendorProfile();

    const isOwner = vendorProfile?.role === "owner";
    // The server refuses staff on every route this screen calls; the redirect is
    // so they are not left looking at permanent 403s.
    React.useEffect(() => {
        if (vendorProfile && !isOwner) {
            Toast.error("Access Denied", "Only the store owner can manage staff.");
            router.replace("/(screens)");
        }
    }, [vendorProfile, isOwner, router]);

    const { data, isLoading, isError, error, refetch } = useVendorStaff(isOwner);
    const invite = useInviteStaff();
    const updatePermissions = useUpdateStaffPermissions();
    const revoke = useRevokeStaff();

    const [email, setEmail] = useState("");
    const [isFocused, setIsFocused] = useState(false);
    // Chosen before sending, so the owner grants deliberately rather than
    // discovering afterwards what the default handed over.
    const [pendingPermissions, setPendingPermissions] = useState<string[] | null>(null);

    const staff = data?.staff ?? [];
    const available: StaffPermission[] = data?.available_permissions ?? [];
    const defaults = available.map((p) => p.key).filter((k) => k !== "view_finances");
    const selected = pendingPermissions ?? defaults;

    const togglePending = (key: string) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        setPendingPermissions(
            selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]
        );
    };

    const handleInvite = async () => {
        const trimmed = email.trim();
        if (!trimmed || !trimmed.includes("@")) {
            Toast.error("Invalid Input", "Please enter a valid email address.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return;
        }

        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            const result = await invite.mutateAsync({ email: trimmed, permissions: selected });
            // The reply is deliberately identical whether or not the address has
            // a Drop account — otherwise this screen would let any vendor test
            // whether an arbitrary email is registered here. So the server's own
            // sentence is shown, rather than a claim this screen cannot make.
            Toast.success(
                result.updated_existing ? "Access updated" : "Invitation sent",
                result.message
            );
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            setEmail("");
            setPendingPermissions(null);
        } catch (e) {
            Toast.error("Couldn't add them", errorMessage(e, "Please try again."));
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        }
    };

    const handleToggleMemberPermission = async (member: StaffMember, key: string) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        const next = member.permissions.includes(key)
            ? member.permissions.filter((p) => p !== key)
            : [...member.permissions, key];
        try {
            await updatePermissions.mutateAsync({ staffId: member.id, permissions: next });
        } catch (e) {
            Toast.error("Couldn't save", errorMessage(e, "That change didn't stick."));
        }
    };

    const handleRevoke = (member: StaffMember) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        Popup.show({
            title: "Remove access",
            message: `${member.email} will no longer be able to open this store. Orders they already handled stay on record.`,
            cancelText: "Cancel",
            confirmText: "Remove",
            isDestructive: true,
            onConfirm: async () => {
                Popup.hide();
                try {
                    await revoke.mutateAsync(member.id);
                    Toast.success("Removed", "Their access to this store has ended.");
                    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
                } catch (e) {
                    Toast.error("Couldn't remove", errorMessage(e, "Please try again."));
                }
            },
        });
    };

    const cardStyle = darkTheme
        ? { shadowColor: "#000", shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 }
        : { shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <Stack.Screen options={{ headerShown: false }} />
            <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} className="flex-1">
                <View style={{ overflow: "hidden", paddingBottom: 4 }}>
                    <View
                        className="flex-row items-center px-4 py-3 pb-4 mb-2"
                        style={{
                            backgroundColor: darkTheme ? "#000" : "#fff",
                            borderBottomWidth: 1,
                            borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                            ...cardStyle,
                        }}
                    >
                        <PressableScale onPress={() => router.back()} className="mr-4">
                            <BackButtonMinimal />
                        </PressableScale>
                        <Text className={`text-xl font-sans-bold flex-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                            Manage Staff
                        </Text>
                    </View>
                </View>

                <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 120 }}>
                    {/* ── Current staff ─────────────────────────────────── */}
                    <Text className={`font-sans-bold text-lg mb-3 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                        People with access
                    </Text>

                    {isLoading ? (
                        <View className="py-10 items-center">
                            <ActivityIndicator color={BRAND.primary} />
                        </View>
                    ) : isError ? (
                        <View className={`p-5 rounded-2xl mb-6 ${darkTheme ? "bg-surface-container" : "bg-white border border-gray-100"}`}>
                            <Text className={`mb-3 ${darkTheme ? "text-slate-300" : "text-slate-600"}`}>
                                {errorMessage(error, "Couldn't load your staff list.")}
                            </Text>
                            <PressableScale onPress={() => refetch()} className="bg-accentbg px-5 py-2.5 rounded-xl self-start">
                                <Text className="text-white font-sans-bold">Try again</Text>
                            </PressableScale>
                        </View>
                    ) : staff.length === 0 ? (
                        <View
                            className={`p-6 rounded-2xl mb-6 items-center ${darkTheme ? "bg-surface-container" : "bg-white border border-gray-100"}`}
                            style={cardStyle}
                        >
                            <Ionicons name="people-outline" size={36} color={darkTheme ? BRAND.gray500 : BRAND.gray400} />
                            <Text className={`mt-3 font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                                Just you, for now
                            </Text>
                            <Text className={`mt-1 text-center text-sm ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                                Add someone below to let them run the shop floor without handing over your account.
                            </Text>
                        </View>
                    ) : (
                        staff.map((member) => (
                            <View
                                key={member.id}
                                className={`p-5 rounded-[20px] mb-3 border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
                                style={cardStyle}
                            >
                                <View className="flex-row items-center justify-between mb-1">
                                    <View className="flex-1 mr-3">
                                        <Text numberOfLines={1} className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-slate-900"}`}>
                                            {member.name || member.email}
                                        </Text>
                                        {member.name ? (
                                            <Text numberOfLines={1} className={`text-xs mt-0.5 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                                                {member.email}
                                            </Text>
                                        ) : null}
                                    </View>
                                    <PressableScale accessibilityLabel={`Remove ${member.name || member.email} from this store`}
                                        onPress={() => handleRevoke(member)}
                                        className={`w-10 h-10 rounded-full items-center justify-center ${darkTheme ? "bg-red-900/20" : "bg-red-50"}`}
                                    >
                                        <Ionicons name="person-remove-outline" size={18} color="#ef4444" />
                                    </PressableScale>
                                </View>

                                {/* An invitation that has not been taken up is not
                                    the same as access, and the owner should not be
                                    left wondering why nothing happened. */}
                                {member.is_pending && (
                                    <View className={`self-start px-2.5 py-1 rounded-md mb-3 ${darkTheme ? "bg-amber-500/15" : "bg-amber-50"}`}>
                                        <Text className="text-amber-600 text-[10px] font-sans-bold uppercase tracking-wider">
                                            Waiting for them to sign in
                                        </Text>
                                    </View>
                                )}

                                <View className={`h-px my-2 ${darkTheme ? "bg-white/10" : "bg-slate-100"}`} />

                                {available.map((permission) => (
                                    <View key={permission.key} className="flex-row items-center justify-between py-1.5">
                                        <Text className={`flex-1 text-sm mr-3 ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
                                            {permission.label}
                                        </Text>
                                        <Switch
                                            value={member.permissions.includes(permission.key)}
                                            onValueChange={() => handleToggleMemberPermission(member, permission.key)}
                                            trackColor={{ false: darkTheme ? "#333" : "#e2e8f0", true: BRAND.primary }}
                                            thumbColor="#fff"
                                            style={{ transform: [{ scaleX: 0.8 }, { scaleY: 0.8 }] }}
                                        />
                                    </View>
                                ))}
                            </View>
                        ))
                    )}

                    {/* ── Add someone ───────────────────────────────────── */}
                    <View
                        className={`p-5 rounded-[20px] mt-6 border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
                        style={cardStyle}
                    >
                        <Text className={`font-sans-bold text-lg mb-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                            Add someone
                        </Text>
                        <Text className={`text-xs mb-4 leading-5 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                            They keep their own Drop account and sign in as themselves — you are not sharing your login. Only you can change the store&apos;s details, its payout account, or withdraw money.
                        </Text>

                        <View className={`flex-row items-center px-4 h-[55px] rounded-2xl border-2 ${isFocused ? "border-green-500 bg-green-500/5" : darkTheme ? "bg-black border-gray-800" : "bg-white border-gray-200"}`}>
                            <View className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-white/10" : "bg-green-100"}`}>
                                <Ionicons name="mail-outline" size={16} color={BRAND.primary} />
                            </View>
                            <TextInput
                                value={email}
                                onChangeText={setEmail}
                                onFocus={() => {
                                    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                    setIsFocused(true);
                                }}
                                onBlur={() => setIsFocused(false)}
                                className={`flex-1 ml-3 text-base font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}
                                placeholder="assistant@example.com"
                                placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                                autoCapitalize="none"
                                keyboardType="email-address"
                                autoCorrect={false}
                            />
                        </View>

                        <Text className={`font-sans-semibold text-sm mt-5 mb-1 ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
                            What they can do
                        </Text>
                        {available.map((permission) => (
                            <View key={permission.key} className="flex-row items-center justify-between py-1.5">
                                <Text className={`flex-1 text-sm mr-3 ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
                                    {permission.label}
                                </Text>
                                <Switch
                                    value={selected.includes(permission.key)}
                                    onValueChange={() => togglePending(permission.key)}
                                    trackColor={{ false: darkTheme ? "#333" : "#e2e8f0", true: BRAND.primary }}
                                    thumbColor="#fff"
                                    style={{ transform: [{ scaleX: 0.8 }, { scaleY: 0.8 }] }}
                                />
                            </View>
                        ))}

                        <PressableScale activeOpacity={0.8} onPress={handleInvite} disabled={invite.isPending || !email.trim()}>
                            <View className={`mt-5 py-4 rounded-2xl items-center ${invite.isPending || !email.trim() ? "bg-accentbg/50" : "bg-accentbg"}`}>
                                {invite.isPending ? (
                                    <ActivityIndicator color="#fff" />
                                ) : (
                                    <Text className="text-white text-lg font-sans-bold">Send invitation</Text>
                                )}
                            </View>
                        </PressableScale>

                        <Text className={`mt-3 text-xs text-center leading-5 ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                            If they don&apos;t have a Drop account yet, the invitation waits for them — access starts the moment they sign in with that email.
                        </Text>
                    </View>
                </ScrollView>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}
