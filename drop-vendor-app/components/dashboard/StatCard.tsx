import React, { useContext } from 'react';
import { View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { Ionicons } from '@expo/vector-icons';
import PressableScale from '@/components/ui/PressableScale';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND } from '@/constants/brandColors';

interface StatCardProps {
  title: string;
  value: string | number;
  icon: keyof typeof Ionicons.glyphMap;
  color: string;
}

export default function StatCard({ title, value, icon, color }: StatCardProps) {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  return (
    <PressableScale
      activeOpacity={0.8}
      className={`w-[140px] h-[130px] p-4 rounded-[20px] shadow-sm border justify-between mr-3 ${
        darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"
      }`}
      style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
    >
      <View className={`w-10 h-10 rounded-full items-center justify-center ${darkTheme ? "bg-slate-800/80" : "bg-white"}`}>
        <Ionicons name={icon} size={20} color={color || BRAND.primary} />
      </View>
      <View>
        <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`} numberOfLines={1}>
          {value}
        </Text>
        <Text className={`text-xs mt-1 ${darkTheme ? "text-slate-400" : "text-slate-500"}`} numberOfLines={1}>
          {title}
        </Text>
      </View>
    </PressableScale>
  );
}
