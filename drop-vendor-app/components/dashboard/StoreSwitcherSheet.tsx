import React, { forwardRef, useCallback, useContext, useImperativeHandle, useMemo, useRef } from 'react';
import { View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { BottomSheetModal, BottomSheetBackdrop, BottomSheetView } from '@gorhom/bottom-sheet';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND } from '@/constants/brandColors';
import { useVendorStores } from '@/hooks/queries/useVendorProfile';
import PressableScale from '@/components/ui/PressableScale';
import { Ionicons } from '@expo/vector-icons';

import { Skeleton } from '@/components/ui/Skeleton';

export interface StoreSwitcherSheetRef {
  open: () => void;
  close: () => void;
}

interface StoreSwitcherSheetProps {
  /** `null` means "no explicit choice yet" — the backend then uses the first. */
  activeStoreId?: string | null;
  onSelectStore: (storeId: string) => void;
}

const StoreSwitcherSheet = forwardRef<StoreSwitcherSheetRef, StoreSwitcherSheetProps>(
  ({ activeStoreId, onSelectStore }, ref) => {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === 'dark';
    const bottomSheetRef = useRef<BottomSheetModal>(null);
    const snapPoints = useMemo(() => ['40%', '60%'], []);

    const { data: stores, isLoading } = useVendorStores();

    useImperativeHandle(ref, () => ({
      open: () => bottomSheetRef.current?.present(),
      close: () => bottomSheetRef.current?.dismiss(),
    }));

    const renderBackdrop = useCallback(
      (props: any) => (
        <BottomSheetBackdrop {...props} disappearsOnIndex={-1} appearsOnIndex={0} opacity={0.5} />
      ),
      []
    );

    const handleSelect = (storeId: string) => {
      onSelectStore(storeId);
      bottomSheetRef.current?.dismiss();
    };

    return (
      <BottomSheetModal
        ref={bottomSheetRef}
        snapPoints={snapPoints}
        backdropComponent={renderBackdrop}
        enablePanDownToClose
        backgroundStyle={{
          backgroundColor: darkTheme ? '#1c1b1b' : '#ffffff',
          borderTopLeftRadius: 24,
          borderTopRightRadius: 24,
        }}
        handleIndicatorStyle={{
          backgroundColor: darkTheme ? BRAND.gray500 : BRAND.gray300,
          width: 40,
        }}
      >
        <BottomSheetView style={{ flex: 1, paddingHorizontal: 20 }}>
          {/* Header */}
          <View className="flex-row items-center justify-between mb-4 pt-1">
            <Text className={`text-xl font-sans-bold ${darkTheme ? 'text-white' : 'text-gray-900'}`}>
              Your Stores
            </Text>
            <PressableScale accessibilityLabel="Close the store list" onPress={() => bottomSheetRef.current?.dismiss()}>
              <View className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? 'bg-surface-container-high' : 'bg-white'}`}>
                <Ionicons name="close" size={18} color={BRAND.primary} />
              </View>
            </PressableScale>
          </View>

          {/* Store List */}
          {isLoading ? (
            <View className="items-center justify-center py-4 w-full gap-2">
              <Skeleton width="100%" height={76} borderRadius={16} />
              <Skeleton width="100%" height={76} borderRadius={16} />
            </View>
          ) : !stores || stores.length === 0 ? (
            <View className="items-center justify-center py-8">
              <Ionicons name="storefront-outline" size={48} color={BRAND.primary} />
              <Text className={`mt-3 text-base font-sans-medium ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>
                No additional stores found
              </Text>
              <Text className={`mt-1 text-sm text-center ${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}>
                You're currently managing your only store.
              </Text>
            </View>
          ) : (
            stores.map((store: any, index: number) => {
              const isActive = store.id === activeStoreId || (!activeStoreId && index === 0);
              return (
                <PressableScale key={store.id || index} onPress={() => handleSelect(store.id)}>
                  <View
                    className={`flex-row items-center p-4 mb-2 rounded-2xl border ${
                      isActive
                        ? darkTheme ? 'border-primary bg-primary/10' : 'border-primary bg-blue-50'
                        : darkTheme ? 'border-outline-variant bg-surface-container' : 'border-gray-200 bg-white'
                    }`}
                  >
                    {/* Store Icon */}
                    <View
                      className={`w-12 h-12 rounded-full items-center justify-center mr-3 ${
                        isActive
                          ? 'bg-primary'
                          : darkTheme ? 'bg-surface-container-high' : 'bg-white'
                      }`}
                    >
                      <Ionicons
                        name="storefront"
                        size={22}
                        color={isActive ? '#ffffff' : (darkTheme ? BRAND.gray400 : BRAND.gray500)}
                      />
                    </View>

                    {/* Store Info */}
                    <View className="flex-1">
                      <Text
                        numberOfLines={1}
                        className={`text-base font-sans-bold ${
                          isActive
                            ? darkTheme ? 'text-white' : 'text-gray-900'
                            : darkTheme ? 'text-on-surface' : 'text-gray-800'
                        }`}
                      >
                        {store.business_name || 'Unnamed Store'}
                      </Text>
                      <Text
                        numberOfLines={1}
                        className={`text-sm mt-0.5 ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}
                      >
                        {store.location_address || 'No address set'}
                      </Text>
                    </View>

                    {/* Active indicator */}
                    {isActive && (
                      <View className="w-6 h-6 rounded-full bg-primary items-center justify-center">
                        <Ionicons name="checkmark" size={14} color="#ffffff" />
                      </View>
                    )}
                  </View>
                </PressableScale>
              );
            })
          )}

          {/* Footer hint */}
          <View className="items-center pt-4 pb-6">
            <Text className={`text-xs ${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}>
              Tap a store to switch your active dashboard
            </Text>
          </View>
        </BottomSheetView>
      </BottomSheetModal>
    );
  }
);

StoreSwitcherSheet.displayName = 'StoreSwitcherSheet';
export default StoreSwitcherSheet;
