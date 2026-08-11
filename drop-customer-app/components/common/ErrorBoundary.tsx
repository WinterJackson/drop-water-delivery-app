import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { PressableScale } from "@/components/ui/PressableScale";
import { ERROR_BOUNDARY, BRAND } from '@/constants/brandColors';
import { UIThemeContext } from '@/context/ThemeContext';
import { captureError } from '@/utils/sentry';

const ErrorFallbackUI = ({ error, resetCount, maxResets, onReset }: any) => {
  const { currentTheme } = React.useContext(UIThemeContext);
  const isDark = currentTheme === "dark";

  return (
    <View style={[styles.container, { backgroundColor: isDark ? ERROR_BOUNDARY.bgDark : ERROR_BOUNDARY.bgLight }]}>
      <Text style={[styles.title, { color: isDark ? BRAND.white : BRAND.textDark }]}>Something went wrong</Text>
      <Text style={[styles.message, { color: isDark ? ERROR_BOUNDARY.subTextDark : ERROR_BOUNDARY.subTextLight }]} numberOfLines={3}>
        {(error as Error)?.message ?? 'An unexpected error occurred.'}
      </Text>
      {resetCount < maxResets ? (
        <PressableScale style={styles.button} onPress={onReset}>
          <Text style={styles.buttonText}>Try Again</Text>
        </PressableScale>
      ) : (
        <Text style={styles.crashLimit}>
          The app has crashed multiple times. Please restart the application.
        </Text>
      )}
    </View>
  );
};
interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  resetCount: number;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  onReset?: () => void;
}

/**
 * ErrorBoundary — shared across all 3 Drop apps.
 * Wrap at the navigator level to prevent full-app crashes.
 * Usage: <ErrorBoundary><NavigatorComponent /></ErrorBoundary>
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  static MAX_RESETS = 3;

  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, resetCount: 0 };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[FATAL_CRASH] Caught error:', (error as Error).message, info.componentStack);
    // The boundary swallows the crash, so without this the one class of error
    // that actually breaks a screen is the only class Sentry never sees.
    // No-ops when EXPO_PUBLIC_SENTRY_DSN is unset (initSentry skips init).
    if (!__DEV__) {
      captureError(error, {
        componentStack: info.componentStack,
        resetCount: this.state.resetCount,
      });
    }
  }

  handleReset = () => {
    this.setState((prev) => ({
      hasError: false,
      error: null,
      resetCount: prev.resetCount + 1,
    }));
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <ErrorFallbackUI 
          error={this.state.error}
          resetCount={this.state.resetCount}
          maxResets={ErrorBoundary.MAX_RESETS}
          onReset={this.handleReset}
        />
      );
    }

    return this.props.children;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  title: {
    fontSize: 22,
    fontFamily: 'Fredoka_600SemiBold',
    marginBottom: 12,
    textAlign: 'center',
  },
  message: {
    fontSize: 14,
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 20,
  },
  button: {
    backgroundColor: BRAND.blue,
    paddingHorizontal: 32,
    paddingVertical: 14,
    borderRadius: 12,
  },
  buttonText: {
    color: BRAND.white,
    fontSize: 16,
    fontFamily: 'Karla_600SemiBold',
  },
  crashLimit: {
    color: '#EF4444',
    fontSize: 14,
    textAlign: 'center' as const,
    marginTop: 8,
    lineHeight: 20,
  },
});

export default ErrorBoundary;
