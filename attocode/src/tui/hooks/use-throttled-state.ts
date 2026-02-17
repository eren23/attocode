/**
 * useThrottledState - Throttles React state updates to reduce re-renders.
 *
 * Wraps useState with a throttled setter that batches rapid updates,
 * only applying the latest value after the throttle interval.
 * Useful for high-frequency events (tool calls, agent phases, token updates).
 */

import { useState, useRef, useCallback, useEffect } from 'react';

/**
 * Like useState, but the setter is throttled: at most one render per `intervalMs`.
 * The latest value is always applied when the throttle window ends.
 */
export function useThrottledState<T>(
  initialValue: T,
  intervalMs: number,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState(initialValue);
  const pendingRef = useRef<{ value: T | ((prev: T) => T) } | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastUpdateRef = useRef(0);

  const throttledSet = useCallback(
    (value: T | ((prev: T) => T)) => {
      const now = Date.now();
      const elapsed = now - lastUpdateRef.current;

      if (elapsed >= intervalMs) {
        // Enough time has passed — apply immediately
        lastUpdateRef.current = now;
        setState(value);
        pendingRef.current = null;
      } else {
        // Within throttle window — queue the latest value
        pendingRef.current = { value };
        if (!timerRef.current) {
          timerRef.current = setTimeout(() => {
            timerRef.current = null;
            if (pendingRef.current) {
              lastUpdateRef.current = Date.now();
              setState(pendingRef.current.value);
              pendingRef.current = null;
            }
          }, intervalMs - elapsed);
        }
      }
    },
    [intervalMs],
  );

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  return [state, throttledSet];
}

/**
 * Creates a throttled version of any callback.
 * Unlike useThrottledState, this doesn't manage state — just limits call frequency.
 */
export function useThrottledCallback<T extends (...args: any[]) => void>(
  callback: T,
  intervalMs: number,
): T {
  const lastCallRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingArgsRef = useRef<Parameters<T> | null>(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const throttled = useCallback(
    (...args: Parameters<T>) => {
      const now = Date.now();
      const elapsed = now - lastCallRef.current;

      if (elapsed >= intervalMs) {
        lastCallRef.current = now;
        callbackRef.current(...args);
        pendingArgsRef.current = null;
      } else {
        pendingArgsRef.current = args;
        if (!timerRef.current) {
          timerRef.current = setTimeout(() => {
            timerRef.current = null;
            if (pendingArgsRef.current) {
              lastCallRef.current = Date.now();
              callbackRef.current(...pendingArgsRef.current);
              pendingArgsRef.current = null;
            }
          }, intervalMs - elapsed);
        }
      }
    },
    [intervalMs],
  ) as T;

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  return throttled;
}
