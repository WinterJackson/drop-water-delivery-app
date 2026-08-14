import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { EmptyState } from "@/components/ui/EmptyState";
import { NotificationItemSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { UIThemeContext } from "@/context/ThemeContext";
import { FlashList as OriginalFlashList } from "@shopify/flash-list";
import { useRouter } from "expo-router";
import { useContext } from "react";
import { RefreshControl, StatusBar, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { PressableScale } from "@/components/ui/PressableScale";
import { useNotifications, notificationRows, useMarkNotificationRead, useMarkAllNotificationsRead, useUnreadNotificationCount } from "@/hooks/queries/useNotifications";
import { keepPaging } from "@/utils/paging";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import * as Haptics from "expo-haptics";
import { BRAND } from "@/constants/brandColors";

const FlashList = OriginalFlashList as any;

const Notifications = () => {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const notificationsQuery = useNotifications();
    const { isLoading: loading, isFetchingNextPage, hasNextPage, refetch } = notificationsQuery;
    const notifications = notificationRows(notificationsQuery.data);
    const { mutateAsync: markAsReadMutation } = useMarkNotificationRead();
    const { mutateAsync: markAllAsReadMutation } = useMarkAllNotificationsRead();

    const markAsRead = async (notificationId: string) => {
        try {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            await markAsReadMutation(notificationId);
        } catch (error) {
            if (__DEV__) console.error("Error marking notification read:", error);
        }
    };

    const markAllAsRead = async () => {
        try {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            await markAllAsReadMutation();
        } catch (error) {
            if (__DEV__) console.error("Error marking all read:", error);
        }
    };

    const safeNavigate = (url: string) => {
        // Whitelist safe route prefixes to prevent malicious deep links from backend payloads
        const allowedPrefixes = ["/(screens)", "/product-details", "/vendor"];
        if (allowedPrefixes.some(prefix => url.startsWith(prefix))) {
            router.push(url as any);
        } else {
            if (__DEV__) console.warn(`Blocked navigation to unsafe url: ${url}`);
        }
    };

    // The server's count, not a pass over the rows in hand. Counting the loaded
    // pages was exactly right while the screen fetched every notification there
    // was; now that it fetches one page, it would report "3 new" to somebody with
    // forty — and the "Mark all read" control beside it, which acts on all of
    // them, would disappear as soon as the unread ones fell past the first page.
    const { data: unread } = useUnreadNotificationCount();
    const unreadCount = unread?.unread_count ?? 0;

    const getTypeColor = (type: string) => {
        switch (type) {
            case "order_update": return darkTheme ? "border-blue-500/30" : "border-blue-200";
            case "delivery_update": return darkTheme ? "border-green-500/30" : "border-green-200";
            case "promo": return darkTheme ? "border-yellow-500/30" : "border-yellow-200";
            case "alert": return darkTheme ? "border-red-500/30" : "border-red-200";
            default: return darkTheme ? "border-gray-700" : "border-gray-200";
        }
    };

    const getTypeIcon = (type: string) => {
        switch (type) {
            case "order_update": return "cart";
            case "delivery_update": return "bicycle";
            case "order_cancelled": return "close";
            case "promo": return "heart";
            case "alert": return "help-circle";
            default: return "notifications";
        }
    };

    // Date grouping function
    const formatDateObj = (dateStr: string | null) => {
        if (!dateStr) return "Older";
        const date = new Date(dateStr);
        const today = new Date();
        const yesterday = new Date();
        yesterday.setDate(yesterday.getDate() - 1);

        if (date.toDateString() === today.toDateString()) {
            return "Today";
        } else if (date.toDateString() === yesterday.toDateString()) {
            return "Yesterday";
        } else {
            return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
        }
    };

    // Add a section header logic
    const groupedNotifications = [];
    let lastDateGrp = null;
    
    for (const notif of notifications) {
        const grp = formatDateObj(notif.created_at);
        if (grp !== lastDateGrp) {
            groupedNotifications.push({ isHeader: true, title: grp, id: `header-${grp}` });
            lastDateGrp = grp;
        }
        groupedNotifications.push(notif);
    }

    return (
        <View className={`flex-1 ${darkTheme ? "bg-black" : ""}`} style={{ paddingTop: StatusBar.currentHeight }}>
            {/* HEAD */}
            <View style={{ overflow: "hidden", paddingBottom: 4 }}>
            <View 
                className="flex-row items-center p-3 gap-3 justify-between pb-4 mb-2"
                style={{ 
    backgroundColor: darkTheme ? "#000" : "#fff",
    borderBottomWidth: 1, 
    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
}}
            >
                <View className="flex-row items-center gap-3">
                    <PressableScale onPress={() => router.back()} activeOpacity={0.7}>
                        <BackButtonMinimal />
                    </PressableScale>
                    <Text className={`font-sans-bold text-xl ${darkTheme ? "text-white" : "text-black"}`}>
                        Notifications
                        {unreadCount > 0 && (
                            <Text className="font-sans-bold text-blue-500 text-base"> ({unreadCount} new)</Text>
                        )}
                    </Text>
                </View>
                {unreadCount > 0 && (
                    <PressableScale onPress={markAllAsRead} activeOpacity={0.7}>
                        <Text className="text-blue-500 font-sans-semibold text-sm">Mark all read</Text>
                    </PressableScale>
                )}
            </View>
            </View>

            <View style={{ flex: 1, marginHorizontal: 0 }}>
                <FlashList
                    data={groupedNotifications}
                    contentContainerStyle={{ padding: 15, paddingBottom: 120}}
                    ItemSeparatorComponent={() => <View style={{ height: 12 }} />}
                    refreshControl={
                        <RefreshControl refreshing={loading} onRefresh={refetch} tintColor={darkTheme ? "#fff" : "#000"} />
                    }
                    onEndReached={keepPaging(notificationsQuery)}
                    onEndReachedThreshold={0.5}
                    ListFooterComponent={
                        isFetchingNextPage ? (
                            <View className="py-6">
                                <NotificationItemSkeleton />
                            </View>
                        ) : !hasNextPage && notifications.length > 0 ? (
                            // The end of the history, said out loud. Without it a
                            // list that simply stops is indistinguishable from one
                            // that failed to load the next page.
                            <Text className={`text-center text-xs py-6 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
                                That's everything.
                            </Text>
                        ) : null
                    }
                    ListEmptyComponent={() => {
                        if (loading && groupedNotifications.length === 0) {
                            return (
                                <View className="px-2 mt-4">
                                    <NotificationItemSkeleton />
                                    <NotificationItemSkeleton />
                                    <NotificationItemSkeleton />
                                    <NotificationItemSkeleton />
                                </View>
                            );
                        }
                        if (!loading && groupedNotifications.length === 0) {
                            return (
                                <View className="mt-10">
                                    <EmptyState 
                                        mood="proud" 
                                        title="All Caught Up" 
                                        subtitle="You are up to date. No new notifications." 
                                    />
                                </View>
                            );
                        }
                        return null;
                    }}
                    renderItem={({ item }: { item: any }) => {
                        if (item.isHeader) {
                            return (
                                <Text className={`font-sans-bold text-lg mt-4 mb-2 ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>
                                    {item.title}
                                </Text>
                            );
                        }
                        
                        return (
                            <PressableScale
                                activeOpacity={0.8}
                                onPress={() => {
                                    if (!item.is_read) markAsRead(item.id);
                                    if (item.action_url) {
                                        safeNavigate(item.action_url);
                                    } else if (item.related_order_id) {
                                        router.push(`/(screens)/Orders`);
                                    }
                                }}
                            >
                                <View className={`p-4 rounded-2xl border-l-4 ${getTypeColor(item.message_type)} ${
                                    item.is_read
                                        ? (darkTheme ? "bg-gray-900/50" : "bg-white")
                                        : (darkTheme ? "bg-blue-900/10" : "bg-blue-50/50")
                                }`}>
                                    <View className="flex-row items-start gap-4">
                                        <View className={`w-12 h-12 rounded-full items-center justify-center ${darkTheme ? "bg-gray-800" : "bg-white"} shadow-sm`}>
                                            <Ionicons 
                                                name={getTypeIcon(item.message_type) as any} 
                                                size={24} 
                                                color={darkTheme ? "#A0AEC0" : "#4A5568"} 
                                            />
                                        </View>
                                        <View className="flex-1">
                                            <View className="flex-row justify-between items-center mb-1">
                                                <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`}>
                                                    {item.title}
                                                </Text>
                                                {!item.is_read && (
                                                    <View className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                                                )}
                                            </View>
                                            <Text className={`text-sm leading-5 ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>
                                                {item.message}
                                            </Text>
                                            <Text className={`text-xs mt-2 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                                {item.created_at
                                                    ? new Date(item.created_at).toLocaleTimeString("en-US", {
                                                        hour: "2-digit", minute: "2-digit"
                                                    })
                                                    : ""
                                                }
                                            </Text>
                                        </View>
                                    </View>
                                </View>
                            </PressableScale>
                        );
                    }}
                />
            </View>
        </View>
    );
};

export default Notifications;
