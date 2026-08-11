import * as Haptics from 'expo-haptics';
import React from 'react';
import { TouchableWithoutFeedback } from 'react-native';
import { Text } from '@/components/ui/Text';
import Animated, {
    useAnimatedStyle,
    useSharedValue,
    withSpring,
} from 'react-native-reanimated';

type Props = {
  title: string;
  onPress: () => void;
  style?: string;
  textStyle?: string;
  disabled?: boolean;
};

export default function DropButton({ title, onPress, style = "", textStyle = "", disabled = false }: Props) {
  const scale = useSharedValue(1);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const handlePressIn = () => {
    if (disabled) return;
    scale.value = withSpring(0.95);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
  };

  const handlePressOut = () => {
    if (disabled) return;
    scale.value = withSpring(1);
  };

  return (
    <TouchableWithoutFeedback
      onPressIn={handlePressIn}
      onPressOut={handlePressOut}
      onPress={!disabled ? onPress : undefined}
    >
      <Animated.View 
        className={`bg-primary p-4 px-6 rounded-full items-center justify-center ${style} ${disabled ? 'opacity-50' : ''}`} 
        style={animatedStyle}
      >
        <Text numberOfLines={1} className={`text-white font-sans-bold text-center text-lg whitespace-nowrap ${textStyle}`}>{title}</Text>
      </Animated.View>
    </TouchableWithoutFeedback>
  );
}
