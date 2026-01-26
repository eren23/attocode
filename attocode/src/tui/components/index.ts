/**
 * Core UI Components
 *
 * These components are used by the TUI in src/tui/app.tsx.
 * They follow the anti-flicker pattern: no internal useInput hooks,
 * parent handles all keyboard input.
 */

export { ScrollableBox, type ScrollableBoxProps } from './ScrollableBox.js';

// Memoized components extracted from main.ts
export { MessageItem, type MessageItemProps, type TUIMessage } from './MessageItem.js';
export { ToolCallItem, type ToolCallItemProps, type ToolCallDisplayItem } from './ToolCallItem.js';
export { MemoizedInputArea, type InputAreaProps } from './InputArea.js';
