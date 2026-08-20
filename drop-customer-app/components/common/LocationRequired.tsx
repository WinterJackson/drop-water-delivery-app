import React, { useContext, useState } from 'react';
import { View, ActivityIndicator } from 'react-native';
import { Text } from '@/components/ui/Text';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { UIThemeContext } from '@/context/ThemeContext';
import { PressableScale } from '@/components/ui/PressableScale';
import DropButton from '@/components/ui/DropButton';
import { BRAND } from '@/constants/brandColors';
import { useDeliveryLocation } from '@/hooks/useDeliveryLocation';
import { useUpdateLocation } from '@/hooks/queries/useUser';
import { useLocation } from '@/hooks/useLocation';
import { Toast } from '@/lib/toast';
import { errorMessage } from '@/API/errors';

/**
 * The home screen when the platform does not know where to deliver.
 *
 * This replaces a yellow warning that read "Limited Coverage Area — No vendors
 * currently deliver to your location", which was shown for two completely
 * different situations and was wrong about both:
 *
 * * a customer who had never set an address, who was being told their
 *   neighbourhood is unserved when in fact nobody had asked them where they
 *   live;
 * * a customer whose six deliverable shops had all been deleted from the query
 *   by a NULL cache column, who was being told the truth about the result and
 *   nothing true about the platform.
 *
 * An unknown location is a question. So this asks it — once, prominently, with
 * the two ways of answering it, and without any of the surrounding shelves that
 * would imply the app already knew.
 */
export default function LocationRequired() {
    const router = useRouter();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === 'dark';
    const { deviceFix } = useDeliveryLocation();
    const { requestLocation, reverseGeocode, loading: locating } = useLocation();
    const updateLocation = useUpdateLocation();
    const [using, setUsing] = useState(false);

    /**
     * Use the handset's own position as the delivery address.
     *
     * Saved rather than held in memory, because the radius is measured
     * server-side on every discovery read and at checkout — a fix this app knows
     * about and the server does not is not a delivery address, it is a
     * disagreement waiting to surface as a refusal at the end of a basket.
     */
    const useCurrentPosition = async () => {
        setUsing(true);
        try {
            let fix = deviceFix;
            if (!fix) {
                await requestLocation();
                fix = useLocation.getState().location?.coords
                    ? {
                          lat: useLocation.getState().location!.coords.latitude,
                          lng: useLocation.getState().location!.coords.longitude,
                      }
                    : null;
            }
            if (!fix) {
                Toast.error(
                    "Couldn't read your location",
                    'Turn on location for Drop, or search for your address instead.',
                );
                return;
            }
            await updateLocation.mutateAsync({ lat: fix.lat, lng: fix.lng });
            // Best effort — the address is a label. Failing to name the place is
            // not a reason to refuse a position the server has already accepted.
            reverseGeocode(fix.lat, fix.lng).catch(() => {});
            Toast.success('Location set', 'Showing the stores that deliver to you.');
        } catch (err) {
            Toast.error("Couldn't save your location", errorMessage(err));
        } finally {
            setUsing(false);
        }
    };

    const busy = using || locating || updateLocation.isPending;

    return (
        <View className="px-5 pt-6 pb-10 items-center">
            <View
                className={`w-full rounded-3xl px-6 py-8 items-center border ${
                    darkTheme ? 'bg-surface-container border-outline-variant' : 'bg-white border-gray-100'
                }`}
                style={
                    darkTheme
                        ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 }
                        : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }
                }
            >
                <View
                    className="w-16 h-16 rounded-full items-center justify-center mb-4"
                    style={{ backgroundColor: BRAND.primary + '15' }}
                >
                    <Ionicons name="location-outline" size={32} color={BRAND.primary} />
                </View>

                <Text
                    className={`font-heading text-xl text-center ${darkTheme ? 'text-on-surface' : 'text-gray-900'}`}
                >
                    Where should we deliver?
                </Text>
                <Text
                    className={`text-sm text-center mt-2 leading-5 ${
                        darkTheme ? 'text-on-surface-variant' : 'text-gray-500'
                    }`}
                >
                    {/* No figures here. The radius is a settings row —
                        `retail_max_distance_km` / `wholesale_max_distance_km` —
                        and this app is not one of the places allowed to state
                        it. Quoting "2.5 km" and "15 km" in copy meant the
                        sentence became false the moment an administrator moved
                        either one, on the screen whose whole job is to explain
                        why the address matters. The rider app hit the same
                        thing in a sentence of its own, which is why
                        `operation_radius_km` is served to it; there is no
                        equivalent field for a customer, and the customer does
                        not need the number — they need the reason. */}
                    Drop only shows you shops that can actually reach your address,
                    so we need to know where you are.
                </Text>

                <View className="w-full mt-6 gap-3">
                    <DropButton
                        title={busy ? 'Getting your location…' : 'Use my current location'}
                        onPress={useCurrentPosition}
                        disabled={busy}
                        style="py-3.5"
                    />

                    <PressableScale
                        accessibilityLabel="Search for a delivery address"
                        onPress={() => router.push('/(screens)/LocationSearch')}
                        disabled={busy}
                    >
                        <View
                            className={`flex-row items-center justify-center gap-2 py-3.5 rounded-2xl border ${
                                darkTheme ? 'border-outline-variant' : 'border-gray-200'
                            }`}
                        >
                            <Ionicons name="search-outline" size={18} color={BRAND.primary} />
                            <Text className="font-sans-semibold text-sm" style={{ color: BRAND.primary }}>
                                Search for an address
                            </Text>
                        </View>
                    </PressableScale>
                </View>

                {busy && (
                    <View className="mt-4">
                        <ActivityIndicator size="small" color={BRAND.primary} />
                    </View>
                )}
            </View>
        </View>
    );
}

/**
 * The other bad-news state: we know where the customer is, and nothing trades
 * there yet.
 *
 * Deliberately a different component with different words from the one above.
 * Merging them is what produced "Limited Coverage Area" for a brand-new
 * customer who had simply not been asked yet.
 */
export function NoStoresInRange({ address }: { address: string | null }) {
    const router = useRouter();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === 'dark';

    return (
        <View className="px-5 pt-6 pb-10 items-center">
            <View
                className={`w-full rounded-3xl px-6 py-8 items-center border ${
                    darkTheme ? 'bg-surface-container border-outline-variant' : 'bg-white border-gray-100'
                }`}
            >
                <View
                    className="w-16 h-16 rounded-full items-center justify-center mb-4"
                    style={{ backgroundColor: BRAND.primary + '15' }}
                >
                    <Ionicons name="storefront-outline" size={32} color={BRAND.primary} />
                </View>

                <Text
                    className={`font-heading text-xl text-center ${darkTheme ? 'text-on-surface' : 'text-gray-900'}`}
                >
                    We're not in your area yet
                </Text>
                <Text
                    className={`text-sm text-center mt-2 leading-5 ${
                        darkTheme ? 'text-on-surface-variant' : 'text-gray-500'
                    }`}
                >
                    {address
                        ? `No stores deliver to ${address} right now. If you're somewhere else today, change your address to see what's nearby.`
                        : "No stores deliver to your address right now. If you're somewhere else today, change your address to see what's nearby."}
                </Text>

                <View className="w-full mt-6">
                    <PressableScale
                        accessibilityLabel="Change delivery address"
                        onPress={() => router.push('/(screens)/LocationSearch')}
                    >
                        <View
                            className={`flex-row items-center justify-center gap-2 py-3.5 rounded-2xl border ${
                                darkTheme ? 'border-outline-variant' : 'border-gray-200'
                            }`}
                        >
                            <Ionicons name="location-outline" size={18} color={BRAND.primary} />
                            <Text className="font-sans-semibold text-sm" style={{ color: BRAND.primary }}>
                                Change delivery address
                            </Text>
                        </View>
                    </PressableScale>
                </View>
            </View>
        </View>
    );
}
