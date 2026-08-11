import { Ionicons } from "@expo/vector-icons";
import React, { useContext } from "react";
import { View } from "react-native";
import { Text } from '@/components/ui/Text';

import { UIThemeContext } from "@/context/ThemeContext";

/**
 * "Paused until 14:30 — restocking."
 *
 * One component, used on the store page and anywhere else a shop's state has to
 * be shown, for the same reason the server has one `vendor_availability`: a
 * store marked open in a list and closed on its own page is the version of this
 * bug people screenshot.
 *
 * Every word comes from `store_reason`, which the server composes. It carries
 * the store's own note and its reopening time in the shop's local hours —
 * neither of which this app can produce, and both of which move without a
 * release.
 *
 * A closed store is deliberately still browsable. Hiding it would tell the
 * customer looking for the shop they always use that it has left the platform,
 * and would cost a shop that paused for twenty minutes its place in everybody's
 * list rather than twenty minutes of orders.
 */
export function StoreClosedNotice({
	store,
	compact = false,
}: {
	store?: {
		is_accepting_orders?: boolean;
		store_state?: string;
		store_reason?: string | null;
	} | null;
	compact?: boolean;
}) {
	const { currentTheme } = useContext<any>(UIThemeContext);
	const dark = currentTheme === "dark";

	// Absent means open. A response that predates this field, or one still
	// loading, must not close a shop on a screen that cannot see its state.
	if (!store || store.is_accepting_orders !== false) return null;

	const paused = store.store_state === "paused";
	const icon = paused ? "pause-circle" : "moon";
	const tint = paused ? "#F59E0B" : dark ? "#94A3B8" : "#64748B";

	if (compact) {
		return (
			<View className="flex-row items-center gap-1.5">
				<Ionicons name={icon} size={12} color={tint} />
				<Text className="text-xs font-sans-semibold" style={{ color: tint }} numberOfLines={1}>
					{store.store_reason ?? "Closed"}
				</Text>
			</View>
		);
	}

	return (
		<View
			className={`flex-row items-start gap-2.5 rounded-2xl px-4 py-3 ${
				dark ? "bg-slate-800/60" : "bg-slate-100"
			}`}
		>
			<Ionicons name={icon} size={18} color={tint} style={{ marginTop: 1 }} />
			<View className="flex-1">
				<Text className={`font-sans-bold text-sm ${dark ? "text-white" : "text-slate-900"}`}>
					{paused ? "Paused" : "Closed"}
				</Text>
				<Text className={`text-xs mt-0.5 ${dark ? "text-gray-400" : "text-slate-500"}`}>
					{store.store_reason ??
						"This store is not taking orders right now. You can still browse."}
				</Text>
			</View>
		</View>
	);
}

export default StoreClosedNotice;
