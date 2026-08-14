import React, { useContext, useState, useEffect } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, ScrollView, ActivityIndicator, KeyboardAvoidingView, Platform, KeyboardTypeOptions } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { useUpdateVendorProfile, useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { errorMessage } from "@/API/errors";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { BRAND } from "@/constants/brandColors";

type PayoutMethod = "MPESA_PHONE" | "MPESA_TILL" | "MPESA_PAYBILL" | "BANK_TRANSFER";

/**
 * A labelled text field on the payout form.
 *
 * Module scope, not the render body of `PayoutSettings`. React reconciles by
 * component *type*, and a function created during render is a new type every
 * render, so the subtree is unmounted and remounted instead of updated — the
 * native `TextInput` is destroyed and rebuilt on every keystroke, losing focus
 * and dismissing the keyboard.
 *
 * This is the screen where a vendor types the account their money is paid into:
 * a till number, a paybill and account, an M-Pesa number, or a bank account
 * number up to twelve digits. Entering twelve digits meant twelve taps back into
 * the field, which is exactly the condition under which somebody gets a digit
 * wrong and does not notice.
 */
const InputBlock = ({
    label,
    value,
    onChange,
    placeholder,
    keyboardType = "default",
    id,
    maxLength,
    darkTheme,
    isFocused,
    handleFocus,
    setIsFocused,
}: any) => (
    <View className="mb-4">
        <Text className={`font-sans-semibold mb-2 text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>{label}</Text>
        <View className={`flex-row items-center px-4 h-[55px] rounded-2xl border-2 ${isFocused === id ? "border-green-500 bg-green-500/5" : (darkTheme ? "bg-black border-gray-800" : "bg-white border-gray-200")}`}>
            <TextInput
                value={value}
                onChangeText={onChange}
                onFocus={() => handleFocus(id)}
                onBlur={() => setIsFocused(null)}
                keyboardType={keyboardType as KeyboardTypeOptions}
                className={`flex-1 text-base font-sans-semibold tracking-wide ${darkTheme ? "text-white" : "text-black"}`}
                placeholder={placeholder}
                placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                maxLength={maxLength}
            />
        </View>
    </View>
);

/**
 * At module scope, not inside the screen.
 *
 * A component declared in a render body is a new function object — and so a new
 * component *type* — on every render, which makes React unmount its subtree and
 * mount a fresh one instead of updating it. Even with no input and no state of
 * its own that is not free: every child is torn down and rebuilt, `PressableScale`
 * restarts its animation, and the reconciler does the most expensive kind of work
 * on the most ordinary re-render.
 *
 * What it closed over is passed in instead.
 */
const MethodTab = ({ method, title, icon, darkTheme, activeMethod, setActiveMethod }: { method: PayoutMethod, title: string, icon: keyof typeof Ionicons.glyphMap } & { darkTheme: boolean; activeMethod: PayoutMethod; setActiveMethod: (m: PayoutMethod) => void }) => {
    const isActive = activeMethod === method;
    return (
        <PressableScale onPress={() => { Haptics.selectionAsync(); setActiveMethod(method); }} className="mr-3">
            <View className={`px-4 py-3 rounded-2xl flex-row items-center border ${isActive ? (darkTheme ? "bg-accentbg/20 border-accentbg" : "bg-accentbg border-accentbg") : (darkTheme ? "bg-slate-800 border-gray-700" : "bg-white border-gray-200")}`}>
                <Ionicons name={icon} size={18} color={isActive ? (darkTheme ? BRAND.primary : "#fff") : (darkTheme ? "#9ca3af" : "#6b7280")} style={{ marginRight: 6 }} />
                <Text className={`font-sans-bold text-sm ${isActive ? (darkTheme ? "text-accenttxt" : "text-white") : (darkTheme ? "text-gray-300" : "text-gray-600")}`}>{title}</Text>
            </View>
        </PressableScale>
    );
};

export default function PayoutSettings() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    // Payout details live on the store profile. The dashboard never returned
    // `preferred_payment_method`, so this screen opened on the default method
    // every time and a save silently replaced whatever was configured.
    const { data: vendorProfile } = useVendorProfile();
    const updateProfile = useUpdateVendorProfile();

    useEffect(() => {
        if (vendorProfile?.role === "staff") {
            Toast.error("Access Denied", "Staff members cannot access payout settings.");
            router.replace("/(screens)");
        }
    }, [vendorProfile]);

    const [activeMethod, setActiveMethod] = useState<PayoutMethod>("MPESA_PHONE");

    // States
    const [phoneNo, setPhoneNo] = useState("");
    const [tillNo, setTillNo] = useState("");
    const [paybillBusinessNo, setPaybillBusinessNo] = useState("");
    const [paybillAccountNo, setPaybillAccountNo] = useState("");
    const [bankName, setBankName] = useState("");
    const [bankAccountNo, setBankAccountNo] = useState("");
    const [bankAccountName, setBankAccountName] = useState("");

    const [isSaving, setIsSaving] = useState(false);
    const [isFocused, setIsFocused] = useState<string | null>(null);

    // Hydration
    useEffect(() => {
        if (vendorProfile?.preferred_payment_method && vendorProfile.preferred_payment_method.length > 0) {
            const prefs = vendorProfile.preferred_payment_method;
            const type = prefs[0] as PayoutMethod;
            setActiveMethod(type);
            if (type === "MPESA_PHONE") setPhoneNo(prefs[1] || "");
            if (type === "MPESA_TILL") setTillNo(prefs[1] || "");
            if (type === "MPESA_PAYBILL") {
                setPaybillBusinessNo(prefs[1] || "");
                setPaybillAccountNo(prefs[2] || "");
            }
            if (type === "BANK_TRANSFER") {
                setBankName(prefs[1] || "");
                setBankAccountNo(prefs[2] || "");
                setBankAccountName(prefs[3] || "");
            }
        }
    }, [vendorProfile]);

    // Validation
    const validate = (): boolean => {
        if (activeMethod === "MPESA_PHONE") return /^254(7|1)\d{8}$/.test(phoneNo);
        if (activeMethod === "MPESA_TILL") return /^\d{5,8}$/.test(tillNo);
        if (activeMethod === "MPESA_PAYBILL") return /^\d{5,7}$/.test(paybillBusinessNo) && paybillAccountNo.trim().length > 0;
        if (activeMethod === "BANK_TRANSFER") return bankName.trim().length > 0 && bankAccountNo.trim().length > 5 && bankAccountName.trim().length > 0;
        return false;
    };
    
    const isValid = validate();

    const handleFocus = (id: string) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        setIsFocused(id);
    };

    const handlePhoneChange = (text: string) => {
        let cleaned = text.replace(/[^0-9]/g, '');
        if (cleaned.startsWith('0')) cleaned = '254' + cleaned.substring(1);
        else if (cleaned.length > 0 && !cleaned.startsWith('2') && (cleaned.startsWith('7') || cleaned.startsWith('1'))) cleaned = '254' + cleaned;
        setPhoneNo(cleaned.substring(0, 12));
    };

    const handleSave = async () => {
        if (!isValid) {
            Toast.error("Invalid Details", "Please check your payout details and ensure they are correct.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            return;
        }

        setIsSaving(true);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

        try {
            let payloadArr: string[] = [];
            if (activeMethod === "MPESA_PHONE") payloadArr = ["MPESA_PHONE", phoneNo];
            if (activeMethod === "MPESA_TILL") payloadArr = ["MPESA_TILL", tillNo];
            if (activeMethod === "MPESA_PAYBILL") payloadArr = ["MPESA_PAYBILL", paybillBusinessNo, paybillAccountNo.trim()];
            if (activeMethod === "BANK_TRANSFER") payloadArr = ["BANK_TRANSFER", bankName.trim(), bankAccountNo.trim(), bankAccountName.trim()];

            await updateProfile.mutateAsync({ preferred_payment_method: payloadArr });
            Toast.success("Saved", "Payout details updated successfully.");
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            setTimeout(() => router.back(), 500);
        } catch (error) {
            // Owner-only on the server; a staff member gets the `owner_only`
            // sentence rather than a flat "Unable to reach servers".
            Toast.error("Error", errorMessage(error, "Could not update payout instructions."));
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        } finally {
            setIsSaving(false);
        }
    };

    const inputBlockProps = { darkTheme, isFocused, handleFocus, setIsFocused };

    const methodTabProps = { darkTheme, activeMethod, setActiveMethod };

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
                            ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
                        }}
                    >
                        <PressableScale onPress={() => router.back()} className="mr-4">
                            <BackButtonMinimal />
                        </PressableScale>
                        <Text className={`text-xl font-sans-bold flex-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                            Payout Settings
                        </Text>
                    </View>
                </View>

                <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 120 }}>
                    <View className={`p-4 rounded-2xl mb-6 flex-row items-start ${darkTheme ? "bg-slate-800" : "bg-blue-50"}`}>
                        <Ionicons name="information-circle" size={24} color={BRAND.primary} />
                        <View className="flex-1 ml-3">
                            <Text className={`font-sans-bold text-sm mb-1 ${darkTheme ? "text-white" : "text-gray-900"}`}>Automated Settlements</Text>
                            <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-600"} leading-5`}>
                                Drop automatically reconciles and settles your funds to your preferred channel. Select your business payment method below.
                            </Text>
                        </View>
                    </View>

                    <ScrollView horizontal showsHorizontalScrollIndicator={false} className="mb-8" contentContainerStyle={{ paddingRight: 20 }}>
                        <MethodTab {...methodTabProps} method="MPESA_TILL" title="Buy Goods (Till)" icon="storefront-outline" />
                        <MethodTab {...methodTabProps} method="MPESA_PAYBILL" title="Paybill" icon="business-outline" />
                        <MethodTab {...methodTabProps} method="MPESA_PHONE" title="Phone Number" icon="phone-portrait-outline" />
                        <MethodTab {...methodTabProps} method="BANK_TRANSFER" title="Bank Account" icon="card-outline" />
                    </ScrollView>

                    <View className="mb-4">
                        {activeMethod === "MPESA_TILL" && (
                            <>
                                <InputBlock {...inputBlockProps} label="M-Pesa Till Number" value={tillNo} onChange={setTillNo} placeholder="e.g. 123456" keyboardType="number-pad" id="till" maxLength={8} />
                                <Text className={`text-xs mt-1 px-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Funds are sent directly to your Safaricom Buy Goods Till.</Text>
                            </>
                        )}

                        {activeMethod === "MPESA_PAYBILL" && (
                            <>
                                <InputBlock {...inputBlockProps} label="Business Number (Paybill)" value={paybillBusinessNo} onChange={setPaybillBusinessNo} placeholder="e.g. 247247" keyboardType="number-pad" id="paybillBusiness" maxLength={8} />
                                <InputBlock {...inputBlockProps} label="Account Number" value={paybillAccountNo} onChange={setPaybillAccountNo} placeholder="e.g. DropApp" keyboardType="default" id="paybillAccount" />
                                <Text className={`text-xs mt-1 px-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Funds are deposited to this specific Paybill Account.</Text>
                            </>
                        )}

                        {activeMethod === "MPESA_PHONE" && (
                            <>
                                <InputBlock {...inputBlockProps} label="M-Pesa Phone Number" value={phoneNo} onChange={handlePhoneChange} placeholder="e.g. 254712345678" keyboardType="number-pad" id="phone" maxLength={12} />
                                <Text className={`text-xs mt-1 px-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Funds are sent via M-Pesa B2C to this mobile number.</Text>
                            </>
                        )}

                        {activeMethod === "BANK_TRANSFER" && (
                            <>
                                <InputBlock {...inputBlockProps} label="Bank Name" value={bankName} onChange={setBankName} placeholder="e.g. Equity Bank" keyboardType="default" id="bankName" />
                                <InputBlock {...inputBlockProps} label="Account Name" value={bankAccountName} onChange={setBankAccountName} placeholder="e.g. Aqua Drop Ltd" keyboardType="default" id="bankAcctName" />
                                <InputBlock {...inputBlockProps} label="Account Number" value={bankAccountNo} onChange={setBankAccountNo} placeholder="e.g. 123456789012" keyboardType="number-pad" id="bankAcctNo" />
                                <Text className={`text-xs mt-1 px-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Bank transfers may take 1-2 business days to clear via EFT/RTGS.</Text>
                            </>
                        )}
                    </View>

                    <PressableScale activeOpacity={0.8} onPress={handleSave} disabled={isSaving || !isValid}>
                        <View className={`mt-6 py-4 rounded-2xl items-center ${isSaving || !isValid ? "bg-accentbg/50" : "bg-accentbg"}`}>
                            {isSaving ? (
                                <ActivityIndicator color={BRAND.white} />
                            ) : (
                                <Text className="text-white text-lg font-sans-bold">Save Payout Details</Text>
                            )}
                        </View>
                    </PressableScale>
                </ScrollView>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}
