import React, { useContext } from "react";
import { useTabBarClearance } from '@/constants/layout';
import { View, ScrollView, StatusBar, TouchableOpacity } from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { BRAND, TOAST } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
import { useRiderReviews } from "@/hooks/queries/useRiderData";
import { RiderReviewsSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { ratingScore, filledStars, UNRATED_LABEL } from "@/utils/rating";

export default function Reviews() {
    const tabBarClearance = useTabBarClearance();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const router = useRouter();
  const { data: reviewsData, isLoading, isError, refetch } = useRiderReviews();

  const renderDistributionBar = (stars: number, count: number, total: number) => {
    const percentage = total > 0 ? (count / total) * 100 : 0;
    return (
      <View key={stars} className="flex-row items-center mb-2">
        <Text className={`w-4 font-sans-bold ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>{stars}</Text>
        <Ionicons name="star" size={12} color="#F59E0B" style={{ marginRight: 8 }} />
        <View className="flex-1 h-2 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
          <View className="h-full bg-yellow-500 rounded-full" style={{ width: `${percentage}%` }} />
        </View>
        <Text className={`w-8 text-right text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{count}</Text>
      </View>
    );
  };

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />

      {/* Header */}
      <View style={{ overflow: "hidden", paddingBottom: 4, zIndex: 30 }}>
          <View 
              className="flex-row items-center px-4 py-3 pb-4 mb-2"
              style={{ 
                  backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
                  borderBottomWidth: 1, 
                  borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                  ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
              }}
          >
              <TouchableOpacity onPress={() => router.back()} className="mr-4">
                  <BackButtonMinimal />
              </TouchableOpacity>
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                  Customer Feedback
              </Text>
          </View>
      </View>

      {isLoading ? (
          <RiderReviewsSkeleton />
      ) : isError ? (
          <View className="flex-1 items-center justify-center p-6">
              <Ionicons name="alert-circle-outline" size={64} color={TOAST.error} />
              <Text className={`text-lg font-sans-bold mt-4 mb-2 text-center ${darkTheme ? "text-white" : "text-black"}`}>
                  Failed to load reviews
              </Text>
              <Text className={`text-center mb-6 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                  We couldn't retrieve your customer feedback right now. Please check your connection and try again.
              </Text>
              <TouchableOpacity 
                  onPress={() => refetch()}
                  className="px-6 py-3 rounded-full flex-row items-center justify-center"
                  style={{ backgroundColor: BRAND.primary }}
              >
                  <Ionicons name="refresh" size={20} color="#fff" style={{ marginRight: 8 }} />
                  <Text className="text-white font-sans-bold text-base">Try Again</Text>
              </TouchableOpacity>
          </View>
      ) : (
          <ScrollView contentContainerStyle={{ paddingBottom: tabBarClearance }} className="flex-1 px-4 pt-2">
            {/* Overall Rating Card */}
            <View className={`w-full rounded-2xl p-5 border flex-row items-center justify-between mb-6 ${darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}>
                <View className="items-center mr-6">
                    <Text className={`text-5xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                        {ratingScore(reviewsData?.average_rating, reviewsData?.total_reviews) ?? UNRATED_LABEL}
                    </Text>
                    <View className="flex-row my-1">
                        {[1, 2, 3, 4, 5].map((i) => (
                            <Ionicons 
                                key={i} 
                                name={i <= filledStars(reviewsData?.average_rating, reviewsData?.total_reviews) ? "star" : "star-outline"} 
                                size={16} 
                                color="#F59E0B" 
                            />
                        ))}
                    </View>
                    <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        {reviewsData?.total_reviews || 0} Ratings
                    </Text>
                </View>

                <View className="flex-1">
                    {[5, 4, 3, 2, 1].map((star) => 
                        renderDistributionBar(star, reviewsData?.distribution?.[star] || 0, reviewsData?.total_reviews || 0)
                    )}
                </View>
            </View>

            <Text className={`text-xl font-sans-bold mb-4 ${darkTheme ? "text-white" : "text-black"}`}>
                Recent Comments
            </Text>

            {reviewsData?.reviews && reviewsData.reviews.filter(r => r.comment).length > 0 ? (
                reviewsData.reviews.filter(r => r.comment).map((review) => (
                    <View key={review.id} className={`p-4 rounded-xl mb-3 border ${darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-100 shadow-sm"}`}>
                        <View className="flex-row justify-between items-center mb-2">
                            <View className="flex-row">
                                {[1, 2, 3, 4, 5].map((i) => (
                                    <Ionicons 
                                        key={i} 
                                        name={i <= review.rating ? "star" : "star-outline"} 
                                        size={14} 
                                        color="#F59E0B" 
                                    />
                                ))}
                            </View>
                            <Text className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                {review.created_at ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(new Date(review.created_at)) : 'Recent'}
                            </Text>
                        </View>
                        <Text className={`text-base ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                            "{review.comment}"
                        </Text>
                    </View>
                ))
            ) : (
                <View className="items-center justify-center py-10">
                    <Ionicons name="chatbubble-ellipses-outline" size={48} color={BRAND.primary} />
                    <Text className={`mt-4 text-center ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        No written comments yet. Keep providing great service!
                    </Text>
                </View>
            )}

          </ScrollView>
      )}
    </SafeAreaView>
  );
}
