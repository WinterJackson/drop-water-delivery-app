import React from 'react';
import { Pressable, PressableProps, StyleProp, ViewStyle } from 'react-native';
import Animated, {
    useAnimatedStyle,
    useSharedValue,
    withSpring,
} from 'react-native-reanimated';

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

/**
 * The touch-target floor, and deliberately *only* the box.
 *
 * A minimum size says nothing about how a caller wants their content arranged
 * inside it, so nothing here may set a layout property.
 */
const TOUCH_TARGET = { minHeight: 44, minWidth: 44 } as const;

/**
 * Does the caller's class string decide main-axis placement itself?
 *
 * This base style is merged **ahead of** the className, and it wins — so a
 * layout property written here is not a default, it is an override the caller
 * cannot see and cannot beat. `justifyContent: 'center'` used to sit in
 * `TOUCH_TARGET`, where it read as "centre the child in the 44px box", which is
 * what it does in the default column direction. The moment a caller passes
 * `flex-row`, `justifyContent` is the *horizontal* axis, so every
 * `flex-row justify-between` row on a `PressableScale` silently rendered as a
 * centred cluster with its trailing element glued to its label instead of
 * pinned to the right edge. Ten of them across the three apps, including all
 * nine rows of the customer's Settings screen.
 *
 * The rule is narrow on purpose: a caller who has stated a `justify-*` keeps
 * it, and a caller who has stated nothing keeps the centring they have always
 * had. An explicit `style` prop already won, because it merges after this.
 */
const CALLER_SETS_JUSTIFY = /(?:^|\s)justify-/;

interface PressableScaleProps extends PressableProps {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle> | ((state: { pressed: boolean }) => StyleProp<ViewStyle>);
  className?: string; // Support for NativeWind classNames
  accessibilityRole?: 'button' | 'link' | 'image' | 'header' | 'none';
  accessibilityLabel?: string;
  activeOpacity?: number;
}

export const PressableScale = React.forwardRef<any, PressableScaleProps>(({ children, style, accessibilityRole = 'button', accessibilityLabel, activeOpacity, ...props }, ref) => {
  const scale = useSharedValue(1);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const handlePressIn = (e: any) => {
    scale.value = withSpring(0.97, { mass: 1, damping: 15, stiffness: 300 });
    props.onPressIn?.(e);
  };

  const handlePressOut = (e: any) => {
    scale.value = withSpring(1, { mass: 1, damping: 15, stiffness: 300 });
    props.onPressOut?.(e);
  };

  return (
    <AnimatedPressable
      {...props}
      onPressIn={handlePressIn}
      onPressOut={handlePressOut}
      accessibilityRole={accessibilityRole}
      accessibilityLabel={accessibilityLabel}
      style={[
        TOUCH_TARGET,
        CALLER_SETS_JUSTIFY.test(props.className ?? '') ? null : { justifyContent: 'center' as const },
        animatedStyle,
        typeof style === 'function' ? style({ pressed: false }) : style,
      ]}
    >
      {children}
    </AnimatedPressable>
  );
});

export default PressableScale;
