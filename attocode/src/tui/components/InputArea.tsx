/**
 * InputArea Component
 *
 * Memoized input area that manages own state to prevent parent re-renders.
 * Also handles ALL keyboard input to prevent multiple useInput hooks.
 */

import React, { memo, useState, useRef } from 'react';
import { Box, Text, useInput } from 'ink';

export interface InputAreaProps {
  onSubmit: (value: string) => void;
  disabled: boolean;
  borderColor: string;
  textColor: string;
  cursorColor: string;
  // Global keyboard handlers to avoid multiple useInput hooks
  onCtrlC?: () => void;
  onCtrlL?: () => void;
  onCtrlP?: () => void;
  onEscape?: () => void;
  onToggleToolExpand?: () => void;
  onToggleThinking?: () => void;
  // Scroll handlers for message navigation
  onPageUp?: () => void;
  onPageDown?: () => void;
  onHome?: () => void;
  onEnd?: () => void;
}

/**
 * Memoized input area with centralized keyboard handling.
 *
 * Key patterns used:
 * - Callbacks stored in refs to prevent useInput re-subscription
 * - Custom memo comparator for controlled re-rendering
 * - Single useInput hook for all keyboard handling
 */
export const MemoizedInputArea = memo(function MemoizedInputArea({
  onSubmit,
  disabled,
  borderColor,
  textColor,
  cursorColor,
  onCtrlC,
  onCtrlL,
  onCtrlP,
  onEscape,
  onToggleToolExpand,
  onToggleThinking,
  onPageUp,
  onPageDown,
  onHome,
  onEnd,
}: InputAreaProps) {
  const [value, setValue] = useState('');
  const [cursorPos, setCursorPos] = useState(0);

  // Store callbacks in refs so useInput doesn't re-subscribe on prop changes
  const callbacksRef = useRef({
    onSubmit, onCtrlC, onCtrlL, onCtrlP, onEscape,
    onToggleToolExpand, onToggleThinking,
    onPageUp, onPageDown, onHome, onEnd
  });
  // Update refs on every render (but don't cause re-render)
  callbacksRef.current = {
    onSubmit, onCtrlC, onCtrlL, onCtrlP, onEscape,
    onToggleToolExpand, onToggleThinking,
    onPageUp, onPageDown, onHome, onEnd
  };
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  useInput((input, key) => {
    const cb = callbacksRef.current;
    // Global shortcuts (always active)
    if (key.ctrl && input === 'c') {
      cb.onCtrlC?.();
      return;
    }
    if (key.ctrl && input === 'l') {
      cb.onCtrlL?.();
      return;
    }
    if (key.ctrl && input === 'p') {
      cb.onCtrlP?.();
      return;
    }
    if (key.escape) {
      cb.onEscape?.();
      return;
    }
    // Alt+T / Option+T (produces 'dagger' on macOS)
    if (input === '\u2020' || (key.meta && input === 't')) {
      cb.onToggleToolExpand?.();
      return;
    }
    // Alt+O / Option+O (produces 'oslash' on macOS)
    if (input === '\u00f8' || (key.meta && input === 'o')) {
      cb.onToggleThinking?.();
      return;
    }

    // Scroll navigation (always active)
    if (key.pageUp) {
      cb.onPageUp?.();
      return;
    }
    if (key.pageDown) {
      cb.onPageDown?.();
      return;
    }
    // Ctrl+Home (go to first message) and Ctrl+End (go to last message)
    if (key.ctrl && key.upArrow) {
      cb.onHome?.();
      return;
    }
    if (key.ctrl && key.downArrow) {
      cb.onEnd?.();
      return;
    }

    // Input handling (only when not disabled)
    if (disabledRef.current) return;

    // Submit on Enter
    if (key.return && value.trim()) {
      cb.onSubmit(value);
      setValue('');
      setCursorPos(0);
      return;
    }

    // Backspace
    if (key.backspace || key.delete) {
      if (cursorPos > 0) {
        setValue(v => v.slice(0, cursorPos - 1) + v.slice(cursorPos));
        setCursorPos(p => p - 1);
      }
      return;
    }

    // Arrow keys
    if (key.leftArrow) {
      setCursorPos(p => Math.max(0, p - 1));
      return;
    }
    if (key.rightArrow) {
      setCursorPos(p => Math.min(value.length, p + 1));
      return;
    }

    // Ctrl+A: start of line
    if (key.ctrl && input === 'a') {
      setCursorPos(0);
      return;
    }

    // Ctrl+E: end of line
    if (key.ctrl && input === 'e') {
      setCursorPos(value.length);
      return;
    }

    // Ctrl+U: clear line
    if (key.ctrl && input === 'u') {
      setValue('');
      setCursorPos(0);
      return;
    }

    // Regular character input
    if (input && !key.ctrl && !key.meta) {
      setValue(v => v.slice(0, cursorPos) + input + v.slice(cursorPos));
      setCursorPos(p => p + input.length);
    }
  });

  return React.createElement(Box, {
    borderStyle: 'round',
    borderColor: disabledRef.current ? '#666' : borderColor,
    paddingX: 1,
  },
    React.createElement(Text, { color: textColor, bold: true }, '> '),
    React.createElement(Text, {}, value.slice(0, cursorPos)),
    !disabled && React.createElement(Text, { backgroundColor: cursorColor, color: '#1a1a2e' },
      value[cursorPos] ?? ' '
    ),
    React.createElement(Text, {}, value.slice(cursorPos + 1))
  );
}, (prevProps, nextProps) => {
  // Custom comparison: only re-render if visual props change
  // Callbacks are stored in refs so we don't care if they change
  return prevProps.disabled === nextProps.disabled &&
         prevProps.borderColor === nextProps.borderColor &&
         prevProps.textColor === nextProps.textColor &&
         prevProps.cursorColor === nextProps.cursorColor;
});

export default MemoizedInputArea;
