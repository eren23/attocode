/**
 * TUI Error Boundary Component
 *
 * Catches JavaScript errors in child components and displays a fallback UI
 * instead of crashing the entire TUI. This is critical for stability in
 * long-running terminal sessions.
 *
 * Usage:
 * ```tsx
 * <TUIErrorBoundary name="MessageList">
 *   <MessageList messages={messages} />
 * </TUIErrorBoundary>
 * ```
 */

import React, { Component, type ReactNode, type ErrorInfo } from 'react';
import { Box, Text } from 'ink';
import { logger } from '../../integrations/logger.js';

interface ErrorBoundaryProps {
  /** Name for logging/display purposes */
  name: string;
  /** Child components to wrap */
  children: ReactNode;
  /** Custom fallback UI (optional) */
  fallback?: ReactNode;
  /** Callback when an error is caught */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
  /** Whether to show detailed error info (default: false in production) */
  showDetails?: boolean;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Error boundary component for TUI sections.
 *
 * Wraps critical TUI sections to prevent a single component error
 * from crashing the entire interface. Shows a clean fallback UI
 * and logs error details for debugging.
 */
export class TUIErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });

    // Log error for debugging
    logger.error(`[TUIErrorBoundary:${this.props.name}] Component error:`, { error: error.message, stack: error.stack });
    logger.error(`[TUIErrorBoundary:${this.props.name}] Component stack:`, { componentStack: errorInfo.componentStack ?? undefined });

    // Call optional error handler
    this.props.onError?.(error, errorInfo);
  }

  /**
   * Reset the error boundary state.
   * Can be called programmatically to retry rendering.
   */
  reset = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    const { hasError, error } = this.state;
    const { children, name, fallback, showDetails = false } = this.props;

    if (hasError) {
      // Return custom fallback if provided
      if (fallback) {
        return fallback;
      }

      // Default fallback UI
      return (
        <Box
          flexDirection="column"
          borderStyle="single"
          borderColor="#FF6B6B"
          paddingX={1}
          marginY={1}
        >
          <Box gap={1}>
            <Text color="#FF6B6B" bold>[X]</Text>
            <Text color="#FF6B6B" bold>{name} encountered an error</Text>
          </Box>
          {showDetails && error && (
            <Box marginTop={1} flexDirection="column">
              <Text color="#FFD700" dimColor>
                {error.name}: {error.message.slice(0, 100)}
                {error.message.length > 100 ? '...' : ''}
              </Text>
            </Box>
          )}
          <Box marginTop={1}>
            <Text color="#666" dimColor>
              This section has been disabled to prevent TUI crash.
            </Text>
          </Box>
        </Box>
      );
    }

    return children;
  }
}

/**
 * Simple error fallback component for minimal display.
 */
export function ErrorFallback({
  message = 'Component error',
  compact = false,
}: {
  message?: string;
  compact?: boolean;
}): JSX.Element {
  if (compact) {
    return (
      <Box>
        <Text color="#FF6B6B">[!] {message}</Text>
      </Box>
    );
  }

  return (
    <Box borderStyle="round" borderColor="#FF6B6B" paddingX={1}>
      <Text color="#FF6B6B">[X] {message}</Text>
    </Box>
  );
}

/**
 * HOC to wrap a component with error boundary.
 */
export function withErrorBoundary<P extends object>(
  WrappedComponent: React.ComponentType<P>,
  boundaryName: string,
  options?: Omit<ErrorBoundaryProps, 'name' | 'children'>
): React.FC<P> {
  const WithErrorBoundary: React.FC<P> = (props: P) => (
    <TUIErrorBoundary name={boundaryName} {...options}>
      <WrappedComponent {...props} />
    </TUIErrorBoundary>
  );

  WithErrorBoundary.displayName = `withErrorBoundary(${WrappedComponent.displayName || WrappedComponent.name || 'Component'})`;

  return WithErrorBoundary;
}

export default TUIErrorBoundary;
