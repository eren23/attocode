/**
 * useAnimationLoop Hook
 *
 * Runs a requestAnimationFrame loop, calling the provided callback
 * with the elapsed delta in milliseconds on each frame.
 * Starts/stops based on the `active` flag.
 */

import { useRef, useEffect, useCallback } from 'react';

export function useAnimationLoop(
  callback: (deltaMs: number) => void,
  active: boolean
): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const rafIdRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);

  const tick = useCallback((time: number) => {
    if (lastTimeRef.current === 0) {
      lastTimeRef.current = time;
    }
    const delta = time - lastTimeRef.current;
    lastTimeRef.current = time;
    callbackRef.current(delta);
    rafIdRef.current = requestAnimationFrame(tick);
  }, []);

  useEffect(() => {
    if (active) {
      lastTimeRef.current = 0;
      rafIdRef.current = requestAnimationFrame(tick);
    } else {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = 0;
      }
      lastTimeRef.current = 0;
    }

    return () => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = 0;
      }
    };
  }, [active, tick]);
}
