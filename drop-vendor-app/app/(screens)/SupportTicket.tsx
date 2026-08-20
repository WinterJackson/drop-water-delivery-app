import { errorMessage } from "@/API/errors";
import { useTabBarClearance } from '@/constants/layout';
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { useReplyToSupportTicket, useSupportTicket } from "@/hooks/queries/useSupport";
import { Toast } from "@/lib/toast";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useContext, useRef, useState } from "react";
import {
    ActivityIndicator,
    KeyboardAvoidingView,
    Platform,
    ScrollView,
    TouchableOpacity,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";

/**
 * One support conversation.
 *
 * The thread the server sends has already had internal notes removed — support
 * staff write "the rider says the bottles were short" in the same
 * thread, and filtering that here would be one careless render away from
 * showing it. This screen renders what it is given.
 *
 * A reply reopens a resolved ticket, because somebody writing back is saying it
 * is not resolved.
 */

const STATUS_COPY: Record<string, string> = {
    open: "Waiting for us",
    pending: "We've replied",
    resolved: "Resolved",
    closed: "Closed",
};

const SupportTicket = () => {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const { id } = useLocalSearchParams<{ id: string }>();
    const scrollRef = useRef<ScrollView>(null);

    const { data: ticket, isLoading, isError, error, refetch } = useSupportTicket(id);
    const { mutateAsync: reply, isPending } = useReplyToSupportTicket(id);

    const [draft, setDraft] = useState("");

    const send = async () => {
        const body = draft.trim();
        if (!body || isPending) return;
        try {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            await reply(body);
            setDraft("");
            // The refetch is what puts the message on screen; the mutation only
            // invalidates. Scrolling before it lands would jump to nothing.
            const fresh = await refetch();
            if (fresh.data) requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: true }));
        } catch (err) {
            Toast.error("Couldn't send that", errorMessage(err, "Please try again in a moment."));
        }
    };

    const formatWhen = (iso: string | null) => {
        if (!iso) return "";
        const date = new Date(iso);
        return date.toLocaleString("en-KE", {
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
        });
    };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <View
                className="flex-row items-center px-4 py-3 pb-4"
                style={{
                    backgroundColor: darkTheme ? "#000" : "#fff",
                    borderBottomWidth: 1,
                    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                }}
            >
                <TouchableOpacity onPress={() => router.back()} className="mr-4">
                    <BackButtonMinimal />
                </TouchableOpacity>
                <View className="flex-1">
                    <Text
                        numberOfLines={1}
                        className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}
                    >
                        {ticket?.subject ?? "Your request"}
                    </Text>
                    {ticket ? (
                        <Text className={`text-xs mt-0.5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            {STATUS_COPY[ticket.status] ?? ticket.status}
                        </Text>
                    ) : null}
                </View>
            </View>

            <KeyboardAvoidingView
                behavior={Platform.OS === "ios" ? "padding" : undefined}
                keyboardVerticalOffset={Platform.OS === "ios" ? 8 : 0}
                className="flex-1"
            >
                <ScrollView
                    ref={scrollRef}
                    contentContainerStyle={{ padding: 16, paddingBottom: tabBarClearance }}
                    onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: false })}
                >
                    {isLoading ? (
                        <View className="items-center justify-center py-24">
                            <ActivityIndicator size="large" color={BRAND.primary} />
                        </View>
                    ) : isError || !ticket ? (
                        <View className="items-center justify-center py-20 px-4">
                            <Ionicons name="alert-circle-outline" size={44} color={BRAND.primary} />
                            <Text className={`text-center mt-4 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                                {errorMessage(error, "We couldn't open this request.")}
                            </Text>
                            <PressableScale
                                onPress={() => refetch()}
                                className="mt-5 px-6 py-3 rounded-xl"
                                style={{ backgroundColor: BRAND.primary }}
                            >
                                <Text className="text-white font-sans-bold">Try again</Text>
                            </PressableScale>
                        </View>
                    ) : (
                        <>
                            {/* What they originally sent. Part of the conversation,
                                not a header — it is the first thing said. */}
                            <Bubble
                                mine
                                darkTheme={darkTheme}
                                body={ticket.body}
                                when={formatWhen(ticket.created_at)}
                            />

                            {ticket.messages.map((message, index) => (
                                <Bubble
                                    key={`${message.at ?? index}-${index}`}
                                    mine={message.author !== "admin"}
                                    darkTheme={darkTheme}
                                    body={message.body}
                                    when={formatWhen(message.at)}
                                    author={message.author === "admin" ? "Drop support" : undefined}
                                />
                            ))}

                            {ticket.resolution ? (
                                <View
                                    className={`mt-4 p-4 rounded-2xl border ${
                                        darkTheme ? "border-green-900 bg-green-900/20" : "border-green-200 bg-green-50"
                                    }`}
                                >
                                    <Text
                                        className={`text-xs font-sans-bold uppercase tracking-wider ${
                                            darkTheme ? "text-green-400" : "text-green-700"
                                        }`}
                                    >
                                        How this was resolved
                                    </Text>
                                    <Text className={`mt-1.5 ${darkTheme ? "text-green-200" : "text-green-800"}`}>
                                        {ticket.resolution}
                                    </Text>
                                </View>
                            ) : null}
                        </>
                    )}
                </ScrollView>

                {ticket ? (
                    <View
                        className="flex-row items-end gap-2 px-4 py-3"
                        style={{
                            borderTopWidth: 1,
                            borderTopColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                            backgroundColor: darkTheme ? "#000" : "#fff",
                        }}
                    >
                        <TextInput
                            value={draft}
                            onChangeText={setDraft}
                            maxLength={5000}
                            multiline
                            placeholder={
                                ticket.status === "resolved" || ticket.status === "closed"
                                    ? "Still not sorted? Reply to reopen it."
                                    : "Add to this request…"
                            }
                            placeholderTextColor={darkTheme ? "#6b7280" : "#9ca3af"}
                            className={`flex-1 px-4 py-3 rounded-2xl border max-h-32 ${
                                darkTheme
                                    ? "bg-surface-container border-gray-800 text-white"
                                    : "bg-white border-gray-200 text-black"
                            }`}
                        />
                        <PressableScale accessibilityLabel="Send your reply"
                            onPress={send}
                            disabled={!draft.trim() || isPending}
                            className="w-12 h-12 rounded-full items-center justify-center"
                            style={{ backgroundColor: draft.trim() && !isPending ? BRAND.primary : "#9ca3af" }}
                        >
                            {isPending ? (
                                <ActivityIndicator size="small" color="#fff" />
                            ) : (
                                <Ionicons name="send" size={18} color="#fff" />
                            )}
                        </PressableScale>
                    </View>
                ) : null}
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
};

function Bubble({
    mine,
    darkTheme,
    body,
    when,
    author,
}: {
    mine: boolean;
    darkTheme: boolean;
    body: string;
    when: string;
    author?: string;
}) {
    return (
        <View className={`mb-3 ${mine ? "items-end" : "items-start"}`}>
            {author ? (
                <Text className={`text-xs mb-1 ml-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>{author}</Text>
            ) : null}
            <View
                className={`px-4 py-3 rounded-2xl max-w-[85%] ${
                    mine
                        ? ""
                        : darkTheme
                          ? "bg-surface-container border border-gray-800"
                          : "bg-white border border-gray-200"
                }`}
                style={mine ? { backgroundColor: BRAND.primary } : undefined}
            >
                <Text className={mine ? "text-white" : darkTheme ? "text-gray-100" : "text-gray-900"}>{body}</Text>
            </View>
            <Text className={`text-[11px] mt-1 mx-1 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>{when}</Text>
        </View>
    );
}

export default SupportTicket;
