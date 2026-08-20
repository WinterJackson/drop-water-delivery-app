import React, { useContext, useState } from "react";
import { View, ScrollView } from "react-native";
import { Text } from '@/components/ui/Text';
import { Image as ExpoImage } from "expo-image";
import { useRouter } from "expo-router";
import { PressableScale } from "@/components/ui/PressableScale";
import { UIThemeContext } from "@/context/ThemeContext";
import DropButton from "@/components/ui/DropButton";
import { Ionicons } from "@expo/vector-icons";
import { useVendorFavorites, useRemoveVendorFavorite } from "@/hooks/queries/useVendorFavorites";
import { usePopupStore } from "@/stores/popupStore";
import { BRAND, TOAST } from "@/constants/brandColors";
import { Skeleton } from "@/components/ui/Skeleton";
import { FavoriteVendorSkeleton } from "@/components/skeletons/ContextualSkeletons";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";
import { ratingLabel } from "@/utils/rating";
export default function FavouritesList() {
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const [selectedFavId, setSelectedFavId] = useState<string | null>(null);

  const { data: favorites = [], isLoading } = useVendorFavorites();
  const removeFavorite = useRemoveVendorFavorite();
  const showPopup = usePopupStore((state) => state.show);
  const hidePopup = usePopupStore((state) => state.hide);

  /**
   * Removing a favourite, asked for before it happens.
   *
   * There was no way to remove one at all — a customer could add a shop to this
   * rail and never take it off, so a store they had stopped using, or one that
   * had closed for good, sat at the top of their home screen permanently.
   *
   * Confirmed rather than instant, because there is no undo affordance in this
   * app's toast and a horizontal chip rail is the easiest place in the whole UI
   * to hit the wrong row. `PopupModal` is themed on both grounds, traps focus
   * and is what every other destructive action here already uses — the platform
   * has removed native `confirm()` from the console for exactly these reasons,
   * and the same reasoning applies on a handset.
   */
  const confirmRemove = (vendorId: string, name: string) => {
    showPopup({
      title: "Remove favourite?",
      message: `${name} will be taken off your favourites. You can add it back from the store's page at any time.`,
      confirmText: "Remove",
      cancelText: "Keep",
      isDestructive: true,
      onConfirm: () => {
        hidePopup();
        // Clear the selection first: the action panel below is keyed on it, and
        // the optimistic removal takes the row out from under it in the same
        // tick. Left set, the panel renders against a vendor that is no longer
        // in the list.
        setSelectedFavId(null);
        removeFavorite.mutate(vendorId);
      },
    });
  };

  const handleSelect = (vendorId: string) => {
    if (selectedFavId === vendorId) {
      setSelectedFavId(null);
    } else {
      setSelectedFavId(vendorId);
    }
  };

  // Don't render the section at all if user has no favourites and data has loaded
  if (!isLoading && favorites.length === 0) {
    return null;
  }

  // Get the selected vendor object
  const selectedVendor = favorites.find(fav => fav.vendor_id === selectedFavId)?.vendor;

  return (
    <View className="flex-col gap-4 mt-2">
      <View className="px-5 py-3 flex-row items-center justify-between">
        <Text className={`font-sans-bold text-lg tracking-wide ${darkTheme ? "text-white" : "text-gray-900"}`}>
          Your Favourites
        </Text>
        <Ionicons name="star" size={20} color={BRAND.primary} />
      </View>

      {isLoading ? (
        <ScrollView 
          horizontal 
          showsHorizontalScrollIndicator={false} 
          contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 4 }}
        >
          <FavoriteVendorSkeleton />
          <FavoriteVendorSkeleton />
          <FavoriteVendorSkeleton />
        </ScrollView>
      ) : (
        <ScrollView 
          horizontal 
          showsHorizontalScrollIndicator={false} 
          contentContainerStyle={{ paddingHorizontal: 20, gap: 12, paddingBottom: 4 }}
        >
          {favorites.map((fav) => {
            const isSelected = selectedFavId === fav.vendor_id;
            const vendor = fav.vendor;
            
            return (
              <PressableScale
                // Keyed on the vendor, not the favourite row. `id` is
                // `temp-<vendorId>` while an optimistic add is in flight and
                // the server's id once it settles, so keying on it changes the
                // key under a chip that is already on screen and React
                // remounts it. `vendor_id` is stable across that swap, unique
                // per row (a favourite is one user-vendor pair), and is
                // already the identity `selectedFavId` is compared against.
                key={fav.vendor_id}
                accessibilityLabel={`${vendor?.business_name || "Favourite vendor"}. Long press to remove from favourites.`}
                onPress={() => handleSelect(fav.vendor_id)}
                onLongPress={() => confirmRemove(fav.vendor_id, vendor?.business_name || "This vendor")}
                delayLongPress={400}
              >
                <View 
                  className={`flex-row items-center gap-3 px-3 py-2 rounded-full ${darkTheme ? "bg-surface-container" : "bg-white"}`}
                  style={{
                    borderWidth: isSelected ? 1.5 : 1,
                    borderColor: isSelected ? BRAND.primary : (darkTheme ? BRAND.gray800 : BRAND.gray200),
                    shadowColor: isSelected ? BRAND.primary : (darkTheme ? "#000" : BRAND.gray800),
                    shadowOffset: { width: 0, height: isSelected ? 3 : 1 },
                    shadowOpacity: isSelected ? 0.3 : 0.05,
                    shadowRadius: isSelected ? 5 : 2,
                    elevation: isSelected ? 4 : 1,
                  }}
                >
                  <View className="relative w-10 h-10 rounded-full">
                    {vendor?.profile_pic ? (
                      <ExpoImage
                        source={{ uri: vendor.profile_pic }}
                        className="w-full h-full rounded-full"
                        contentFit="cover"
                        cachePolicy="disk"
                      />
                    ) : (
                      <View className="w-full h-full rounded-full items-center justify-center" style={{ backgroundColor: BRAND.gray200 }}>
                        <Ionicons name="storefront-outline" size={18} color={BRAND.gray500} />
                      </View>
                    )}
                    {/* The heart marks the row; it does not remove it. A tap
                        target this small, on a rail people scroll through, is
                        where an accidental destructive tap comes from — so the
                        removal lives in the panel below and on long press. */}
                    <View 
                      className={`absolute -bottom-1 -right-1 rounded-full p-[2px]`}
                      style={{ backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white }}
                    >
                      <Ionicons name="heart" size={12} color={BRAND.primary} />
                    </View>
                  </View>
                  
                  <View className="flex-col justify-center pr-2">
                    <Text 
                      className={`text-sm font-sans-semibold ${darkTheme ? "text-white" : "text-gray-900"}`} 
                      numberOfLines={1}
                    >
                      {vendor?.business_name || "Vendor"}
                    </Text>
                    {isSelected && (
                      <Text className={`text-[10px] font-sans-medium ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        {ratingLabel(vendor?.rating, vendor?.rating_count)}
                      </Text>
                    )}
                  </View>
                </View>
              </PressableScale>
            );
          })}
        </ScrollView>
      )}

      {/* Premium Action Panel */}
      {selectedFavId && selectedVendor && (
        <View className="px-5 py-2">
          <View 
            className="rounded-2xl p-4 flex-col gap-4"
            style={{
              backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white,
              borderWidth: 1,
              borderColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
              ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }),
            }}
          >
            <View className="flex-row items-center justify-between">
              <View className="flex-row items-center gap-3 flex-1">
                <View className="w-8 h-8 rounded-full items-center justify-center" style={{ backgroundColor: BRAND.primary + '15' }}>
                  <Ionicons name="time-outline" size={18} color={BRAND.primary} />
                </View>
                <View className="flex-1">
                  <Text className={`text-sm font-sans-bold ${darkTheme ? "text-white" : "text-gray-900"}`} numberOfLines={1}>
                    Reorder from {selectedVendor.business_name}
                  </Text>
                  {/* "Skip the cart and order your usual immediately" is a
                      promise, and against a shut shop it is one the platform
                      cannot keep. Favourites is where this matters most: the
                      customer already knows which store they want, so the only
                      thing on the card worth reading is whether it is open. */}
                  {selectedVendor.is_accepting_orders === false ? (
                    <View className="mt-0.5">
                      <StoreClosedNotice store={selectedVendor} compact />
                    </View>
                  ) : (
                    <Text className={`text-xs mt-0.5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                      Skip the cart and order your usual immediately.
                    </Text>
                  )}
                </View>
              </View>
            </View>

            <View className="flex-row items-center gap-3">
              <View className="flex-1">
                <DropButton
                  title="Repeat Last Order"
                  onPress={() => router.push(`/(screens)/repeat-order?vendorId=${selectedFavId}`)}
                  style="shadow-sm shadow-primary/30 py-3"
                />
              </View>

              {/* Icon-only, so it carries its own label: React Native names a
                  touchable from its `<Text>` children, and this has none. */}
              <PressableScale
                accessibilityLabel={`Remove ${selectedVendor.business_name} from favourites`}
                onPress={() => confirmRemove(selectedFavId, selectedVendor.business_name)}
                disabled={removeFavorite.isPending}
              >
                <View
                  className="w-12 h-12 rounded-2xl items-center justify-center border"
                  style={{
                    borderColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                    opacity: removeFavorite.isPending ? 0.5 : 1,
                  }}
                >
                  <Ionicons name="heart-dislike-outline" size={20} color={TOAST.error} />
                </View>
              </PressableScale>
            </View>
          </View>
        </View>
      )}
    </View>
  );
}
