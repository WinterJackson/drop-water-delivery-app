import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { UIThemeContext } from "@/context/ThemeContext";
import { FlashList } from "@shopify/flash-list";
import { useRouter } from "expo-router";
import React, { memo, useContext } from "react";
import { RefreshControl, StatusBar, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { PressableScale } from "@/components/ui/PressableScale";
import { useNotifications, notificationRows, useMarkNotificationRead, useMarkAllNotificationsRead, useUnreadNotificationCount } from "@/hooks/queries/useNotifications";
import { keepPaging } from "@/utils/paging";
import icons from "@/constants/icons/icons";
import { Image } from "expo-image";
import * as Haptics from "expo-haptics";
import { BRAND } from "@/constants/brandColors";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { VendorNotificationItemSkeleton } from "@/components/skeletons/ContextualSkeletons";

const getTypeColor = (type: string, darkTheme: boolean) => {
    switch (type) {
        case "order_update": return darkTheme ? "border-accentbg/50" : "border-accentbg";
        case "delivery_update": return darkTheme ? "border-green-500/50" : "border-green-500/80";
        case "promo": return darkTheme ? "border-amber-500/50" : "border-amber-500/80";
        case "alert": return darkTheme ? "border-red-500/50" : "border-red-500/80";
        default: return darkTheme ? "border-slate-700" : "border-slate-300";
    }
};

const getTypeIcon = (type: string) => {
    switch (type) {
        case "order_update": return icons.cart;
        case "delivery_update": return icons.bike;
        case "order_cancelled": return icons.close;
        case "promo": return icons.like;
        case "alert": return icons.help;
        default: return icons.notifications;
    }
};

const NotificationItemCard = memo(({ 
    item, 
    darkTheme, 
    markAsRead, 
    router 
}: { 
    item: any, 
    darkTheme: boolean, 
    markAsRead: (id: string) => void,
    router: any 
}) => {
    if (item.isHeader) {
        return (
            <Text className={`font-sans-bold text-lg mt-6 mb-3 px-1 uppercase tracking-wider text-xs ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                {item.title}
            </Text>
        );
    }
    
    return (
        <PressableScale
            activeOpacity={0.8}
            onPress={() => {
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                if (!item.is_read) markAsRead(item.id);
                if (item.action_url) {
                    router.push(item.action_url);
                } else if (item.related_order_id) {
                    router.push(`/(screens)/Orders`);
                }
            }}
        >
            <View className={`p-4 mb-3 rounded-[24px] border-l-4 shadow-sm ${getTypeColor(item.message_type, darkTheme)} ${
                item.is_read
                    ? (darkTheme ? "bg-surface-container border-r border-y border-outline-variant" : "bg-white border-r border-y border-gray-100")
                    : (darkTheme ? "bg-accentbg/10 border-r border-y border-accentbg/20" : "bg-accentbg/5 border-r border-y border-accentbg/10")
            }`} style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
                <View className="flex-row items-start gap-4">
                    <View className={`w-12 h-12 rounded-full items-center justify-center border ${darkTheme ? "bg-slate-800 border-slate-700" : "bg-white border-slate-200"}`}>
                        <Image 
                            source={getTypeIcon(item.message_type)} 
                            className="w-6 h-6" 
                            tintColor={darkTheme ? "#94a3b8" : "#64748b"} 
                        />
                    </View>
                    <View className="flex-1 pt-1">
                        <View className="flex-row justify-between items-start mb-1">
                            <Text className={`font-sans-bold text-base flex-1 pr-2 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                                {item.title}
                            </Text>
                            {!item.is_read && (
                                <View className="w-2.5 h-2.5 rounded-full bg-accentbg mt-1.5 shadow-sm shadow-accentbg" />
                            )}
                        </View>
                        <Text className={`text-sm leading-5 font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-600"}`}>
                            {item.message}
                        </Text>
                        <Text className={`text-xs mt-3 font-sans-semibold ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
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
});

export default function Notifications() {
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

    // The server's count, not a pass over the rows in hand. Counting the loaded
    // pages was exactly right while the screen fetched every notification there
    // was; now that it fetches one page, it would report "3 new" to somebody with
    // forty — and the "Mark all read" control beside it, which acts on all of
    // them, would disappear as soon as the unread ones fell past the first page.
    const { data: unread } = useUnreadNotificationCount();
    const unreadCount = unread?.unread_count ?? 0;

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
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
            
            {/* HEAD */}
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
                    <View className="flex-1 flex-row items-center">
                        <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                            Notifications
                        </Text>
                        {unreadCount > 0 && (
                            <View className="ml-2 bg-accentbg px-2 py-0.5 rounded-full">
                                <Text className="text-white text-xs font-sans-bold">{unreadCount} New</Text>
                            </View>
                        )}
                    </View>
                    {unreadCount > 0 && (
                        <PressableScale onPress={markAllAsRead} className="bg-accentbg/10 px-3 py-1.5 rounded-full border border-accentbg/20">
                            <Text className="text-accentbg font-sans-bold text-xs uppercase tracking-wider">Mark Read</Text>
                        </PressableScale>
                    )}
                </View>
            </View>

            <View style={{ flex: 1 }}>
                <FlashList
                    data={groupedNotifications}
                    keyExtractor={(item: any) => item.id}
                    // @ts-ignore
                    contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 120 }}
                    refreshControl={
                        <RefreshControl refreshing={loading} onRefresh={refetch} tintColor={darkTheme ? "white" : "black"} />
                    }
                    onEndReached={keepPaging(notificationsQuery)}
                    onEndReachedThreshold={0.5}
                    ListFooterComponent={
                        isFetchingNextPage ? (
                            <View className="py-6">
                                <VendorNotificationItemSkeleton />
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
                                <View className="pt-6 gap-4">
                                    {[...Array(5)].map((_, i) => (
                                        <VendorNotificationItemSkeleton key={i} />
                                    ))}
                                </View>
                            );
                        }
                        if (!loading && groupedNotifications.length === 0) {
                            return (
                                <View className="mt-16 items-center">
                                    <View className={`w-24 h-24 rounded-full items-center justify-center mb-6 shadow-sm border ${darkTheme ? "bg-slate-800 border-slate-700" : "bg-white border-slate-200"}`}>
                                        <Ionicons name="notifications" size={40} color={BRAND.primary} />
                                    </View>
                                    <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>All Caught Up</Text>
                                    <Text className={`text-base mt-2 text-center px-10 font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                                        You are up to date. No new notifications.
                                    </Text>
                                </View>
                            );
                        }
                        return null;
                    }}
                    renderItem={({ item }) => (
                        <NotificationItemCard 
                            item={item} 
                            darkTheme={darkTheme} 
                            markAsRead={markAsRead} 
                            router={router} 
                        />
                    )}
                />
            </View>
        </SafeAreaView>
    );
}
