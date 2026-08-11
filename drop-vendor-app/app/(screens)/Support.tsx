import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { EmptyState } from "@/components/ui/EmptyState";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { errorMessage } from "@/API/errors";
import {
    useCreateSupportTicket,
    useSupportCategories,
    useSupportTickets,
    type SupportTicketSummary,
} from "@/hooks/queries/useSupport";
import { Toast } from "@/lib/toast";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useContext, useState } from "react";
import {
    ActivityIndicator,
    KeyboardAvoidingView,
    Modal,
    Platform,
    RefreshControl,
    ScrollView,
    TouchableOpacity,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";

/**
 * Help & support — where a store writes into the admin console's queue.
 *
 * Scoped to the **active store**, like every other vendor screen: the API client
 * sends `X-Store-Id`, so an owner with two branches raises the ticket against
 * the one they are looking at. Staff can raise one too — they are the people on
 * the shop floor when something goes wrong.
 *
 * The account is the token's, not this screen's. Nothing here can file against
 * another store.
 */

const CATEGORY_LABELS: Record<string, string> = {
    order: "An order",
    payment: "Payouts or commission",
    delivery: "A rider or a delivery",
    bottles: "Bottles and reconciliation",
    account: "This store's account",
    app: "The app itself",
    other: "Something else",
};

const STATUS_TONE: Record<string, { light: string; dark: string; label: string }> = {
    open: { light: "bg-amber-100 text-amber-700", dark: "bg-amber-900/40 text-amber-300", label: "Waiting for us" },
    pending: { light: "bg-blue-100 text-blue-700", dark: "bg-blue-900/40 text-blue-300", label: "We replied" },
    resolved: { light: "bg-green-100 text-green-700", dark: "bg-green-900/40 text-green-300", label: "Resolved" },
    closed: { light: "bg-gray-200 text-gray-600", dark: "bg-gray-800 text-gray-400", label: "Closed" },
};

const MIN_SUBJECT = 3;
const MIN_BODY = 10;

const Support = () => {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: tickets = [], isLoading, refetch, isRefetching, isError, error } = useSupportTickets();
    const { data: categories = [] } = useSupportCategories();
    const { mutateAsync: createTicket, isPending } = useCreateSupportTicket();

    const [composing, setComposing] = useState(false);
    const [category, setCategory] = useState("other");
    const [subject, setSubject] = useState("");
    const [body, setBody] = useState("");

    const ready = subject.trim().length >= MIN_SUBJECT && body.trim().length >= MIN_BODY;

    const submit = async () => {
        if (!ready || isPending) return;
        try {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            const result = await createTicket({
                subject: subject.trim(),
                body: body.trim(),
                category,
            });
            setComposing(false);
            setSubject("");
            setBody("");
            setCategory("other");
            Toast.success("Sent", result.message);
        } catch (err) {
            // The backend's own sentence, never a status code.
            Toast.error("Couldn't send that", errorMessage(err, "Please try again in a moment."));
        }
    };

    const openTicket = (ticket: SupportTicketSummary) => {
        Haptics.selectionAsync();
        router.push({ pathname: "/(screens)/SupportTicket", params: { id: ticket.id } } as any);
    };

    const formatWhen = (iso: string | null) => {
        if (!iso) return "";
        const date = new Date(iso);
        return date.toLocaleDateString("en-KE", { day: "numeric", month: "short" });
    };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            {/* HEAD */}
            <View
                className="flex-row items-center justify-between px-4 py-3 pb-4 mb-2"
                style={{
                    backgroundColor: darkTheme ? "#000" : "#fff",
                    borderBottomWidth: 1,
                    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                }}
            >
                <View className="flex-row items-center">
                    <TouchableOpacity onPress={() => router.back()} className="mr-4">
                        <BackButtonMinimal />
                    </TouchableOpacity>
                    <Text className={`font-sans-bold text-xl ${darkTheme ? "text-white" : "text-black"}`}>
                        Help & support
                    </Text>
                </View>
                <PressableScale
                    onPress={() => {
                        Haptics.selectionAsync();
                        setComposing(true);
                    }}
                    className="flex-row items-center gap-1.5 px-3 py-2 rounded-full"
                    style={{ backgroundColor: BRAND.primary }}
                >
                    <Ionicons name="add" size={16} color="#fff" />
                    <Text className="text-white font-sans-semibold text-sm">New</Text>
                </PressableScale>
            </View>

            <ScrollView
                contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 120, flexGrow: 1 }}
                refreshControl={
                    <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={BRAND.primary} />
                }
            >
                {isLoading ? (
                    <View className="flex-1 items-center justify-center py-24">
                        <ActivityIndicator size="large" color={BRAND.primary} />
                    </View>
                ) : isError ? (
                    <View className="items-center justify-center py-20 px-4">
                        <Ionicons name="cloud-offline-outline" size={44} color={BRAND.primary} />
                        <Text className={`text-center mt-4 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                            {errorMessage(error, "We couldn't load your requests.")}
                        </Text>
                        <PressableScale
                            onPress={() => refetch()}
                            className="mt-5 px-6 py-3 rounded-xl"
                            style={{ backgroundColor: BRAND.primary }}
                        >
                            <Text className="text-white font-sans-bold">Try again</Text>
                        </PressableScale>
                    </View>
                ) : tickets.length === 0 ? (
                    <View className="flex-1 pt-6">
                        <EmptyState
                            mood="search"
                            title="Nothing open"
                            subtitle="A payout that hasn't landed, a rider dispute, a store detail you can't change — tell us and we'll reply here in the app."
                            ctaLabel="Ask for help"
                            onCtaPress={() => setComposing(true)}
                        />
                    </View>
                ) : (
                    <View className="pt-2">
                        {tickets.map((ticket) => {
                            const tone = STATUS_TONE[ticket.status] ?? STATUS_TONE.closed;
                            return (
                                <TouchableOpacity
                                    key={ticket.id}
                                    activeOpacity={0.7}
                                    onPress={() => openTicket(ticket)}
                                    className={`p-4 mb-3 rounded-2xl border ${
                                        darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"
                                    }`}
                                >
                                    <View className="flex-row items-start justify-between gap-3">
                                        <Text
                                            numberOfLines={2}
                                            className={`flex-1 font-sans-semibold text-base ${
                                                darkTheme ? "text-white" : "text-gray-900"
                                            }`}
                                        >
                                            {ticket.subject}
                                        </Text>
                                        <View
                                            className={`px-2.5 py-1 rounded-full ${
                                                darkTheme ? tone.dark.split(" ")[0] : tone.light.split(" ")[0]
                                            }`}
                                        >
                                            <Text
                                                className={`text-xs font-sans-semibold ${
                                                    darkTheme ? tone.dark.split(" ")[1] : tone.light.split(" ")[1]
                                                }`}
                                            >
                                                {tone.label}
                                            </Text>
                                        </View>
                                    </View>
                                    <View className="flex-row items-center justify-between mt-2">
                                        <Text className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                            {formatWhen(ticket.created_at)}
                                        </Text>
                                        <Ionicons
                                            name="chevron-forward"
                                            size={16}
                                            color={darkTheme ? "#6b7280" : "#9ca3af"}
                                        />
                                    </View>
                                </TouchableOpacity>
                            );
                        })}
                    </View>
                )}
            </ScrollView>

            {/* COMPOSER */}
            <Modal
                visible={composing}
                animationType="slide"
                presentationStyle="pageSheet"
                onRequestClose={() => setComposing(false)}
            >
                <KeyboardAvoidingView
                    behavior={Platform.OS === "ios" ? "padding" : undefined}
                    className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}
                >
                    <View
                        className="flex-row items-center justify-between px-4 py-4"
                        style={{ borderBottomWidth: 1, borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }}
                    >
                        <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}>
                            Ask for help
                        </Text>
                        <TouchableOpacity accessibilityRole="button" accessibilityLabel="Close the help form" onPress={() => setComposing(false)}>
                            <Ionicons name="close" size={24} color={darkTheme ? "#fff" : "#000"} />
                        </TouchableOpacity>
                    </View>

                    <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
                        <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                            What's it about?
                        </Text>
                        <View className="flex-row flex-wrap gap-2 mb-6">
                            {(categories.length ? categories : Object.keys(CATEGORY_LABELS)).map((key) => {
                                const selected = key === category;
                                return (
                                    <TouchableOpacity
                                        key={key}
                                        activeOpacity={0.7}
                                        onPress={() => {
                                            Haptics.selectionAsync();
                                            setCategory(key);
                                        }}
                                        className={`px-3.5 py-2 rounded-full border ${
                                            selected
                                                ? ""
                                                : darkTheme
                                                  ? "border-gray-700"
                                                  : "border-gray-200"
                                        }`}
                                        style={
                                            selected
                                                ? { backgroundColor: BRAND.primary, borderColor: BRAND.primary }
                                                : undefined
                                        }
                                    >
                                        <Text
                                            className={`text-sm font-sans-medium ${
                                                selected ? "text-white" : darkTheme ? "text-gray-300" : "text-gray-700"
                                            }`}
                                        >
                                            {CATEGORY_LABELS[key] ?? key}
                                        </Text>
                                    </TouchableOpacity>
                                );
                            })}
                        </View>

                        <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                            Subject
                        </Text>
                        <TextInput
                            value={subject}
                            onChangeText={setSubject}
                            maxLength={200}
                            placeholder="e.g. Last week's payout hasn't arrived"
                            placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                            className={`px-4 py-3 rounded-xl border mb-6 ${
                                darkTheme
                                    ? "bg-surface-container border-gray-800 text-white"
                                    : "bg-white border-gray-200 text-black"
                            }`}
                        />

                        <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                            What happened?
                        </Text>
                        <TextInput
                            value={body}
                            onChangeText={setBody}
                            maxLength={5000}
                            multiline
                            textAlignVertical="top"
                            placeholder="Tell us what happened. Order numbers and dates help."
                            placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                            className={`px-4 py-3 rounded-xl border h-40 ${
                                darkTheme
                                    ? "bg-surface-container border-gray-800 text-white"
                                    : "bg-white border-gray-200 text-black"
                            }`}
                        />
                        <Text className={`text-xs mt-2 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                            {body.trim().length < MIN_BODY
                                ? `A few more words — at least ${MIN_BODY} characters.`
                                : "We reply in the app, and you'll get a notification."}
                        </Text>

                        <PressableScale
                            onPress={submit}
                            disabled={!ready || isPending}
                            className="mt-8 py-4 rounded-2xl items-center"
                            style={{ backgroundColor: ready && !isPending ? BRAND.primary : "#9ca3af" }}
                        >
                            {isPending ? (
                                <ActivityIndicator size="small" color="#fff" />
                            ) : (
                                <Text className="text-white font-sans-bold text-base">Send to support</Text>
                            )}
                        </PressableScale>
                    </ScrollView>
                </KeyboardAvoidingView>
            </Modal>
        </SafeAreaView>
    );
};

export default Support;
