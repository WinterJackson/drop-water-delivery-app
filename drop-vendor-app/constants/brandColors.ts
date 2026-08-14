/**
 * ╔═══════════════════════════════════════════════════════════════╗
 * ║  DROP BRAND COLOR SYSTEM — Easy to change!                   ║
 * ║  To update colors, ONLY edit the values below.               ║
 * ║  All splash screens, auth screens, and gradients will update.║
 * ╚═══════════════════════════════════════════════════════════════╝
 */

// ── Core Brand Colors ─────────────────────────────────────────────
export const BRAND = {
  /** Drop's primary brand color */
  primary: '#0295f7',
  /** Drop's signature gold — the anchor for all gradients */
  gold: '#0295f7',
  /** Secondary gold for text accents */
  goldLight: '#0295f7',
  /** Primary action blue */
  blue: '#3498db',
  /** Light mode background */
  bgLight: '#f0f0f0',
  /** Dark mode background */
  bgDark: '#000000',
  /** Pure white for text on gradients */
  white: '#FFFFFF',
  /** Dark text for light backgrounds */
  textDark: '#11181C',
  /** Search bar *placeholder* in dark mode (70% opacity). Not the typed term. */
  searchPlaceholderDark: 'rgba(255, 255, 255, 0.7)',
  /** Search bar *placeholder* in light mode (70% opacity). Not the typed term. */
  searchPlaceholderLight: 'rgba(0, 0, 0, 0.7)',
  /** Standard gray tones for borders, shadows, and text */
  gray100: '#f3f4f6',
  gray200: '#e5e7eb',
  gray300: '#d1d5db',
  gray400: '#9ca3af',
  gray500: '#6b7280',
  gray600: '#4b5563',
  gray700: '#374151',
  gray800: '#1f2937',
  gray900: '#111827',
  /** Favorite heart background */
  favorite: '#ef4444',
  /** Outline color for borders (Customer App compatibility) */
  outline: '#d1d5db',
} as const;

// ── App-Specific Gradient Palettes ────────────────────────────────
// Each app gets a unique gradient to differentiate personas.
// Change these 3-color arrays to instantly update splash + auth screens.

export const GRADIENTS = {
  /** Customer: Gold → Warm Amber → Deep Bronze */
  customer: ['#0295f7', '#b8860b', '#8B6914'] as const,
  /** Vendor: Gold → Blue → Indigo */
  vendor: ['#0295f7', '#3498db', '#2563eb'] as const,
  /** Rider: Gold → Emerald → Teal */
  rider: ['#0295f7', '#10b981', '#0d9488'] as const,
} as const;

// ── Dark Mode Gradient Variants ───────────────────────────────────
// Slightly darker/richer versions for dark theme

export const GRADIENTS_DARK = {
  customer: ['#a67c15', '#8B6914', '#5c4510'] as const,
  vendor: ['#a67c15', '#1e6bb5', '#1d4ed8'] as const,
  rider: ['#a67c15', '#059669', '#0f766e'] as const,
} as const;

// ── Glass Card Colors ─────────────────────────────────────────────
export const GLASS = {
  /** Card background overlay */
  bg: 'rgba(255, 255, 255, 0.15)',
  /** Card border */
  border: 'rgba(255, 255, 255, 0.3)',
  /** Divider line inside glass cards */
  divider: 'rgba(255, 255, 255, 0.2)',
  /** Button text on glass */
  textPrimary: '#FFFFFF',
  /** Subtle text on glass */
  textSecondary: 'rgba(255, 255, 255, 0.9)',
} as const;

// ── Standard UI Component Colors ──────────────────────────────────
export const TOAST = {
  success: '#10B981',
  successLight: '#ECFDF5',
  successDark: '#022C22',
  successBorderLight: '#A7F3D0',
  successBorderDark: '#065F46',
  error: '#EF4444',
  errorLight: '#FEF2F2',
  errorDark: '#450a0a',
  errorBorderLight: '#FECACA',
  errorBorderDark: '#991b1b',
  info: '#3B82F6',
  infoLight: '#EFF6FF',
  infoDark: '#172554',
  infoBorderLight: '#BFDBFE',
  infoBorderDark: '#1E3A8A',
  bgDark: '#1f2937',
  bgLight: '#ffffff',
  borderDark: '#374151',
  borderLight: '#e5e7eb',
  textDark: '#F9FAFB',
  textLight: '#111827',
  subTextDark: '#9CA3AF',
  subTextLight: '#6B7280'
} as const;

export const AVATAR = {
  placeholder: '#E5E7EB',
  text: '#FFFFFF',
  gradients: [
    ["#4F46E5", "#3B82F6"], // Indigo to Blue
    ["#10B981", "#059669"], // Emerald
    ["#F59E0B", "#D97706"], // Amber
    ["#EC4899", "#BE185D"], // Pink
    ["#8B5CF6", "#6D28D9"], // Violet
    ["#06B6D4", "#0369A1"], // Cyan to Light blue
  ] as const
} as const;

export const ERROR_BOUNDARY = {
  bgLight: '#ffffff',
  bgDark: '#0a0a0a',
  textLight: '#4b5563',
  textDark: '#9ca3af',
  subTextLight: '#9ca3af',
  subTextDark: '#6b7280',
} as const;

export type AppVariant = keyof typeof GRADIENTS;
