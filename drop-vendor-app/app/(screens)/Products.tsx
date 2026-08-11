import { errorMessage } from "@/API/errors";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { Toast } from "@/lib/toast";
import { PERMISSIONS, useCan } from "@/hooks/queries/useVendorProfile";
import { useRouter } from "expo-router";
import React, { useCallback, useContext, useEffect, useState, memo } from "react";
import {
    RefreshControl,
    ScrollView,
    StatusBar,
    View,
    Switch,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { FlashList } from "@shopify/flash-list";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import PressableScale from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import * as Haptics from "expo-haptics";
import { trackEvent } from "@/utils/analytics";
import { Popup } from "@/lib/popup";
import SearchBar from "@/components/common/Search";
import { EmptyState } from "@/components/ui/EmptyState";
import { useVendorProducts } from "@/hooks/queries/useVendorProducts";
import { useDebounce } from "@/hooks/useDebounce";
import { formatMoney } from "@/utils/money";

const ProductCard = memo(({ item, darkTheme, canEdit, onDelete, onEdit, onToggleAvailability, onUpdateStock }: { item: any, darkTheme: boolean, canEdit: boolean, onDelete: (id: string) => void, onEdit: (id: string) => void, onToggleAvailability: (id: string, isAvailable: boolean) => void, onUpdateStock: (id: string, newStock: number) => void }) => {
  return (
    <View 
      className={`flex-row items-center p-5 mb-4 rounded-[24px] border shadow-sm ${item.stock === 0 ? "opacity-60" : ""} ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"}`} 
      style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
    >
      <View className="flex-1">
        <View className="flex-row items-center gap-2 mb-2">
          <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-slate-900"}`}>
            {item.name}
          </Text>
          {/* Against this product's own threshold, not a hardcoded 5. A vendor
              selling 200 refills a day and one selling a dispenser a month
              cannot share a definition of "low". */}
          {item.stock === 0 ? (
            <View className="bg-red-500/10 border border-red-500/20 px-2 py-1 rounded-md">
              <Text className="text-red-600 text-[10px] font-sans-bold uppercase">Out of Stock</Text>
            </View>
          ) : item.low_stock_threshold > 0 && item.stock <= item.low_stock_threshold ? (
            <View className="bg-amber-500/10 border border-amber-500/20 px-2 py-1 rounded-md">
              <Text className="text-amber-600 text-[10px] font-sans-bold uppercase">Low Stock</Text>
            </View>
          ) : null}
        </View>
        <View className="flex-row items-center gap-4">
          <Text className={`text-base font-sans-semibold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
            {formatMoney(item.price)}
          </Text>
          <View className="w-1 h-1 rounded-full bg-slate-300" />
          <View className="flex-row items-center gap-3 bg-slate-100 dark:bg-slate-800/50 rounded-lg p-1">
            <PressableScale accessibilityLabel={`One fewer ${item.name} in stock`} disabled={!canEdit} onPress={() => onUpdateStock(item.id, Math.max(0, item.stock - 1))} className={`w-6 h-6 rounded-md items-center justify-center ${!canEdit ? "opacity-40" : ""} ${darkTheme ? "bg-slate-700" : "bg-white shadow-sm"}`}>
              <Ionicons name="remove" size={14} color={darkTheme ? "white" : "black"} />
            </PressableScale>
            <Text className={`text-sm font-sans-bold ${item.low_stock_threshold > 0 && item.stock <= item.low_stock_threshold ? "text-red-500" : darkTheme ? "text-white" : "text-slate-900"}`}>
              {item.stock}
            </Text>
            <PressableScale accessibilityLabel={`One more ${item.name} in stock`} disabled={!canEdit} onPress={() => onUpdateStock(item.id, item.stock + 1)} className={`w-6 h-6 rounded-md items-center justify-center ${!canEdit ? "opacity-40" : ""} ${darkTheme ? "bg-slate-700" : "bg-white shadow-sm"}`}>
              <Ionicons name="add" size={14} color={darkTheme ? "white" : "black"} />
            </PressableScale>
          </View>
        </View>
      </View>
      
      <View className="flex-row items-center gap-3">
        <Switch
          value={item.is_available}
          disabled={!canEdit}
          onValueChange={(val) => onToggleAvailability(item.id, val)}
          trackColor={{ false: darkTheme ? "#333" : "#e2e8f0", true: BRAND.primary }}
          thumbColor={item.is_available ? "#fff" : "#f4f3f4"}
          style={{ transform: [{ scaleX: 0.8 }, { scaleY: 0.8 }] }}
        />
        {canEdit && (
          <>
            <PressableScale accessibilityLabel={`Edit ${item.name}`}
              onPress={() => onEdit(item.id)}
              className={`w-10 h-10 rounded-full items-center justify-center ${darkTheme ? "bg-blue-900/20" : "bg-blue-50"}`}
            >
              <Ionicons name="pencil-outline" size={18} color="#3b82f6" />
            </PressableScale>
            <PressableScale accessibilityLabel={`Withdraw ${item.name} from your catalogue`}
              onPress={() => onDelete(item.id)}
              className={`w-10 h-10 rounded-full items-center justify-center ${darkTheme ? "bg-red-900/20" : "bg-red-50"}`}
            >
              <Ionicons name="trash-outline" size={18} color="#ef4444" />
            </PressableScale>
          </>
        )}
      </View>
    </View>
  );
});

export default function Products() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { del, put } = useApiRequest();
  // A staff member may be allowed to take orders without being allowed to
  // reprice the catalogue. The server enforces it; this stops the app offering
  // buttons that would only ever return 403.
  const canEdit = useCan(PERMISSIONS.manageProducts);
  const router = useRouter();

  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearchQuery = useDebounce(searchQuery, 500);
  const [searchState, setSearchState] = useState("");

  const {
    data: productsData,
    isFetching: productLoading,
    fetchNextPage: fetchNextProducts,
    hasNextPage: hasNextProducts,
    refetch,
    isError
  } = useVendorProducts(searchState, filter, 20);

  // `page.items` — the server no longer pretends to be an `InfiniteData`.
  const filteredProducts = productsData?.pages?.flatMap((page) => page.items ?? []) || [];

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await refetch();
    setRefreshing(false);
  }, [refetch]);

  const handleDelete = useCallback(async (productId: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    Popup.show({
      title: "Delete Product",
      message: "Are you sure you want to permanently delete this product?",
      cancelText: "Cancel",
      confirmText: "Delete",
      isDestructive: true,
      onConfirm: async () => {
          Popup.hide();
          try {
            await del(VendorApiRoutes.DeleteProduct(productId).path);
            await refetch();
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          } catch (e) {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            // The old version never checked the response at all: a refused
            // delete refetched, the product reappeared, and the vendor was told
            // nothing. A product still on sale that the vendor believes is gone
            // is an order they cannot fulfil.
            Toast.error("Couldn't delete", errorMessage(e, "That product is still there. Please try again."));
          }
        }
    });
  }, [del, refetch]);

  const handleToggleAvailability = useCallback(async (productId: string, isAvailable: boolean) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await put(VendorApiRoutes.UpdateProduct(productId).path, { is_available: isAvailable });
      await refetch();
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      // The switch has already moved. Refetching puts it back where the server
      // says it is; without the toast the vendor reads that as a UI glitch and
      // keeps selling something they believe they took offline.
      await refetch();
      Toast.error("Couldn't update", errorMessage(e, "That change didn't save. Please try again."));
    }
  }, [put, refetch]);

  const handleUpdateStock = useCallback(async (productId: string, newStock: number) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await put(VendorApiRoutes.UpdateProduct(productId).path, { stock: newStock });
      await refetch();
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      await refetch();
      Toast.error("Couldn't update stock", errorMessage(e, "That change didn't save. Please try again."));
    }
  }, [put, refetch]);

  useEffect(() => {
    if (debouncedSearchQuery.trim().length > 1) {
      setSearchState(debouncedSearchQuery.trim());
      trackEvent('vendor_inventory_search', { query: debouncedSearchQuery.trim(), count: filteredProducts.length });
    } else {
      setSearchState("");
    }
  }, [debouncedSearchQuery, filteredProducts.length]);

  const renderItem = useCallback(({ item }: { item: any }) => (
    <ProductCard item={item} darkTheme={darkTheme} canEdit={canEdit} onDelete={handleDelete} onEdit={(id) => router.push(`/(screens)/EditProduct/${id}` as any)} onToggleAvailability={handleToggleAvailability} onUpdateStock={handleUpdateStock} />
  ), [darkTheme, canEdit, handleDelete, handleToggleAvailability, handleUpdateStock, router]);

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />

      {/* Header and Search */}
      <View style={{ overflow: "hidden", paddingBottom: 4 }}>
        <View 
          className="pt-4 pb-4 mb-2 gap-3"
          style={{ 
            backgroundColor: darkTheme ? "#000" : "#fff",
            borderBottomWidth: 1, 
            borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
            ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
          }}
        >
          <View className="flex-row items-center px-4">
            <PressableScale accessibilityLabel="Go Back" onPress={() => router.back()} activeOpacity={0.6}>
              <BackButtonMinimal />
            </PressableScale>
            <SearchBar
              width="flex-1 ml-3"
              height="h-[50px]"
              buttonStyle=""
              setFunc={setSearchQuery}
            />
          </View>
          
          {/* Filter Chips positioned directly below SearchBar */}
          <View className="pt-2">
            <ScrollView 
              horizontal 
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: 20, gap: 8 }}
            >
              {[
                { id: "All", label: "All Products" }, 
                { id: "Low Stock", label: "Low Stock" }, 
                { id: "Out of Stock", label: "Out of Stock" }
              ].map(f => (
                <PressableScale
                  key={f.id}
                  onPress={() => {
                    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setFilter(f.id);
                  }}
                  className={`px-4 py-2 rounded-full border ${filter === f.id ? "bg-accentbg border-accentbg" : darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}
                  style={filter !== f.id ? { ...(darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : {}}
                >
                  <Text className={`font-sans-semibold text-sm ${filter === f.id ? "text-white" : darkTheme ? "text-gray-300" : "text-gray-600"}`}>
                    {f.label}
                  </Text>
                </PressableScale>
              ))}
            </ScrollView>
          </View>
        </View>
      </View>

      <View style={{ flex: 1 }}>
        <FlashList
          data={filteredProducts}
          keyExtractor={(item: any) => item.id}
          // @ts-ignore
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={darkTheme ? "white" : "black"} />}
          contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 120, paddingTop: 8 }}
          onEndReached={() => {
            if (hasNextProducts) fetchNextProducts();
          }}
          onEndReachedThreshold={0.5}
          ListEmptyComponent={
            productLoading && filteredProducts.length === 0 && !isError ? (
               <View className="gap-4 w-full pt-4">
                 <SkeletonRow />
                 <SkeletonRow />
                 <SkeletonRow />
                 <SkeletonRow />
              </View>
            ) : (
              <View className="mt-16">
                <EmptyState 
                  mood="sad" 
                  title="No products found" 
                  subtitle={searchQuery ? "Try adjusting your search filters" : "Add your first product to start selling"} 
                />
              </View>
            )
          }
          renderItem={renderItem}
        />
      </View>

      {/* Floating Action Button (FAB) — only for someone who may use it. */}
      {canEdit && (
        <PressableScale accessibilityLabel="Add a product"
          activeOpacity={0.8}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            router.push("/(screens)/AddProduct");
          }}
          className="absolute right-5 bottom-[100px] bg-accentbg w-14 h-14 rounded-2xl items-center justify-center"
          style={{ ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
        >
          <Ionicons name="add" size={28} color="white" />
        </PressableScale>
      )}
    </SafeAreaView>
  );
}
