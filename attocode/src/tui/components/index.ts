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

// Approval dialog for permission requests
export { ApprovalDialog, type ApprovalDialogProps, type ApprovalRequest } from './ApprovalDialog.js';

// Diff display components with syntax highlighting support
export { DiffView, type UnifiedDiff, type DiffHunk, type DiffLine } from './DiffView.js';
export { SideBySideDiff, type SideBySideDiffProps, type AlignedPair } from './SideBySideDiff.js';
export { CollapsibleDiffView, type CollapsibleDiffViewProps } from './CollapsibleDiffView.js';
export { FileChangeSummary } from './FileChangeSummary.js';

// Syntax highlighting component
export { SyntaxText, MemoizedSyntaxText, SyntaxLine, MemoizedSyntaxLine, type SyntaxTextProps, type SyntaxLineProps } from './SyntaxText.js';

// Error boundaries
export { TUIErrorBoundary, ErrorFallback, withErrorBoundary } from './ErrorBoundary.js';

// Active agents panel (subagent visibility)
export {
  ActiveAgentsPanel,
  type ActiveAgentsPanelProps,
  type ActiveAgent,
  type ActiveAgentStatus,
} from './ActiveAgentsPanel.js';

// Tasks panel (task tracking visibility)
export { TasksPanel, type TasksPanelProps } from './TasksPanel.js';

// Debug panel (debug logging visibility)
export { DebugPanel, useDebugBuffer, type DebugEntry, type DebugPanelProps } from './DebugPanel.js';

// Error detail panel (expandable stack traces)
export {
  ErrorDetailPanel,
  parseStackTrace,
  formatPath,
  type ErrorDetail,
  type ErrorDetailPanelProps,
  type StackFrame,
} from './ErrorDetailPanel.js';
