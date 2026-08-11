import React, { useContext, useEffect } from 'react';
import { View, useWindowDimensions, ActivityIndicator } from 'react-native';
import { Text } from '@/components/ui/Text';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  runOnJS,
  interpolateColor,
} from 'react-native-reanimated';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import { Ionicons } from '@expo/vector-icons';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND, TOAST } from '@/constants/brandColors';

interface SwipeToGoOnlineProps {
  isOnline: boolean;
  onToggle: (newState: boolean) => Promise<void>;
  isLoading?: boolean;
}

const SLIDER_HEIGHT = 60;
const SLIDER_PADDING = 6;
const KNOB_SIZE = SLIDER_HEIGHT - SLIDER_PADDING * 2;

export default function SwipeToGoOnline({ isOnline, onToggle, isLoading }: SwipeToGoOnlineProps) {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';
  const { width } = useWindowDimensions();
  
  // Make slider width 90% of screen
  const SLIDER_WIDTH = width * 0.9;
  const MAX_TRANSLATE = SLIDER_WIDTH - KNOB_SIZE - SLIDER_PADDING * 2;

  const translateX = useSharedValue(0);
  const isDragging = useSharedValue(false);

  useEffect(() => {
    if (!isDragging.value) {
      translateX.value = withSpring(isOnline ? MAX_TRANSLATE : 0, {
        damping: 15,
        stiffness: 120,
      });
    }
  }, [isOnline, MAX_TRANSLATE]);

  const handleToggle = (newState: boolean) => {
    onToggle(newState);
  };

  const pan = Gesture.Pan()
    .onBegin(() => {
      if (isLoading) return;
      isDragging.value = true;
    })
    .onUpdate((event) => {
      if (isLoading) return;
      let newTranslation = (isOnline ? MAX_TRANSLATE : 0) + event.translationX;
      newTranslation = Math.max(0, Math.min(newTranslation, MAX_TRANSLATE));
      translateX.value = newTranslation;
    })
    .onEnd(() => {
      if (isLoading) return;
      isDragging.value = false;
      const threshold = MAX_TRANSLATE * 0.5;
      
      if (!isOnline && translateX.value > threshold) {
        // Swiped far enough right -> Go Online
        runOnJS(handleToggle)(true);
        translateX.value = withSpring(MAX_TRANSLATE);
      } else if (isOnline && translateX.value < threshold) {
        // Swiped far enough left -> Go Offline
        runOnJS(handleToggle)(false);
        translateX.value = withSpring(0);
      } else {
        // Snap back to original state
        translateX.value = withSpring(isOnline ? MAX_TRANSLATE : 0);
      }
    });

  const knobStyle = useAnimatedStyle(() => {
    return {
      transform: [{ translateX: translateX.value }],
    };
  });

  const backgroundStyle = useAnimatedStyle(() => {
    const bgColor = interpolateColor(
      translateX.value,
      [0, MAX_TRANSLATE],
      [
        darkTheme ? BRAND.gray800 : BRAND.gray100, // Offline (gray)
        darkTheme ? 'rgba(2, 149, 247, 0.2)' : 'rgba(2, 149, 247, 0.1)' // Online (primary tint)
      ]
    );
    const borderColor = interpolateColor(
      translateX.value,
      [0, MAX_TRANSLATE],
      [
        darkTheme ? BRAND.gray700 : BRAND.gray200,
        darkTheme ? 'rgba(2, 149, 247, 0.4)' : 'rgba(2, 149, 247, 0.3)'
      ]
    );

    return {
      backgroundColor: bgColor,
      borderColor: borderColor,
    };
  });

  const textStyle = useAnimatedStyle(() => {
    const color = interpolateColor(
      translateX.value,
      [0, MAX_TRANSLATE],
      [
        darkTheme ? BRAND.gray400 : BRAND.gray500,
        BRAND.primary
      ]
    );
    return { color };
  });

  return (
    <View style={{ width: '100%', alignItems: 'center', marginVertical: 12 }}>
      <GestureDetector gesture={pan}>
        <Animated.View
          style={[
            backgroundStyle,
            {
              width: SLIDER_WIDTH,
              height: SLIDER_HEIGHT,
              borderRadius: 100,
              borderWidth: 1,
              justifyContent: 'center',
              padding: SLIDER_PADDING,
              overflow: 'hidden',
            },
          ]}
        >
          {/* Background Text */}
          <View style={{ position: 'absolute', width: '100%', alignItems: 'center' }}>
            <Animated.Text style={[textStyle, { fontSize: 16, fontFamily: 'Karla_700Bold', letterSpacing: 0.5 }]}>
              {isLoading ? 'Updating...' : (isOnline ? 'You are Online' : 'Swipe to go Online')}
            </Animated.Text>
          </View>

          {/* Draggable Knob */}
          <Animated.View
            style={[
              knobStyle,
              {
                width: KNOB_SIZE,
                height: KNOB_SIZE,
                borderRadius: KNOB_SIZE / 2,
                backgroundColor: isOnline ? BRAND.primary : (darkTheme ? BRAND.gray600 : '#ffffff'),
                ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }),
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 10,
              },
            ]}
          >
            {isLoading ? (
              <ActivityIndicator color={isOnline ? BRAND.white : BRAND.bgDark} size="small" />
            ) : (
              <Ionicons 
                name={isOnline ? "power" : "chevron-forward"} 
                size={24} 
                color={isOnline ? '#ffffff' : (darkTheme ? '#ffffff' : BRAND.gray600)} 
              />
            )}
          </Animated.View>
        </Animated.View>
      </GestureDetector>
    </View>
  );
}
