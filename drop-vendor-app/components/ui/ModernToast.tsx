import type { ComponentProps } from 'react';
import React, { useEffect, useContext } from 'react';
import { View, Platform, useWindowDimensions } from 'react-native';
import { Text } from '@/components/ui/Text';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
  runOnJS,
  FadeInDown,
  FadeOutUp,
  interpolateColor,
} from 'react-native-reanimated';
import { GestureDetector, Gesture } from 'react-native-gesture-handler';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useToastStore, ToastType } from '@/stores/toastStore';
import { TOAST, BRAND } from '@/constants/brandColors';
import { UIThemeContext } from '@/context/ThemeContext';

const TOAST_HEIGHT = 80;

/** Safely coerce any value into a renderable string */
const safeString = (val: unknown): string => {
  if (val === null || val === undefined) return '';
  if (typeof val === 'string') return val;
  if (typeof val === 'object') {
    // Handle FastAPI validation errors: {type, loc, msg, input}
    // Narrowed once rather than asserted twice per branch: `in` is a type
    // guard on a `Record`, so both reads below are checked rather than trusted.
    const obj = val as Record<string, unknown>;
    if ('msg' in obj) return String(obj.msg);
    if ('message' in obj) return String(obj.message);
    try { return JSON.stringify(val); } catch { return String(val); }
  }
  return String(val);
};
const SWIPE_THRESHOLD = -20; // How far up to swipe before dismissing

export default function ModernToast() {
  const { visible, type, title, message, hideToast } = useToastStore();
  const insets = useSafeAreaInsets();
  const { currentTheme } = useContext(UIThemeContext);
  const isDark = currentTheme === 'dark';
  const { width } = useWindowDimensions();

  // Gesture state
  const translateY = useSharedValue(0);

  // Reset transform when toast becomes visible
  useEffect(() => {
    if (visible) {
      translateY.value = withTiming(0, { duration: 200 });
    }
  }, [visible]);

  // Pan gesture for swipe-to-dismiss
  const panGesture = Gesture.Pan()
    .onUpdate((event) => {
      // Only allow swiping up
      if (event.translationY < 0) {
        translateY.value = event.translationY;
      } else {
        // Add resistance if trying to pull down
        translateY.value = event.translationY * 0.2;
      }
    })
    .onEnd((event) => {
      if (event.translationY < SWIPE_THRESHOLD || event.velocityY < -500) {
        // Swipe dismissed
        translateY.value = withTiming(-150, { duration: 200 }, () => {
          runOnJS(hideToast)();
        });
      } else {
        // Return to resting position
        translateY.value = withTiming(0, { duration: 200 });
      }
    });

  const animatedStyle = useAnimatedStyle(() => {
    return {
      transform: [{ translateY: translateY.value }],
    };
  });

  if (!visible) return null;

  // Type configuration
  const config = {
    success: {
      icon: 'checkmark-circle',
      color: TOAST.success,
      bgLight: TOAST.successLight,
      bgDark: TOAST.successDark,
      borderLight: TOAST.successBorderLight,
      borderDark: TOAST.successBorderDark,
    },
    error: {
      icon: 'close-circle',
      color: TOAST.error,
      bgLight: TOAST.errorLight,
      bgDark: TOAST.errorDark,
      borderLight: TOAST.errorBorderLight,
      borderDark: TOAST.errorBorderDark,
    },
    info: {
      icon: 'information-circle',
      color: TOAST.info,
      bgLight: TOAST.infoLight,
      bgDark: TOAST.infoDark,
      borderLight: TOAST.infoBorderLight,
      borderDark: TOAST.infoBorderDark,
    },
  }[type || 'info'];

  const backgroundColor = isDark ? config?.bgDark || TOAST.bgDark : config?.bgLight || TOAST.bgLight;
  const borderColor = isDark ? config?.borderDark || TOAST.borderDark : config?.borderLight || TOAST.borderLight;
  const textColor = isDark ? TOAST.textDark : TOAST.textLight;
  const subTextColor = isDark ? TOAST.subTextDark : TOAST.subTextLight;

  return (
    <Animated.View
      entering={FadeInDown.duration(200)}
      exiting={FadeOutUp.duration(200)}
      style={{
        position: 'absolute',
        top: insets.top ? insets.top + 10 : 40,
        left: 0,
        right: 0,
        alignItems: 'center',
        zIndex: 999999, // Ensure it's on absolute top
        paddingHorizontal: 20,
        width: width,
      }}
    >
      <GestureDetector gesture={panGesture}>
        <Animated.View style={animatedStyle}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            backgroundColor,
            borderColor,
            borderWidth: 1,
            borderRadius: 24, // Matching PopupModal rounded-[24px]
            paddingHorizontal: 16,
            paddingVertical: 14,
            minHeight: 60,
            width: '100%',
            maxWidth: 400,
            shadowColor: isDark ? "#000" : BRAND.bgDark,
            shadowOffset: { width: 0, height: 4 },
            shadowOpacity: isDark ? 0.4 : 0.1,
            shadowRadius: 10,
            elevation: 8,
          }}
        >
          {/* Icon */}
          <Ionicons name={config?.icon as ComponentProps<typeof Ionicons>['name']} size={24} color={BRAND.primary} />

          {/* Text Content */}
          <View style={{ marginLeft: 12, flex: 1, justifyContent: 'center' }}>
            <Text
              numberOfLines={1}
              style={{
                fontSize: 15,
                fontFamily: 'Karla_600SemiBold',
                color: textColor,
                marginBottom: message ? 2 : 0,
              }}
            >
              {safeString(title)}
            </Text>
            {message ? (
              <Text
                numberOfLines={2}
                style={{
                  fontSize: 13,
                  fontFamily: 'Karla_400Regular',
                  color: subTextColor,
                }}
              >
                {safeString(message)}
              </Text>
            ) : null}
          </View>
        </View>
        </Animated.View>
      </GestureDetector>
    </Animated.View>
  );
}
