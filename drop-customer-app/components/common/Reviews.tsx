import { View, Text } from "react-native";
import React, { useContext, useState } from "react";
import { UIThemeContext } from "@/context/ThemeContext";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import { useTargetReviews, useRatingSummary, type TargetReview } from "@/hooks/queries/useReviews";

const Stars = ({ rating, size = 14 }: { rating: number; size?: number }) => (
  <View className="flex-row">
    {[1, 2, 3, 4, 5].map((star) => (
      <Ionicons
        key={star}
        name={star <= Math.round(rating) ? "star" : "star-outline"}
        size={size}
        color="#FFC107"
      />
    ))}
  </View>
);

const ReviewCard = ({ review, darkTheme }: { review: TargetReview; darkTheme: boolean }) => {
  const [extend, setExtend] = useState(false);
  const comment = review.comment?.trim() ?? "";
  const isLong = comment.length > 70;

  return (
    <View className="p-2 py-4 gap-2 border-b border-accentbg/20 mx-1">
      <View className="flex-row justify-between items-center">
        {/* Five outlined-or-filled stars, so a 2-star review reads as 2 out of 5.
            Rendering only `Math.round(rating)` filled stars made a 2-star and a
            5-star review differ solely by how many icons were present. */}
        <Stars rating={review.rating} />
        <Text className="text-gray-400 text-xs">
          {new Date(review.created_at).toLocaleDateString()}
        </Text>
      </View>

      {/* A rating with no words is the common case — RateOrder submits the stars
          and leaves the comment optional — and it used to render as a blank line. */}
      {comment ? (
        <>
          <Text className={`text-base ${darkTheme ? "text-white" : "text-black"}`}>
            {isLong && !extend ? comment.substring(0, 70).trim() + "..." : comment}
          </Text>
          {isLong && (
            <PressableScale onPress={() => setExtend(!extend)} hitSlop={8}>
              <Text className="text-sm text-gray-500">{extend ? "less" : "more"}</Text>
            </PressableScale>
          )}
        </>
      ) : (
        <Text className={`text-sm italic ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
          Rated without a comment
        </Text>
      )}
    </View>
  );
};

const DistributionBar = ({
  star,
  count,
  total,
  darkTheme,
}: { star: number; count: number; total: number; darkTheme: boolean }) => {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <View className="flex-row items-center gap-2">
      <Text className={`text-xs w-3 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{star}</Text>
      <Ionicons name="star" size={10} color="#FFC107" />
      <View className={`flex-1 h-1.5 rounded-full ${darkTheme ? "bg-gray-800" : "bg-gray-200"}`}>
        <View
          style={{ width: `${pct}%`, backgroundColor: "#FFC107" }}
          className="h-1.5 rounded-full"
        />
      </View>
      <Text className={`text-xs w-6 text-right ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
        {count}
      </Text>
    </View>
  );
};

const Reviews = ({ targetType, targetId }: { targetType: "vendor" | "rider"; targetId: string }) => {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { data: reviews = [], isLoading } = useTargetReviews(targetType, targetId);
  const { data: summary } = useRatingSummary(targetType, targetId);

  if (isLoading) return null; // Or a skeleton later

  const heading = (
    <Text className={`text-xl ${darkTheme ? "text-white" : "text-black"}`}>Reviews</Text>
  );

  if (reviews.length === 0) {
    return (
      <View className="pt-8 p-1 gap-2">
        {heading}
        <Text className={darkTheme ? "text-gray-400" : "text-gray-500"}>No reviews yet.</Text>
      </View>
    );
  }

  const total = summary?.total_reviews ?? reviews.length;

  return (
    <View className="pt-8 p-1 gap-2">
      {heading}

      {/* The count and spread come from the server's aggregate, so they describe
          every review rather than just the page fetched here. An average on its
          own is not decidable: 5.0 from one review looked identical to 5.0 from
          three hundred. */}
      {summary && total > 0 && (
        <View className="flex-row gap-5 items-center p-4 rounded-2xl bg-accentbg/5">
          <View className="items-center">
            <Text className={`text-3xl font-bold ${darkTheme ? "text-white" : "text-black"}`}>
              {summary.average_rating.toFixed(1)}
            </Text>
            <Stars rating={summary.average_rating} />
            <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
              {total} {total === 1 ? "rating" : "ratings"}
            </Text>
          </View>
          <View className="flex-1 gap-1">
            {[5, 4, 3, 2, 1].map((star) => (
              <DistributionBar
                key={star}
                star={star}
                count={summary.distribution?.[String(star)] ?? 0}
                total={total}
                darkTheme={darkTheme}
              />
            ))}
          </View>
        </View>
      )}

      <View className="p-1 pb-4 bg-accentbg/5 flex-1 rounded-3xl">
        {reviews.map((r) => (
          <ReviewCard key={r.id} review={r} darkTheme={darkTheme} />
        ))}
      </View>
    </View>
  );
};

export default Reviews;
