/**
 * Core UI Components
 *
 * These components are used by the TUI in src/tui/app.tsx.
 * They follow the anti-flicker pattern: no internal useInput hooks,
 * parent handles all keyboard input.
 */

export { ScrollableBox, type ScrollableBoxProps } from './ScrollableBox.js';
export { CodeBlock, type CodeBlockProps } from './CodeBlock.js';
export { ToolCall, ToolCallList, type ToolCallProps, type ToolCallListProps } from './ToolCall.js';
