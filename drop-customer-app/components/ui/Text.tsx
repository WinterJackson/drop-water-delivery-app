import React from 'react';
import {
  Text as RNText,
  TextInput as RNTextInput,
  type TextInputProps,
  type TextProps,
} from 'react-native';

/**
 * `Text` and `TextInput` with the platform's body font already on them.
 *
 * React Native has no cascade. A font set on a parent view does not reach the
 * text inside it, there is no `html { font-family }` to inherit from, and every
 * `<Text>` that names no family renders in whatever face the OS picked —
 * Roboto on Android, San Francisco on iOS. Three apps that all use the system
 * font are three apps that look different on every handset and match neither
 * the console nor each other.
 *
 * So the default has to be attached per element. Doing that by hand across
 * ~1,700 call sites would be a one-off rewrite that the next screen anyone
 * writes immediately breaks, and it cannot be done at all where the class
 * string is assembled somewhere else — `<Text className={labelStyle}>` is a
 * real pattern here, and a find-and-replace cannot see inside `labelStyle`.
 * Resolving it at render time handles both: the check runs on the final string,
 * whatever built it and whichever branch produced it.
 *
 * An explicit family always wins. `font-sans-bold`, `font-heading-semibold` and
 * `font-mono` are left exactly as written; the default only fills the gap.
 */

/**
 * Matches a family token — `font-sans`, `font-sans-bold`, `font-heading-medium`,
 * `font-mono-semibold`. Deliberately *not* a match for a bare weight utility
 * like `font-bold`, which sets `fontWeight` and no family: that one is the case
 * the default exists to catch.
 */
const FAMILY_TOKEN = /(?:^|\s)font-(?:sans|heading|mono)(?:-[a-z]+)?(?:\s|$)/;

/**
 * Class strings are stable per call site, so the same handful of values recur
 * for the life of the process. Bounded because a few are interpolated and would
 * otherwise grow without limit.
 */
const resolved = new Map<string, string>();
const CACHE_LIMIT = 512;

export function withDefaultFont(className?: string): string {
  const given = className ?? '';
  const hit = resolved.get(given);
  if (hit !== undefined) return hit;

  const out = FAMILY_TOKEN.test(given) ? given : `font-sans ${given}`.trimEnd();
  if (resolved.size < CACHE_LIMIT) resolved.set(given, out);
  return out;
}

export const Text = React.forwardRef<
  React.ComponentRef<typeof RNText>,
  TextProps & { className?: string }
>(({ className, ...props }, ref) => (
  <RNText ref={ref} className={withDefaultFont(className)} {...props} />
));
Text.displayName = 'Text';

/**
 * The handle a `ref` on the input below receives. `TextInput` is a value here,
 * not a class, so `useRef<TextInput>(null)` — which worked when the import came
 * straight from react-native — no longer type-checks. This is the replacement.
 */
export type TextInputRef = React.ComponentRef<typeof RNTextInput>;

export const TextInput = React.forwardRef<
  TextInputRef,
  TextInputProps & { className?: string }
>(({ className, ...props }, ref) => (
  <RNTextInput ref={ref} className={withDefaultFont(className)} {...props} />
));
TextInput.displayName = 'TextInput';

export default Text;
