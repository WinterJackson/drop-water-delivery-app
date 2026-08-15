import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React, { useContext, useMemo, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { Text } from '@/components/ui/Text';

import { errorMessage } from "@/API/errors";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import {
    useBottleCollections,
    useClaimBottleCollection,
    useConfirmBottleCollection,
    type BottleCollection,
    type VendorBottleDebt,
} from "@/hooks/queries/useBottleDebt";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";

/**
 * Collecting a customer's bottles so their deposit can go back.
 *
 * This sits on "Bottles I'm Holding" rather than on a screen of its own,
 * because that is exactly what a collection does to the rider: it *adds* to
 * what they are holding. Confirming one releases the customer's deposit and, in
 * the same transaction, records these bottles against the store the rider names.
 *
 * **Two things the rider has to state, and both matter.**
 *
 * The *count* is one of two — the customer states the other, and the deposit
 * moves only if they agree. A disagreement goes to a human; nothing is split,
 * because a count that quietly splits the difference is one worth understating.
 *
 * The *store* is where these bottles are going. Without it the ledger cannot
 * attribute them and a bottle leaves the customer's count while still existing
 * in the rider's pannier — which is why it is required here rather than
 * optional, and why the picker offers the stores the rider already deals with.
 */

type Props = {
    vendors: VendorBottleDebt[];
    fallbackVendors?: { vendor_id: string; business_name: string }[];
};

export function CollectionsSection({ vendors, fallbackVendors = [] }: Props) {
    const { currentTheme } = useContext(UIThemeContext);
    const dark = currentTheme === "dark";

    const { data, isLoading } = useBottleCollections();
    const claim = useClaimBottleCollection();
    const confirm = useConfirmBottleCollection();

    const items = useMemo(() => data?.items ?? [], [data]);

    // Stores this rider already deals with. `useBottleDebt` is the better
    // source — they demonstrably work with these — with the registry behind it
    // for a rider who happens to owe nobody anything today.
    const stores = useMemo(() => {
        const seen = new Map<string, string>();
        for (const v of vendors) seen.set(v.vendor_id, v.business_name);
        for (const v of fallbackVendors) if (!seen.has(v.vendor_id)) seen.set(v.vendor_id, v.business_name);
        return [...seen.entries()].map(([id, name]) => ({ id, name }));
    }, [vendors, fallbackVendors]);

    if (isLoading || items.length === 0) return null;

    return (
        <View className="mt-4">
            <Text className={`text-sm font-sans-bold mb-1 ${dark ? "text-gray-300" : "text-slate-700"}`}>
                Bottle collections
            </Text>
            <Text className={`text-xs mb-3 ${dark ? "text-gray-500" : "text-slate-400"}`}>
                Customers waiting to hand bottles back. Collecting one releases their
                deposit and adds those bottles to what you are holding.
            </Text>

            {items.map((item) => (
                <CollectionCard
                    key={item.id}
                    item={item}
                    stores={stores}
                    dark={dark}
                    onClaim={async () => {
                        try {
                            await claim.mutateAsync({ id: item.id });
                            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
                            Toast.success("Collection taken", "Confirm the count when you have the bottles.");
                        } catch (err) {
                            Toast.error("Couldn't take that on", errorMessage(err));
                        }
                    }}
                    onConfirm={async (bottles, vendorId) => {
                        try {
                            const result = await confirm.mutateAsync({ id: item.id, bottles, vendorId });
                            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
                            if (result.status === "settled") {
                                Toast.success("Done", "The customer's deposit has gone back.");
                            } else if (result.status === "disputed") {
                                Toast.info("Counts don't match", result.detail ?? "Somebody will check this.");
                            } else {
                                Toast.info("Confirmed", "Waiting for the customer to confirm.");
                            }
                        } catch (err) {
                            Toast.error("Couldn't confirm", errorMessage(err));
                        }
                    }}
                    busy={claim.isPending || confirm.isPending}
                />
            ))}
        </View>
    );
}

function CollectionCard({
    item,
    stores,
    dark,
    onClaim,
    onConfirm,
    busy,
}: {
    item: BottleCollection;
    stores: { id: string; name: string }[];
    dark: boolean;
    onClaim: () => void;
    onConfirm: (bottles: number, vendorId: string) => void;
    busy: boolean;
}) {
    const [count, setCount] = useState(item.bottles_requested || 1);
    const [store, setStore] = useState<string | null>(stores[0]?.id ?? null);

    const unclaimed = item.status === "requested";
    const alreadyStated = item.bottles_stated_by_rider !== null;

    return (
        <View
            className={`p-4 rounded-2xl mb-3 ${dark ? "bg-surface-container" : "bg-white"}`}
        >
            <View className="flex-row items-center justify-between">
                <View className="flex-row items-center gap-2">
                    <Ionicons name="cube-outline" size={18} color={BRAND.primary} />
                    <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
                        {item.bottles_requested} bottle{item.bottles_requested === 1 ? "" : "s"} to collect
                    </Text>
                </View>
                {alreadyStated ? (
                    <Text className={`text-xs ${dark ? "text-gray-500" : "text-slate-400"}`}>
                        waiting on customer
                    </Text>
                ) : null}
            </View>

            {unclaimed ? (
                <PressableScale onPress={onClaim} disabled={busy}>
                    <View
                        className="mt-3 rounded-xl py-3 items-center flex-row justify-center gap-2"
                        style={{ backgroundColor: BRAND.primary, opacity: busy ? 0.6 : 1 }}
                    >
                        {busy ? <ActivityIndicator color="#fff" size="small" /> : null}
                        <Text className="text-white font-sans-bold">I'll collect these</Text>
                    </View>
                </PressableScale>
            ) : alreadyStated ? (
                <Text className={`text-xs mt-2 ${dark ? "text-gray-400" : "text-slate-500"}`}>
                    You said {item.bottles_stated_by_rider}. The deposit goes back as soon as
                    the customer confirms the same — or on its own shortly, since you have
                    the bottles.
                </Text>
            ) : (
                <>
                    <View className="flex-row items-center justify-between mt-3">
                        <Text className={`text-sm ${dark ? "text-gray-300" : "text-slate-600"}`}>
                            Bottles I collected
                        </Text>
                        <View className="flex-row items-center gap-4">
                            <PressableScale
                                onPress={() => setCount((c) => Math.max(1, c - 1))}
                                accessibilityLabel="One fewer bottle"
                            >
                                <View className={`w-9 h-9 rounded-full items-center justify-center ${dark ? "bg-slate-800" : "bg-slate-100"}`}>
                                    <Ionicons name="remove" size={18} color={dark ? "#E2E8F0" : "#0F172A"} />
                                </View>
                            </PressableScale>
                            <Text className={`text-xl font-sans-extrabold w-8 text-center ${dark ? "text-white" : "text-slate-900"}`}>
                                {count}
                            </Text>
                            <PressableScale
                                onPress={() => setCount((c) => c + 1)}
                                accessibilityLabel="One more bottle"
                            >
                                <View className={`w-9 h-9 rounded-full items-center justify-center ${dark ? "bg-slate-800" : "bg-slate-100"}`}>
                                    <Ionicons name="add" size={18} color={dark ? "#E2E8F0" : "#0F172A"} />
                                </View>
                            </PressableScale>
                        </View>
                    </View>

                    <Text className={`text-xs mt-4 mb-2 ${dark ? "text-gray-400" : "text-slate-500"}`}>
                        Handing them in to
                    </Text>
                    {stores.length === 0 ? (
                        <Text className={`text-xs ${dark ? "text-amber-400" : "text-amber-700"}`}>
                            You are not registered with a store yet. Register with one before
                            collecting — the bottles have to be owed to somebody.
                        </Text>
                    ) : (
                        <View className="flex-row flex-wrap gap-2">
                            {stores.map((s) => (
                                <PressableScale key={s.id} onPress={() => setStore(s.id)}>
                                    <View
                                        className="px-3 py-2 rounded-xl border"
                                        style={{
                                            borderColor: store === s.id ? BRAND.primary : dark ? "#1E293B" : "#E2E8F0",
                                            backgroundColor: store === s.id ? `${BRAND.primary}18` : "transparent",
                                        }}
                                    >
                                        <Text
                                            className={`text-xs font-sans-medium ${dark ? "text-gray-200" : "text-slate-700"}`}
                                        >
                                            {s.name}
                                        </Text>
                                    </View>
                                </PressableScale>
                            ))}
                        </View>
                    )}

                    <PressableScale
                        onPress={() => store && onConfirm(count, store)}
                        disabled={busy || !store}
                    >
                        <View
                            className="mt-4 rounded-xl py-3 items-center flex-row justify-center gap-2"
                            style={{
                                backgroundColor: BRAND.primary,
                                opacity: busy || !store ? 0.5 : 1,
                            }}
                        >
                            {busy ? <ActivityIndicator color="#fff" size="small" /> : null}
                            <Text className="text-white font-sans-bold">Confirm collection</Text>
                        </View>
                    </PressableScale>
                </>
            )}
        </View>
    );
}
