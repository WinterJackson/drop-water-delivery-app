/**
 * AnimatedSplash — Premium full-screen splash with spring physics
 *
 * Layers:
 *   1. LinearGradient background (3 brand colors)
 *   2. Logo with spring scale + rotation + fade
 *   3. Tagline with delayed fade + slide
 *   4. Pulsing dots loader at bottom
 *
 * All animations run on the UI thread via Reanimated v4 worklets.
 * Respects reduced-motion accessibility setting.
 */
import React, { useEffect, useState } from 'react';
import { View, Image, StyleSheet, AccessibilityInfo, Platform, ImageBackground, Dimensions } from 'react-native';
import { Text } from '@/components/ui/Text';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  withDelay,
  withSequence,
  withRepeat,
  Easing,
  type SharedValue,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { GRADIENTS, GRADIENTS_DARK, BRAND, type AppVariant } from '@/constants/brandColors';
import { typography } from '@/constants/typography';
import images from '@/constants/images/images';

// ── Config ────────────────────────────────────────────────────────
const SPLASH_DURATION_MS = 10000;

const TAGLINES: Record<AppVariant, string> = {
  customer: 'Satisfy Your Thirst!',
  vendor: 'Grow your business with Drop',
  rider: 'Earn on your schedule',
};

// ── Component ─────────────────────────────────────────────────────

interface AnimatedSplashProps {
  onComplete: () => void;
  variant: AppVariant;
  isDark?: boolean;
}

export function AnimatedSplash({ onComplete, variant, isDark = false }: AnimatedSplashProps) {
  const insets = useSafeAreaInsets();
  const [reduceMotion, setReduceMotion] = useState(false);

  // ── Shared values (UI thread) ──
  const logoScale = useSharedValue(0.3);
  const logoOpacity = useSharedValue(0);
  const logoRotate = useSharedValue(-5);
  const taglineOpacity = useSharedValue(0);
  const taglineY = useSharedValue(20);

  // ── Dropy Shared values ──
  const dropyOpacity = useSharedValue(0);
  const dropyY = useSharedValue(40);

  useEffect(() => {
    // Check reduced motion preference
    AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      setReduceMotion(enabled);
    });
  }, []);

  useEffect(() => {
    if (reduceMotion) {
      // Skip animations — instant reveal
      logoScale.value = 1;
      logoOpacity.value = 1;
      logoRotate.value = 0;
      taglineOpacity.value = 1;
      taglineY.value = 0;
      dropyOpacity.value = 1;
      dropyY.value = 0;
    } else {
      // Logo entrance — spring physics
      logoScale.value = withDelay(100, withSpring(1, { damping: 12, stiffness: 100 }));
      logoOpacity.value = withDelay(100, withTiming(1, { duration: 400 }));
      logoRotate.value = withDelay(100, withSpring(0, { damping: 10 }));

      // Dropy Hero entrance — slides up under logo
      dropyOpacity.value = withDelay(400, withTiming(1, { duration: 400 }));
      dropyY.value = withDelay(400, withSpring(0, { damping: 12, stiffness: 100 }));

      // Tagline entrance — delayed fade + slide
      taglineOpacity.value = withDelay(600, withTiming(1, { duration: 400 }));
      taglineY.value = withDelay(
        600,
        withTiming(0, { duration: 400, easing: Easing.out(Easing.cubic) })
      );
    }

    // Auto-complete after duration (runs regardless of motion setting)
    const timer = setTimeout(onComplete, SPLASH_DURATION_MS);
    return () => clearTimeout(timer);
  }, [reduceMotion]);

  // ── Animated styles ──
  const logoAnimatedStyle = useAnimatedStyle(() => ({
    transform: [
      { scale: logoScale.value },
      { rotate: `${logoRotate.value}deg` },
    ],
    opacity: logoOpacity.value,
  }));

  const taglineAnimatedStyle = useAnimatedStyle(() => ({
    opacity: taglineOpacity.value,
    transform: [{ translateY: taglineY.value }],
  }));

  const dropyAnimatedStyle = useAnimatedStyle(() => ({
    opacity: dropyOpacity.value,
    transform: [{ translateY: dropyY.value }],
  }));

  return (
    <View className={isDark ? "bg-black" : ""} style={{ flex: 1 }}>
      <ImageBackground
        source={images.authBgLight}
        style={{
          width: '100%',
          height: Dimensions.get('window').height * 0.35,
          position: 'absolute',
          top: 0
        }}
      >
        <LinearGradient
          className="w-full h-full"
          colors={[
            isDark ? "rgba(0, 0, 0, 0.2)" : "transparent",
            isDark ? "rgba(0, 0, 0, 0.6)" : "rgba(240, 240, 240, 0.7)",
            isDark ? "rgba(0, 0, 0, 1)" : "rgb(240, 240, 240)",
          ]}
        />
      </ImageBackground>

      <View style={[styles.container, { zIndex: 1 }]}>
        {/* Logo */}
        <Animated.View
          style={[styles.logoContainer, logoAnimatedStyle]}
          accessibilityLabel="Drop logo"
        >
          <Image
            source={isDark ? images.logo_dark : images.logo_light}
            style={styles.logo}
            resizeMode="contain"
          />
        </Animated.View>

        {/* Dropy Mascot */}
        <Animated.View
          style={[styles.dropyContainer, dropyAnimatedStyle]}
        >
          <Image
            source={require('../../assets/images/dropy/dropy_hero.webp')}
            style={styles.dropy}
            resizeMode="contain"
          />
        </Animated.View>

        {/* Tagline */}
        <Animated.Text
          style={[
            // `typography.body` first: it carries the shared line-height, and
            // whatever comes last wins in a React Native style array. It used
            // to sit after `styles.tagline` and quietly overrode the tagline's
            // own size and face.
            typography.body,
            styles.tagline,
            taglineAnimatedStyle,
            { color: isDark ? BRAND.white : BRAND.textDark }
          ]}
          accessibilityLabel={TAGLINES[variant]}
        >
          {TAGLINES[variant]}
        </Animated.Text>

        {/* Loading dots at bottom */}
        <View style={[styles.loadingContainer, { bottom: insets.bottom + 60 }]}>
          <LoadingDots reduceMotion={reduceMotion} isDark={isDark} />
        </View>
      </View>
    </View>
  );
}

// ── Loading Dots ──────────────────────────────────────────────────

function LoadingDots({ reduceMotion, isDark }: { reduceMotion: boolean, isDark?: boolean }) {
  const dot1 = useSharedValue(0.3);
  const dot2 = useSharedValue(0.3);
  const dot3 = useSharedValue(0.3);

  useEffect(() => {
    if (reduceMotion) {
      dot1.value = 1;
      dot2.value = 1;
      dot3.value = 1;
      return;
    }

    // Staggered pulsing loop
    const pulse = (sv: SharedValue<number>, delay: number) => {
      sv.value = withDelay(
        delay,
        withRepeat(
          withSequence(
            withTiming(1, { duration: 400 }),
            withTiming(0.3, { duration: 400 })
          ),
          -1,  // infinite
          false
        )
      );
    };

    pulse(dot1, 0);
    pulse(dot2, 150);
    pulse(dot3, 300);
  }, [reduceMotion]);

  const d1 = useAnimatedStyle(() => ({ opacity: dot1.value }));
  const d2 = useAnimatedStyle(() => ({ opacity: dot2.value }));
  const d3 = useAnimatedStyle(() => ({ opacity: dot3.value }));

  const dotColor = isDark ? BRAND.white : BRAND.textDark;

  return (
    <View style={styles.dotsRow}>
      <Animated.View style={[styles.dot, d1, { backgroundColor: dotColor }]} />
      <Animated.View style={[styles.dot, d2, { backgroundColor: dotColor }]} />
      <Animated.View style={[styles.dot, d3, { backgroundColor: dotColor }]} />
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoContainer: {
    width: 160,
    height: 160,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logo: {
    width: '100%',
    height: '100%',
  },
  dropyContainer: {
    width: 140,
    height: 140,
    marginTop: -20, // Slide it slightly under/overlapping the logo space
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 10,
  },
  dropy: {
    width: '100%',
    height: '100%',
  },
  tagline: {
    marginTop: 24,
    fontSize: 18,
    fontFamily: 'Fredoka_500Medium',
    color: BRAND.white,
    textAlign: 'center',
    paddingHorizontal: 32,
  },
  loadingContainer: {
    position: 'absolute',
    alignSelf: 'center',
  },
  dotsRow: {
    flexDirection: 'row',
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: BRAND.white,
  },
});

export default AnimatedSplash;
