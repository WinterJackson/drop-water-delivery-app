import React, { useContext } from 'react';
import { View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import PressableScale from '@/components/ui/PressableScale';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND } from '@/constants/brandColors';
import { PERMISSIONS, useCan, useVendorProfile } from '@/hooks/queries/useVendorProfile';

/**
 * The four things a vendor reaches for most, filtered to the ones this caller
 * can actually do.
 *
 * It used to render the same four for everybody. "Add Item" is
 * `require_permission("manage_products")` and "Riders" is `get_owned_store` —
 * so a staff member handed the till tapped "Add Item" and got a form that
 * refused them at submit, and tapped "Riders" and was bounced straight back to
 * the screen they started on. Both are the app's own documented rule broken on
 * the busiest surface in it.
 *
 * The row keeps its shape rather than collapsing to two buttons: the ones a
 * caller can always reach — their orders and their profile — are appended, so
 * everybody gets a usable row and nobody gets a dead end. Bottles fills the gap
 * for whoever holds that capability instead, which is exactly the shop-floor
 * staff member this used to fail.
 */
export default function QuickActions() {
    const router = useRouter();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";

    const { data: profile } = useVendorProfile();
    const isOwner = profile?.role !== "staff";
    const canManageProducts = useCan(PERMISSIONS.manageProducts);
    const canManageBottles = useCan(PERMISSIONS.manageBottles);
    const canManageOrders = useCan(PERMISSIONS.manageOrders);

    const actions = [
        canManageProducts && {
            key: "add",
            icon: "add" as const,
            label: "Add Item",
            path: "/(screens)/AddProduct",
        },
        canManageBottles && {
            key: "bottles",
            icon: "water-outline" as const,
            label: "Bottles",
            path: "/(screens)/BottleReconciliation",
        },
        {
            // Reading the board needs no capability; acting on it does, and the
            // order screens gate their own buttons.
            key: "orders",
            icon: "cube-outline" as const,
            label: canManageOrders ? "Orders" : "View orders",
            path: "/(screens)/Orders",
        },
        isOwner && {
            key: "riders",
            icon: "bicycle-outline" as const,
            label: "Riders",
            path: "/(screens)/RiderManagement",
        },
        {
            key: "profile",
            icon: "person-outline" as const,
            label: "Profile",
            path: "/(screens)/Profile",
        },
    ].filter(Boolean) as { key: string; icon: any; label: string; path: string }[];

    // Four is what the row is laid out for; the tail is always Profile, which is
    // the least urgent, so trimming from the front of the overflow is wrong and
    // trimming from the middle is confusing. Keep the first four.
    const shown = actions.slice(0, 4);

    return (
        <View className="flex-row justify-between px-4 mt-6">
            {shown.map((action) => (
                <PressableScale
                    key={action.key}
                    onPress={() => router.push(action.path as any)}
                    className="items-center flex-1"
                    accessibilityRole="button"
                    accessibilityLabel={action.label}
                >
                    <View
                        className={`w-14 h-14 rounded-full items-center justify-center mb-2 shadow-sm border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`}
                        style={darkTheme
                            ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 }
                            : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
                    >
                        <Ionicons name={action.icon} size={24} color={BRAND.primary} />
                    </View>
                    <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-slate-300" : "text-slate-600"}`}>
                        {action.label}
                    </Text>
                </PressableScale>
            ))}
        </View>
    );
}
