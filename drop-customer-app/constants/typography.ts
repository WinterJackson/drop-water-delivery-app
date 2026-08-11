/**
 * Typography scale for the screens that style with `StyleSheet` rather than
 * NativeWind — the splash sequence and the Auth flow.
 *
 * The same two faces the rest of the platform uses: Fredoka for the display and
 * heading tiers, Karla for body, captions and buttons. Every entry names a real
 * registered face and none sets `fontWeight`, because React Native pairs a
 * `fontFamily` with a `fontWeight` by thickening the strokes itself instead of
 * loading the weight — the faked bold that `font-synthesis-weight: none` turns
 * off on the console has no equivalent switch here.
 *
 * Fredoka stops at 600. `display` and `heading1` asked for Bold when this scale
 * was Inter; they take SemiBold now, which is the heaviest weight the platform
 * loads.
 */
import { TextStyle } from 'react-native';

export const typography: Record<string, TextStyle> = {
  display: {
    fontFamily: 'Fredoka_600SemiBold',
    fontSize: 36,
    lineHeight: 44,
    letterSpacing: -0.5,
  },
  heading1: {
    fontFamily: 'Fredoka_600SemiBold',
    fontSize: 28,
    lineHeight: 36,
    letterSpacing: -0.3,
  },
  heading2: {
    fontFamily: 'Fredoka_500Medium',
    fontSize: 24,
    lineHeight: 32,
  },
  heading3: {
    fontFamily: 'Fredoka_500Medium',
    fontSize: 20,
    lineHeight: 28,
  },
  body: {
    fontFamily: 'Karla_400Regular',
    fontSize: 16,
    lineHeight: 24,
  },
  bodyMedium: {
    fontFamily: 'Karla_500Medium',
    fontSize: 16,
    lineHeight: 24,
  },
  caption: {
    fontFamily: 'Karla_400Regular',
    fontSize: 14,
    lineHeight: 20,
  },
  button: {
    fontFamily: 'Karla_600SemiBold',
    fontSize: 17,
    lineHeight: 22,
    letterSpacing: 0.3,
  },
};
