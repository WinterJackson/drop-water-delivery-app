import { UIThemeContext } from "@/context/ThemeContext";
import { useSubmitReview } from "@/hooks/queries/useReviews";
import { useAuth } from "@clerk/clerk-expo";
import { useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useContext, useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StatusBar, View, ActivityIndicator } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { BRAND } from "@/constants/brandColors";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { Toast } from "@/lib/toast";
import { PressableScale } from "@/components/ui/PressableScale";

/**
 * At module scope, not inside the screen.
 *
 * A component declared in a render body is a new function object — and so a new
 * component *type* — on every render, which makes React unmount its subtree and
 * mount a fresh one instead of updating it. Even with no input and no state of
 * its own that is not free: every child is torn down and rebuilt, `PressableScale`
 * restarts its animation, and the reconciler does the most expensive kind of work
 * on the most ordinary re-render.
 *
 * What it closed over is passed in instead.
 */
const RatingStars = ({ rating, setRating, darkTheme }: { rating: number, setRating: (r: number) => void } & { darkTheme: boolean }) => {
    return (
        <View className="flex-row gap-2 mt-3">
            {[1, 2, 3, 4, 5].map((star) => (
                <PressableScale key={star} onPress={() => setRating(star)}>
                    <Text style={{ fontSize: 36, color: star <= rating ? "#FFD700" : (darkTheme ? "#4B5563" : "#D1D5DB") }}>
                        ★
                    </Text>
                </PressableScale>
            ))}
        </View>
    );
};

const RateOrder = () => {
    const { currentTheme } = useContext<any>(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const { orderId, vendorId, riderId } = useLocalSearchParams();
    const router = useRouter();
    const { getToken } = useAuth();
    
    const [vendorRating, setVendorRating] = useState(0);
    const [riderRating, setRiderRating] = useState(0);
    const [comment, setComment] = useState("");
    const [loading, setLoading] = useState(false);
    const queryClient = useQueryClient();

    const { mutateAsync: mutateReview } = useSubmitReview();

    const submitReview = async (targetType: "vendor" | "rider", targetId: string, rating: number) => {
        if (rating === 0) return true; // Skip if no rating selected
        if (!targetId) return true; // Safety check
        try {
            await mutateReview({
                order_id: orderId as string,
                target_type: targetType,
                target_id: targetId,
                rating: rating,
                comment: comment
            });
            return true;
        } catch (e) {
            if (__DEV__) console.error("Review submission failed:", e);
            return false;
        }
    };

    const handleRate = async () => {
        if (vendorRating === 0 && riderRating === 0) {
            Toast.error("Please select a rating before submitting.");
            return;
        }
        setLoading(true);
        let vendorSuccess = true;
        let riderSuccess = true;

        if (vendorId && vendorRating > 0) {
            vendorSuccess = await submitReview("vendor", vendorId as string, vendorRating);
        }
        if (riderId && riderRating > 0) {
            riderSuccess = await submitReview("rider", riderId as string, riderRating);
        }

        setLoading(false);
        if (vendorSuccess && riderSuccess) {
            Toast.success("Thank you for your feedback!");
            // React Query prefix-matches from the *start* of the key. Orders are
            // cached under ['customer', 'orders', userId], so `['orders']` matched
            // nothing and the list never refreshed — the rated order kept its
            // "Rate Delivery" action and could be submitted again.
            queryClient.invalidateQueries({ queryKey: ['customer', 'orders'] });
            router.back();
        } else {
            Toast.error("Failed to submit some reviews. Please try again.");
        }
    };

    const ratingStarsProps = { darkTheme };

    return (
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
            <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
            
            <View style={{ overflow: "hidden", paddingBottom: 4 }}>
            <View 
                className="flex-row items-center px-4 py-3 pb-4 mb-2 gap-3"
                style={{ 
                    backgroundColor: darkTheme ? "#000" : "#fff",
                    borderBottomWidth: 1, 
                    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
                }}
            >
                <PressableScale onPress={() => router.back()} activeOpacity={0.7}>
                    <BackButtonMinimal />
                </PressableScale>
                <Text className={`font-sans-bold text-xl ${darkTheme ? "text-white" : "text-black"}`}>
                    Rate Your Delivery
                </Text>
            </View>
            </View>

            <ScrollView className="flex-1 px-5" contentContainerStyle={{ paddingVertical: 20, paddingBottom: 120}}>
                {vendorId && (
                    <View className={`mb-8 p-6 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                        <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>Vendor Rating</Text>
                        <Text className={`mt-2 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>How was the product quality and packaging?</Text>
                        <RatingStars {...ratingStarsProps} rating={vendorRating} setRating={setVendorRating} />
                    </View>
                )}

                {riderId && (
                    <View className={`mb-8 p-6 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                        <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>Rider Rating</Text>
                        <Text className={`mt-2 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>How was the delivery speed and service?</Text>
                        <RatingStars {...ratingStarsProps} rating={riderRating} setRating={setRiderRating} />
                    </View>
                )}

                <View className={`mb-8 p-6 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                    <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>Written Feedback (Optional)</Text>
                    <TextInput
                        className={`mt-4 p-4 rounded-xl border ${darkTheme ? "bg-black/50 border-gray-800 text-white" : "bg-white border-gray-200 text-black"}`}
                        placeholder="Tell us more about your experience..."
                        placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                        multiline
                        numberOfLines={4}
                        textAlignVertical="top"
                        value={comment}
                        onChangeText={setComment}
                    />
                </View>

                <PressableScale 
                    activeOpacity={0.8}
                    onPress={handleRate}
                    disabled={loading}
                    className={`mt-6 py-4 rounded-2xl flex-row justify-center items-center ${loading ? "bg-accentbg/50" : "bg-accentbg"}`}
                >
                    {loading ? (
                        <ActivityIndicator color={BRAND.white} />
                    ) : (
                        <Text className="text-white font-sans-bold text-lg">Submit Ratings</Text>
                    )}
                </PressableScale>
            </ScrollView>
        </SafeAreaView>
        </KeyboardAvoidingView>
    );
};
export default RateOrder;
