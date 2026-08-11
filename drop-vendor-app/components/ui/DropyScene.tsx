import React, { useEffect } from 'react';
import { View, StyleSheet, AccessibilityInfo } from 'react-native';
import { Text } from '@/components/ui/Text';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  withSequence,
  Easing,
} from 'react-native-reanimated';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND } from '@/constants/brandColors';
import { PressableScale } from "@/components/ui/PressableScale";
import { Image } from 'expo-image';

export type DropyMood = 'sad' | 'celebrate' | 'concerned' | 'search' | 'proud';

interface DropySceneProps {
  mood: DropyMood;
  title: string;
  subtitle?: string;
  ctaLabel?: string;
  onCtaPress?: () => void;
  variant?: 'customer' | 'vendor' | 'rider';
}

/* require() returns a number (asset ID) in React Native */
const MOOD_IMAGES: Record<DropyMood, number> = {
  sad: require('../../assets/images/dropy/dropy_sad.webp'),
  celebrate: require('../../assets/images/dropy/dropy_celebrate.webp'),
  concerned: require('../../assets/images/dropy/dropy_concerned.webp'),
  search: require('../../assets/images/dropy/dropy_search.webp'),
  proud: require('../../assets/images/dropy/dropy_hero.webp'),
};

export function DropyScene({ mood, title, subtitle, ctaLabel, onCtaPress }: DropySceneProps) {
  const [reduceMotion, setReduceMotion] = React.useState(false);
  const { currentTheme } = React.useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';

  // Animation values
  const translateY = useSharedValue(20);
  const opacity = useSharedValue(0);
  const scale = useSharedValue(0.8);
  const rotation = useSharedValue(0);

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      setReduceMotion(enabled);
    });
  }, []);

  useEffect(() => {
    if (reduceMotion) {
      translateY.value = 0;
      opacity.value = 1;
      scale.value = 1;
      rotation.value = 0;
      return;
    }

    // Motion Design - Emotional Staging
    if (mood === 'sad') {
      // Slow, drooping curve
      translateY.value = withTiming(0, { duration: 600, easing: Easing.inOut(Easing.cubic) });
      opacity.value = withTiming(1, { duration: 600 });
      scale.value = withTiming(1, { duration: 600 });
    } else if (mood === 'celebrate') {
      // Joyful, pop up with overshoot
      translateY.value = withSpring(0, { damping: 12, stiffness: 90 });
      opacity.value = withTiming(1, { duration: 300 });
      scale.value = withSpring(1, { damping: 10, stiffness: 100 });
    } else if (mood === 'concerned') {
      // Firm shake without overshoot (error)
      opacity.value = withTiming(1, { duration: 200 });
      scale.value = withTiming(1, { duration: 200 });
      translateY.value = withTiming(0, { duration: 200 });
      rotation.value = withSequence(
        withTiming(-5, { duration: 100 }),
        withTiming(5, { duration: 100 }),
        withTiming(-3, { duration: 100 }),
        withTiming(0, { duration: 100 })
      );
    } else if (mood === 'search') {
      // Curious, gentle appearance
      translateY.value = withTiming(0, { duration: 400, easing: Easing.out(Easing.quad) });
      opacity.value = withTiming(1, { duration: 300 });
      scale.value = withTiming(1, { duration: 300 });
    } else {
      // Proud / default
      translateY.value = withSpring(0, { damping: 14, stiffness: 100 });
      opacity.value = withTiming(1, { duration: 400 });
      scale.value = withSpring(1, { damping: 12, stiffness: 100 });
    }
  }, [mood, reduceMotion]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [
      { translateY: translateY.value },
      { scale: scale.value },
      { rotate: `${rotation.value}deg` }
    ],
  }));

  return (
    <View className="flex-1 items-center justify-center p-8">
      <Animated.View style={[styles.imageContainer, animatedStyle]}>
        <Image 
          source={MOOD_IMAGES[mood]} 
          style={styles.image} 
          contentFit="contain"
          accessibilityLabel={`Dropy mascot feeling ${mood}`}
          // We fail gracefully to an empty view if the user hasn't added the image yet
          placeholder="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdib3g9IjAgMCAxMDAgMTAwIiBmaWxsPSJub25lIj48Y2lyY2xlIGN4PSI1MCIgY3k9IjUwIiByPSI0MCIgZmlsbD0iI2YwZjBmMCIvPjwvc3ZnPg=="
        />
      </Animated.View>
      
      <Text className={`text-xl font-sans-bold text-center mb-2 ${darkTheme ? 'text-white' : 'text-slate-900'}`} accessibilityRole="header">
        {title}
      </Text>
      
      {subtitle && (
        <Text className={`text-base text-center mb-6 ${darkTheme ? 'text-slate-400' : 'text-slate-500'}`}>
          {subtitle}
        </Text>
      )}
      
      {ctaLabel && onCtaPress && (
        <PressableScale
          onPress={onCtaPress}
          className="px-6 py-3 rounded-xl w-full max-w-[250px]"
          accessibilityRole="button"
          accessibilityLabel={ctaLabel}
          style={{ minHeight: 44, justifyContent: 'center', backgroundColor: BRAND.primary }}
        >
          <Text className="text-white font-sans-bold text-center">{ctaLabel}</Text>
        </PressableScale>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  imageContainer: {
    width: 140,
    height: 140,
    marginBottom: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  image: {
    width: '100%',
    height: '100%',
  }
});
