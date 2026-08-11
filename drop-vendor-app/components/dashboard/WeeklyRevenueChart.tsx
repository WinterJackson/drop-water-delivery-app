import React, { useContext, useEffect } from 'react';
import { View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { Ionicons } from '@expo/vector-icons';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND } from '@/constants/brandColors';
import Animated, { useAnimatedStyle, withSpring, useSharedValue } from 'react-native-reanimated';

export default function WeeklyRevenueChart({ data }: { data?: number[] }) {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const chartData = data && data.length === 7 ? data : [0, 0, 0, 0, 0, 0, 0]; 
  const isAllZeros = chartData.every(val => val === 0);
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const maxVal = Math.max(...chartData, 1);
  
  return (
      <View 
        className={`mt-6 p-5 mx-4 rounded-[24px] border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} 
        style={{ 
          elevation: 2,
          ...(darkTheme ? { boxShadow: "0 4px 12px rgba(0, 0, 0, 0.3)" } : { boxShadow: "0 4px 12px rgba(0, 0, 0, 0.05)" }) 
        }}
      >
        <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-slate-900"}`}>Revenue Overview</Text>
        <Text className={`text-sm mt-1 mb-4 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Weekly Snapshot</Text>
        
        {isAllZeros ? (
          <View className="h-32 items-center justify-center bg-accentbg/5 rounded-xl border border-accentbg/10 border-dashed">
              <Ionicons name="bar-chart-outline" size={32} color={BRAND.primary} className="mb-2" />
              <Text className={`text-center font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>No revenue yet</Text>
              <Text className={`text-center text-xs mt-1 ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Start receiving orders to see your breakdown</Text>
          </View>
        ) : (
          <View className="flex-row items-end justify-between h-32 mt-2">
            {chartData.map((value, i) => {
               const percentage = (value / maxVal) * 100;
               return (
                 <View key={i} className="items-center flex-1">
                    <AnimatedBar percentage={percentage} />
                    <Text className={`mt-2 text-xs font-sans-semibold ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>{days[i]}</Text>
                 </View>
               );
            })}
          </View>
        )}
      </View>
  );
}

const AnimatedBar = ({ percentage }: { percentage: number }) => {
  const height = useSharedValue(0);

  useEffect(() => {
    height.value = withSpring(percentage, {
      damping: 12,
      stiffness: 90,
    });
  }, [percentage]);

  const animatedStyle = useAnimatedStyle(() => {
    return {
      height: `${height.value}%`,
    };
  });

  return (
    <View className="w-8 rounded-t-xl bg-accentbg/20 flex-row items-end" style={{ height: '100%', overflow: 'hidden' }}>
       <Animated.View className="w-full bg-accentbg rounded-t-xl" style={animatedStyle} />
    </View>
  );
};
