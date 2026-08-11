import React, { useContext, useEffect, useMemo } from 'react';
import { View, useWindowDimensions, ActivityIndicator } from 'react-native';
import { Text } from '@/components/ui/Text';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  useDerivedValue,
  withSpring,
  runOnJS,
  interpolateColor,
} from 'react-native-reanimated';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import { Ionicons } from '@expo/vector-icons';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND } from '@/constants/brandColors';

interface SwipeToGoOnlineProps {
  isOnline: boolean;
  onToggle: (newState: boolean) => Promise<void>;
  isLoading?: boolean;
}

const SLIDER_HEIGHT = 60;
const SLIDER_PADDING = 6;
const KNOB_SIZE = SLIDER_HEIGHT - SLIDER_PADDING * 2;

// ── Hardcoded color arrays for worklet safety ──────────────────────
// Reanimated worklets cannot reliably read JS closure variables.
// We define static color tuples here so interpolateColor always gets valid string arrays.
const COLORS = {
  bgOfflineDark: '#1f2937',    // gray800
  bgOfflineLight: '#f3f4f6',   // gray100
  bgOnlineDark: 'rgba(2, 149, 247, 0.2)',
  bgOnlineLight: 'rgba(2, 149, 247, 0.1)',
  borderOfflineDark: '#374151', // gray700
  borderOfflineLight: '#e5e7eb', // gray200
  borderOnlineDark: 'rgba(2, 149, 247, 0.4)',
  borderOnlineLight: 'rgba(2, 149, 247, 0.3)',
  textOfflineDark: '#9ca3af',  // gray400
  textOfflineLight: '#6b7280', // gray500
  textOnline: '#0295f7',       // primary
} as const;

export default function SwipeToGoOnline({ isOnline, onToggle, isLoading }: SwipeToGoOnlineProps) {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';
  const { width } = useWindowDimensions();

  // Calculate slider width — guard against 0-width on first render
  const SLIDER_WIDTH = Math.max(200, width * 0.9);
  const MAX_TRANSLATE = Math.max(10, SLIDER_WIDTH - KNOB_SIZE - SLIDER_PADDING * 2);

  // ── Shared values for the Reanimated UI thread ──────────────────
  const translateX = useSharedValue(0);
  const isDragging = useSharedValue(false);
  const maxTranslateSV = useSharedValue(MAX_TRANSLATE);
  const isDarkSV = useSharedValue(darkTheme);

  // Keep shared values in sync with JS props
  useEffect(() => {
    maxTranslateSV.value = MAX_TRANSLATE;
  }, [MAX_TRANSLATE]);

  useEffect(() => {
    isDarkSV.value = darkTheme;
  }, [darkTheme]);

  useEffect(() => {
    if (!isDragging.value) {
      translateX.value = withSpring(isOnline ? maxTranslateSV.value : 0, {
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
      const base = isOnline ? maxTranslateSV.value : 0;
      let next = base + event.translationX;
      next = Math.max(0, Math.min(next, maxTranslateSV.value));
      translateX.value = next;
    })
    .onEnd(() => {
      if (isLoading) return;
      isDragging.value = false;
      const threshold = maxTranslateSV.value * 0.5;

      if (!isOnline && translateX.value > threshold) {
        runOnJS(handleToggle)(true);
        translateX.value = withSpring(maxTranslateSV.value);
      } else if (isOnline && translateX.value < threshold) {
        runOnJS(handleToggle)(false);
        translateX.value = withSpring(0);
      } else {
        translateX.value = withSpring(isOnline ? maxTranslateSV.value : 0);
      }
    });

  const knobStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: translateX.value }],
  }));

  // ── Animated background ─────────────────────────────────────────
  // All color values are static strings — no JS closures inside worklet
  const backgroundStyle = useAnimatedStyle(() => {
    const max = maxTranslateSV.value;
    const dark = isDarkSV.value;

    const bgColor = interpolateColor(
      translateX.value,
      [0, max],
      dark
        ? [COLORS.bgOfflineDark, COLORS.bgOnlineDark]
        : [COLORS.bgOfflineLight, COLORS.bgOnlineLight]
    );

    const borderColor = interpolateColor(
      translateX.value,
      [0, max],
      dark
        ? [COLORS.borderOfflineDark, COLORS.borderOnlineDark]
        : [COLORS.borderOfflineLight, COLORS.borderOnlineLight]
    );

    return { backgroundColor: bgColor, borderColor };
  });

  // ── Animated label color ────────────────────────────────────────
  const textStyle = useAnimatedStyle(() => {
    const max = maxTranslateSV.value;
    const dark = isDarkSV.value;

    const color = interpolateColor(
      translateX.value,
      [0, max],
      dark
        ? [COLORS.textOfflineDark, COLORS.textOnline]
        : [COLORS.textOfflineLight, COLORS.textOnline]
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
