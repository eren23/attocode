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
import { DiffView } from './components/DiffView.js';
import { ActiveAgentsPanel, type ActiveAgent, type ActiveAgentStatus } from './components/ActiveAgentsPanel.js';
import { TasksPanel } from './components/TasksPanel.js';
import type { Task } from '../integrations/task-manager.js';
import type { ProductionAgent } from '../agent.js';
import type { SQLiteStore } from '../integrations/sqlite-store.js';
import type { MCPClient } from '../integrations/mcp-client.js';
import type { Compactor } from '../integrations/compaction.js';
import type { ThemeColors, CommandPaletteItem } from './types.js';
import { getTheme, getThemeNames } from './theme/index.js';
import { ControlledCommandPalette } from './input/CommandPalette.js';
import { ApprovalDialog } from './components/ApprovalDialog.js';
import type { TUIApprovalBridge } from '../adapters.js';
import type { ApprovalRequest as TypesApprovalRequest, AgentEvent } from '../types.js';
import { TransparencyAggregator, formatTransparencyState, type TransparencyState } from './transparency-aggregator.js';
import { handleSkillsCommand, formatEnhancedSkillList } from '../commands/skills-commands.js';
import { handleAgentsCommand, formatEnhancedAgentList } from '../commands/agents-commands.js';
import { handleInitCommand } from '../commands/init-commands.js';
import type { CommandOutput } from '../commands/types.js';

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
    // Extract base command: "npm test --coverage" → "npm test"
    const parts = args.command.trim().split(/\s+/);
    const baseCmd = parts.slice(0, 2).join(' '); // First 2 tokens
    return `bash:${baseCmd}`;
  }

  if (['write_file', 'edit_file', 'read_file'].includes(tool)) {
    const path = (args.path || args.file_path || '') as string;
    return `${tool}:${path}`;
  }

  // Default: tool + first string argument
  const firstStringArg = Object.values(args).find(v => typeof v === 'string') as string | undefined;
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
}

/** TUI message display format */
interface TUIMessage {
  id: string;
  role: string;
  content: string;
  ts: Date;
}

/** Tool call display item */
interface ToolCallDisplayItem {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: 'pending' | 'running' | 'success' | 'error';
  result?: unknown;
  error?: string;
  duration?: number;
  startTime?: Date;
}

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
        <Text color={roleColor} bold>{icon}</Text>
        <Text color={roleColor} bold>{label}</Text>
        <Text color={colors.textMuted} dimColor>
          {` ${msg.ts.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`}
        </Text>
      </Box>
      <Box marginLeft={2}>
        <Text wrap="wrap" color={isError ? colors.error : colors.text}>{msg.content}</Text>
      </Box>
    </Box>
  );
});

// =============================================================================
// MEMOIZED TOOL CALL ITEM
// =============================================================================

interface ToolCallItemProps {
  tc: ToolCallDisplayItem;
  expanded: boolean;
  colors: ThemeColors;
}

const ToolCallItem = memo(function ToolCallItem({ tc, expanded, colors }: ToolCallItemProps) {
  const icon = tc.status === 'success' ? '[OK]' : tc.status === 'error' ? '[X]' : tc.status === 'running' ? '[~]' : '[ ]';
  const statusColor = tc.status === 'success' ? '#98FB98' : tc.status === 'error' ? '#FF6B6B' : tc.status === 'running' ? '#87CEEB' : colors.textMuted;

  // Compact formatting for collapsed view
  const formatToolArgsCompact = (args: Record<string, unknown>): string => {
    const entries = Object.entries(args);
    if (entries.length === 0) return '';
    if (entries.length === 1) {
      const [key, val] = entries[0];
      const valStr = typeof val === 'string' ? val : JSON.stringify(val);
      return valStr.length > 50 ? `${key}: ${valStr.slice(0, 47)}...` : `${key}: ${valStr}`;
    }
    return `{${entries.length} args}`;
  };

  // Expanded formatting - each arg on its own line with proper handling
  const formatToolArgsExpanded = (args: Record<string, unknown>): string[] => {
    const entries = Object.entries(args);
    if (entries.length === 0) return [];

    return entries.map(([key, val]) => {
      let valStr: string;
      if (typeof val === 'string') {
        // For strings, show with quotes, handle multiline
        if (val.includes('\n')) {
          const lines = val.split('\n');
          if (lines.length > 3) {
            valStr = `"${lines.slice(0, 3).join('\\n')}..." (${lines.length} lines)`;
          } else {
            valStr = `"${val.replace(/\n/g, '\\n')}"`;
          }
        } else if (val.length > 100) {
          valStr = `"${val.slice(0, 97)}..."`;
        } else {
          valStr = `"${val}"`;
        }
      } else if (typeof val === 'object' && val !== null) {
        const json = JSON.stringify(val, null, 2);
        if (json.length > 200) {
          valStr = JSON.stringify(val).slice(0, 197) + '...';
        } else {
          valStr = json;
        }
      } else {
        valStr = String(val);
      }
      return `${key}: ${valStr}`;
    });
  };

  const argsStr = formatToolArgsCompact(tc.args);

  if (expanded) {
    const expandedArgs = formatToolArgsExpanded(tc.args);

    return (
      <Box marginLeft={2} flexDirection="column">
        <Box gap={1}>
          <Text color={statusColor}>{icon}</Text>
          <Text color="#DDA0DD" bold>{tc.name}</Text>
          {tc.duration ? <Text color={colors.textMuted} dimColor>({tc.duration}ms)</Text> : null}
        </Box>
        {/* Show each arg on its own line for readability */}
        {expandedArgs.map((argLine, i) => (
          <Box key={i} marginLeft={3}>
            <Text color="#87CEEB" dimColor>{argLine}</Text>
          </Box>
        ))}
        {tc.status === 'success' && tc.result !== undefined && tc.result !== null ? (
          <Box marginLeft={3} flexDirection="column">
            {/* Show diff if available for file operations */}
            {(tc.name === 'edit_file' || tc.name === 'write_file') &&
             typeof tc.result === 'object' && tc.result !== null &&
             'metadata' in tc.result &&
             typeof (tc.result as { metadata?: { diff?: string } }).metadata?.diff === 'string' ? (
              <DiffView
                diff={(tc.result as { metadata: { diff: string } }).metadata.diff}
                expanded={true}
                maxLines={15}
              />
            ) : (
              <Text color="#98FB98" dimColor>
                {`-> ${String(tc.result).slice(0, 150)}${String(tc.result).length > 150 ? '...' : ''}`}
              </Text>
            )}
          </Box>
        ) : null}
        {tc.status === 'error' && tc.error && (
          <Box marginLeft={3}>
            <Text color="#FF6B6B">{`x ${tc.error}`}</Text>
          </Box>
        )}
      </Box>
    );
  }

  // Check if result has diff metadata for collapsed summary
  const hasDiff = tc.status === 'success' &&
    (tc.name === 'edit_file' || tc.name === 'write_file') &&
    typeof tc.result === 'object' && tc.result !== null &&
    'metadata' in tc.result &&
    typeof (tc.result as { metadata?: { diff?: string } }).metadata?.diff === 'string';

  return (
    <Box marginLeft={2} gap={1}>
      <Text color={statusColor}>{icon}</Text>
      <Text color="#DDA0DD" bold>{tc.name}</Text>
      {argsStr ? <Text color={colors.textMuted} dimColor>{argsStr}</Text> : null}
      {/* Show diff summary in collapsed view */}
      {hasDiff && (
        <DiffView
          diff={(tc.result as { metadata: { diff: string } }).metadata.diff}
          expanded={false}
        />
      )}
      {tc.duration ? <Text color={colors.textMuted} dimColor>({tc.duration}ms)</Text> : null}
    </Box>
  );
});

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
}

const MemoizedInputArea = memo(function MemoizedInputArea({
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
}: MemoizedInputAreaProps) {
  const [value, setValue] = useState('');
  const [cursorPos, setCursorPos] = useState(0);

  // Store callbacks in refs so useInput doesn't re-subscribe on prop changes
  const callbacksRef = useRef({
    onSubmit, onCtrlC, onCtrlL, onCtrlP, onEscape,
    onToggleToolExpand, onToggleThinking, onToggleTransparency, onToggleActiveAgents, onToggleTasks,
    onPageUp, onPageDown, onHome, onEnd,
    commandPaletteOpen, onCommandPaletteInput,
    approvalDialogOpen, approvalDenyReasonMode,
    onApprovalApprove, onApprovalAlwaysAllow, onApprovalDeny, onApprovalDenyWithReason,
    onApprovalCancelDenyReason, onApprovalDenyReasonInput,
  });
  callbacksRef.current = {
    onSubmit, onCtrlC, onCtrlL, onCtrlP, onEscape,
    onToggleToolExpand, onToggleThinking, onToggleTransparency, onToggleActiveAgents, onToggleTasks,
    onPageUp, onPageDown, onHome, onEnd,
    commandPaletteOpen, onCommandPaletteInput,
    approvalDialogOpen, approvalDenyReasonMode,
    onApprovalApprove, onApprovalAlwaysAllow, onApprovalDeny, onApprovalDenyWithReason,
    onApprovalCancelDenyReason, onApprovalDenyReasonInput,
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

    if (key.return && value.trim()) {
      cb.onSubmit(value);
      setValue('');
      setCursorPos(0);
      return;
    }

    if (key.backspace || key.delete) {
      if (cursorPos > 0) {
        setValue(v => v.slice(0, cursorPos - 1) + v.slice(cursorPos));
        setCursorPos(p => p - 1);
      }
      return;
    }

    if (key.leftArrow) {
      setCursorPos(p => Math.max(0, p - 1));
      return;
    }
    if (key.rightArrow) {
      setCursorPos(p => Math.min(value.length, p + 1));
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
      setValue(v => v.slice(0, cursorPos) + input + v.slice(cursorPos));
      setCursorPos(p => p + input.length);
    }
  });

  return (
    <Box
      borderStyle="round"
      borderColor={disabledRef.current ? '#666' : borderColor}
      paddingX={1}
    >
      <Text color={textColor} bold>{'>'} </Text>
      <Text>{value.slice(0, cursorPos)}</Text>
      {!disabled && (
        <Text backgroundColor={cursorColor} color="#1a1a2e">
          {value[cursorPos] ?? ' '}
        </Text>
      )}
      <Text>{value.slice(cursorPos + 1)}</Text>
    </Box>
  );
}, (prevProps, nextProps) => {
  // Custom comparison: only re-render if visual props change
  return prevProps.disabled === nextProps.disabled &&
         prevProps.borderColor === nextProps.borderColor &&
         prevProps.textColor === nextProps.textColor &&
         prevProps.cursorColor === nextProps.cursorColor &&
         prevProps.commandPaletteOpen === nextProps.commandPaletteOpen &&
         prevProps.approvalDialogOpen === nextProps.approvalDialogOpen &&
         prevProps.approvalDenyReasonMode === nextProps.approvalDenyReasonMode;
});

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
}: TUIAppProps) {
  const { exit } = useApp();
  const [messages, setMessages] = useState<TUIMessage[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const initialModeInfo = agent.getModeInfo();
  const initialMode = initialModeInfo.name === 'Plan' ? 'ready (plan)' : 'ready';
  const [status, setStatus] = useState({ iter: 0, tokens: 0, cost: 0, mode: initialMode });
  const [toolCalls, setToolCalls] = useState<ToolCallDisplayItem[]>([]);
  const [currentThemeName, setCurrentThemeName] = useState<string>(theme);
  const [contextTokens, setContextTokens] = useState(0);
  const [elapsedTime, setElapsedTime] = useState(0);
  const processingStartRef = useRef<number | null>(null);

  // Execution mode to prevent duplicate event handling
  // 'idle' = no active execution, 'processing' = handleSubmit running, 'approving' = /approve running
  type ExecutionMode = 'idle' | 'processing' | 'approving';
  const [executionMode, setExecutionMode] = useState<ExecutionMode>('idle');
  const executionModeRef = useRef<ExecutionMode>('idle');

  // Display toggles
  const [toolCallsExpanded, setToolCallsExpanded] = useState(false);
  const [showThinking, setShowThinking] = useState(true);
  const [transparencyExpanded, setTransparencyExpanded] = useState(false);
  const [activeAgentsExpanded, setActiveAgentsExpanded] = useState(true);
  const [tasksExpanded, setTasksExpanded] = useState(true);

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

  // Transparency state
  const [transparencyState, setTransparencyState] = useState<TransparencyState | null>(null);
  const transparencyAggregatorRef = useRef<TransparencyAggregator | null>(null);

  // Refs for stable callbacks
  const isProcessingRef = useRef(isProcessing);
  const messagesLengthRef = useRef(messages.length);
  const pendingApprovalRef = useRef(pendingApproval);
  isProcessingRef.current = isProcessing;
  messagesLengthRef.current = messages.length;
  pendingApprovalRef.current = pendingApproval;

  // Derive theme and colors
  const selectedTheme = getTheme(currentThemeName);
  const colors = selectedTheme.colors;

  const messageIdCounter = useRef(0);
  const addMessage = useCallback((role: string, content: string) => {
    const uniqueId = `${role}-${Date.now()}-${++messageIdCounter.current}`;
    setMessages(prev => [...prev, { id: uniqueId, role, content, ts: new Date() }]);
  }, []);

  // =========================================================================
  // APPROVAL DIALOG HANDLERS
  // =========================================================================

  // Handle approval request from bridge
  const handleApprovalRequest = useCallback((request: TypesApprovalRequest) => {
    // Check if this matches an always-allowed pattern
    const pattern = generateApprovalPattern(request);
    if (alwaysAllowed.has(pattern)) {
      // Auto-approve without showing dialog
      approvalBridge?.resolve({ approved: true });
      return;
    }

    // Show dialog as normal
    setPendingApproval(request);
    setDenyReasonMode(false);
    setDenyReason('');
  }, [alwaysAllowed, approvalBridge]);

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
  const handleDeny = useCallback((reason?: string) => {
    if (approvalBridge && pendingApprovalRef.current) {
      approvalBridge.resolve({ approved: false, reason: reason || 'User denied' });
      setPendingApproval(null);
      setDenyReasonMode(false);
      setDenyReason('');
    }
  }, [approvalBridge]);

  // Always allow this pattern for the rest of the session
  const handleAlwaysAllow = useCallback(() => {
    if (approvalBridge && pendingApprovalRef.current) {
      const pattern = generateApprovalPattern(pendingApprovalRef.current);
      setAlwaysAllowed(prev => new Set(prev).add(pattern));
      approvalBridge.resolve({ approved: true });
      setPendingApproval(null);
      setDenyReasonMode(false);
      setDenyReason('');
    }
  }, [approvalBridge]);

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

  // =========================================================================
  // UNIFIED EVENT HANDLER
  // Consolidated handler for all agent events - prevents duplicate messages
  // =========================================================================

  const handleAgentEvent = useCallback((event: AgentEvent) => {
    const mode = executionModeRef.current;
    if (mode === 'idle') return; // No active execution, ignore events

    // Extract subagent from event if present (not all events have it)
    const eventWithSubagent = event as { subagent?: string };
    const subagentPrefix = eventWithSubagent.subagent ? `[${eventWithSubagent.subagent}] ` : '';

    // -------------------------------------------------------------------------
    // Approving-only events (plan execution)
    // -------------------------------------------------------------------------
    if (mode === 'approving') {
      if (event.type === 'plan.approved') {
        const e = event as { changeCount: number };
        addMessage('system', `[PLAN] Executing ${e.changeCount} change(s)...`);
        return;
      }
      if (event.type === 'plan.executing') {
        const e = event as { changeIndex: number; totalChanges: number };
        setStatus(s => ({ ...s, mode: `executing ${e.changeIndex + 1}/${e.totalChanges}` }));
        return;
      }
    }

    // -------------------------------------------------------------------------
    // Shared events (both processing and approving modes)
    // -------------------------------------------------------------------------

    // Subagent lifecycle events - also update Active Agents Panel
    if (event.type === 'agent.spawn') {
      const e = event as { agentId: string; name: string; task: string };
      const agentId = e.agentId || `spawn-${Date.now()}`;
      addMessage('system', `[AGENT] Spawning ${e.name}: ${e.task.slice(0, 100)}${e.task.length > 100 ? '...' : ''}`);
      // Add to active agents panel
      setActiveAgents(prev => [...prev, {
        id: agentId,
        type: e.name,
        task: e.task,
        status: 'running' as ActiveAgentStatus,
        tokens: 0,
        startTime: Date.now(),
      }]);
      return;
    }
    if (event.type === 'agent.complete') {
      const e = event as { agentId: string; success: boolean; output?: string };
      const statusText = e.success ? 'completed' : 'failed';
      addMessage('system', `[AGENT] ${e.agentId} ${statusText}`);
      // Show output preview if substantive
      if (e.output && e.output.length > 50) {
        const preview = e.output.slice(0, 300);
        addMessage('system', `[AGENT OUTPUT]\n${preview}${e.output.length > 300 ? '\n...(truncated)' : ''}`);
      }
      // Update active agents panel
      setActiveAgents(prev => prev.map(a =>
        a.type === e.agentId || a.id.includes(e.agentId)
          ? { ...a, status: e.success ? 'completed' as ActiveAgentStatus : 'error' as ActiveAgentStatus }
          : a
      ));
      return;
    }
    if (event.type === 'agent.error') {
      const e = event as { agentId: string; error: string };
      addMessage('system', `[AGENT] ${e.agentId} error: ${e.error}`);

      // For timeout errors, use 'timing_out' status first to indicate the agent
      // is in the process of stopping. Then transition to 'timeout' after a delay.
      // This provides better UX than immediately showing "failed" while tokens accumulate.
      const isTimeout = e.error.includes('timed out') || e.error.includes('Timed out');

      if (isTimeout) {
        // First, mark as timing_out
        setActiveAgents(prev => prev.map(a =>
          a.type === e.agentId || a.id.includes(e.agentId)
            ? { ...a, status: 'timing_out' as ActiveAgentStatus }
            : a
        ));

        // After 3 seconds, transition to final timeout status
        // (agent should have stopped by then due to cancellation token check)
        setTimeout(() => {
          setActiveAgents(prev => prev.map(a =>
            (a.type === e.agentId || a.id.includes(e.agentId)) && a.status === 'timing_out'
              ? { ...a, status: 'timeout' as ActiveAgentStatus }
              : a
          ));
        }, 3000);
      } else {
        // Regular error - set immediately
        setActiveAgents(prev => prev.map(a =>
          a.type === e.agentId || a.id.includes(e.agentId)
            ? { ...a, status: 'error' as ActiveAgentStatus }
            : a
        ));
      }
      return;
    }
    if (event.type === 'agent.pending_plan') {
      const e = event as { agentId: string; changes: Array<{ tool: string }> };
      addMessage('system', `[AGENT] ${e.agentId} queued ${e.changes.length} change(s) to pending plan`);
      return;
    }

    // Tool events
    if (event.type === 'tool.start') {
      const e = event as { tool: string; args?: Record<string, unknown>; subagent?: string };
      const displayName = e.subagent ? `${e.subagent}:${e.tool}` : e.tool;
      setStatus(s => ({ ...s, mode: `calling ${displayName}` }));
      setToolCalls(prev => [...prev.slice(-4), {
        id: `${displayName}-${Date.now()}`,
        name: displayName,
        args: e.args || {},
        status: 'running',
        startTime: new Date(),
      }]);
      return;
    }
    if (event.type === 'tool.complete') {
      const e = event as { tool: string; result?: unknown; subagent?: string };
      const displayName = e.subagent ? `${e.subagent}:${e.tool}` : e.tool;
      const modeText = e.subagent ? `${e.subagent} thinking` : (mode === 'approving' ? 'executing plan' : 'thinking');
      setStatus(s => ({ ...s, mode: modeText }));
      setToolCalls(prev => prev.map(t => t.name === displayName ? {
        ...t,
        status: 'success' as const,
        result: e.result,
        duration: t.startTime ? Date.now() - t.startTime.getTime() : undefined,
      } : t));
      return;
    }
    if (event.type === 'tool.blocked') {
      const e = event as { tool: string; reason?: string; subagent?: string };
      const displayName = e.subagent ? `${e.subagent}:${e.tool}` : e.tool;
      setToolCalls(prev => prev.map(t => t.name === displayName ? {
        ...t,
        status: 'error' as const,
        error: e.reason || 'Blocked',
      } : t));
      return;
    }

    // LLM events
    if (event.type === 'llm.start') {
      const e = event as { subagent?: string };
      const modeText = e.subagent ? `${e.subagent} thinking` : (mode === 'approving' ? 'executing plan' : 'thinking');
      setStatus(s => ({ ...s, mode: modeText, iter: s.iter + 1 }));
      return;
    }
    if (event.type === 'llm.complete' && eventWithSubagent.subagent && showThinking) {
      const e = event as { response?: { thinking?: string; content?: string } };
      const thinking = e.response?.thinking;
      if (thinking) {
        const preview = thinking.length > 500 ? thinking.slice(0, 500) + '...' : thinking;
        addMessage('system', `[${eventWithSubagent.subagent}] ${preview}`);
      }
      return;
    }

    // Error events
    if (event.type === 'error') {
      const e = event as { error: string | { message?: string }; subagent?: string };
      const prefix = e.subagent ? `[${e.subagent} ERROR]` : '[ERROR]';
      const errorMsg = typeof e.error === 'string' ? e.error : e.error?.message || 'Unknown error';
      addMessage('error', `${prefix} ${errorMsg}`);
      return;
    }

    // Insight events - also track tokens for active agents
    if (event.type === 'insight.tokens') {
      const e = event as { inputTokens: number; outputTokens: number; cost?: number; subagent?: string };
      if (showThinking) {
        addMessage('system', `${subagentPrefix}* ${e.inputTokens.toLocaleString()} in, ${e.outputTokens.toLocaleString()} out${e.cost ? ` $${e.cost.toFixed(6)}` : ''}`);
      }
      // Update tokens for active agent if this event is from a subagent
      // IMPORTANT: Don't update tokens for agents that are timing_out/timeout/error
      // These agents should have stopped, and any lingering events are from
      // zombie processes that we don't want to count.
      if (e.subagent || eventWithSubagent.subagent) {
        const agentName = e.subagent || eventWithSubagent.subagent;
        setActiveAgents(prev => prev.map(a => {
          const matchesAgent = a.type === agentName || a.id.includes(agentName || '');
          const isStillRunning = a.status === 'running';
          // Only update tokens if agent is still running
          if (matchesAgent && isStillRunning) {
            return { ...a, tokens: a.tokens + (e.inputTokens || 0) + (e.outputTokens || 0) };
          }
          return a;
        }));
      }
      return;
    }

    // Resilience events
    if (event.type === 'resilience.retry') {
      const e = event as { reason: string; attempt: number; maxAttempts: number };
      addMessage('system', `[RETRY] ${e.reason} (${e.attempt}/${e.maxAttempts})`);
      return;
    }
    if (event.type === 'resilience.recovered') {
      const e = event as { reason: string; attempts: number };
      addMessage('system', `[RECOVERED] ${e.reason} after ${e.attempts} attempt(s)`);
      return;
    }

    // Subagent visibility events - also update Active Agents Panel
    if (event.type === 'subagent.iteration') {
      const e = event as { agentId: string; iteration: number; maxIterations: number };
      setStatus(s => ({ ...s, mode: `${e.agentId} iter ${e.iteration}/${e.maxIterations}` }));
      // Update active agents panel with iteration info
      setActiveAgents(prev => prev.map(a =>
        a.type === e.agentId || a.id.includes(e.agentId)
          ? { ...a, iteration: e.iteration, maxIterations: e.maxIterations }
          : a
      ));
      return;
    }
    if (event.type === 'subagent.phase') {
      const e = event as { agentId: string; phase: string };
      setStatus(s => ({ ...s, mode: `${e.agentId} ${e.phase}` }));
      // Update active agents panel with phase info
      setActiveAgents(prev => prev.map(a =>
        a.type === e.agentId || a.id.includes(e.agentId)
          ? { ...a, currentPhase: e.phase }
          : a
      ));
      return;
    }

    // Task events - update Tasks Panel
    if (event.type === 'task.created') {
      const e = event as unknown as { task: Task };
      setTasks(prev => [...prev, e.task]);
      addMessage('system', `[TASK] Created: ${e.task.subject}`);
      return;
    }
    if (event.type === 'task.updated') {
      const e = event as unknown as { task: Task };
      setTasks(prev => prev.map(t => t.id === e.task.id ? e.task : t));
      // Only log status changes
      addMessage('system', `[TASK] ${e.task.subject}: ${e.task.status}`);
      return;
    }

    // -------------------------------------------------------------------------
    // Processing-only events (normal message submission)
    // -------------------------------------------------------------------------
    if (mode === 'processing') {
      if (event.type === 'plan.change.queued') {
        const e = event as { tool: string; summary?: string; subagent?: string };
        const summary = e.summary ? `: ${e.summary}` : '';
        const prefix = e.subagent ? `[${e.subagent} PLAN]` : '[PLAN]';
        addMessage('system', `${prefix} Queued ${e.tool}${summary}`);
        return;
      }
      if (event.type === 'plan.change.complete') {
        const e = event as { changeIndex: number; tool: string; result: unknown; error?: string };
        if (e.error) {
          addMessage('system', `[PLAN ${e.changeIndex + 1}] ${e.tool} FAILED: ${e.error}`);
        } else if (e.tool === 'spawn_agent' && e.result) {
          const output = typeof e.result === 'object' && e.result !== null && 'output' in e.result
            ? String((e.result as { output: unknown }).output)
            : String(e.result);
          const preview = output.length > 800 ? output.slice(0, 800) + '\n... (truncated)' : output;
          addMessage('system', `[PLAN ${e.changeIndex + 1}] ${e.tool} result:\n${preview}`);
        } else {
          addMessage('system', `[PLAN ${e.changeIndex + 1}] ${e.tool} completed`);
        }
        return;
      }
      if (event.type === 'cache.hit' && showThinking) {
        const e = event as { query: string; similarity: number };
        addMessage('system', `[CACHE HIT] similarity: ${(e.similarity * 100).toFixed(0)}%`);
        return;
      }
      if (event.type === 'cache.miss' && showThinking) {
        addMessage('system', `[CACHE MISS]`);
        return;
      }
      if (event.type === 'compaction.auto') {
        const e = event as { tokensBefore: number; tokensAfter: number; messagesCompacted: number };
        const before = (e.tokensBefore / 1000).toFixed(1);
        const after = (e.tokensAfter / 1000).toFixed(1);
        addMessage('system', `[COMPACT] ${before}k -> ${after}k tokens (${e.messagesCompacted} messages)`);
        return;
      }
      if (event.type === 'compaction.warning' && showThinking) {
        const e = event as { currentTokens: number; threshold: number };
        const pct = Math.round((e.currentTokens / e.threshold) * 100);
        addMessage('system', `[!] Context at ${pct}% of threshold`);
        return;
      }
    }
  }, [addMessage, showThinking]);

  // Set up transparency aggregator and subscribe to agent events
  useEffect(() => {
    const aggregator = new TransparencyAggregator();
    transparencyAggregatorRef.current = aggregator;

    // Subscribe to state changes
    const unsubscribeAggregator = aggregator.subscribe((state) => {
      setTransparencyState(state);
    });

    // Subscribe to agent events
    const unsubscribeAgent = agent.subscribe((event: AgentEvent) => {
      aggregator.processEvent(event);
      handleAgentEvent(event); // Unified event handler for TUI display
    });

    return () => {
      unsubscribeAggregator();
      unsubscribeAgent();
    };
  }, [agent, handleAgentEvent]);

  // =========================================================================
  // COMMAND HANDLER
  // =========================================================================

  const handleCommand = useCallback(async (cmd: string, args: string[]) => {
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
        addMessage('system', [
          `Session Status:`,
          `  Status: ${agentState.status} | Iteration: ${agentState.iteration}`,
          `  Messages: ${agentState.messages.length}`,
          `  Tokens: ${metrics.totalTokens.toLocaleString()} (${metrics.inputTokens} in / ${metrics.outputTokens} out)`,
          `  LLM Calls: ${metrics.llmCalls} | Tool Calls: ${metrics.toolCalls}`,
          `  Cost: $${metrics.estimatedCost.toFixed(4)}`,
        ].join('\n'));
        return;
      }

      case 'help':
      case 'h':
        addMessage('system', [
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
          '========================',
        ].join('\n'));
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

      case 'tasks': {
        // Filter out deleted tasks
        const visibleTasks = tasks.filter(t => t.status !== 'deleted');
        if (visibleTasks.length === 0) {
          addMessage('system', 'No tasks. Tasks are created when the agent uses task_create tool.');
          return;
        }
        // Count by status
        const pending = visibleTasks.filter(t => t.status === 'pending').length;
        const inProgress = visibleTasks.filter(t => t.status === 'in_progress').length;
        const completed = visibleTasks.filter(t => t.status === 'completed').length;
        // Format task list
        const taskLines = visibleTasks.map(t => {
          const isBlocked = t.blockedBy.some(id => {
            const blocker = visibleTasks.find(bt => bt.id === id);
            return blocker && blocker.status !== 'completed';
          });
          const icon = isBlocked ? '◌' : t.status === 'completed' ? '✓' : t.status === 'in_progress' ? '●' : '○';
          const blockedInfo = isBlocked ? ` (blocked by: ${t.blockedBy.slice(0, 2).join(', ')})` : '';
          const activeInfo = t.status === 'in_progress' && t.activeForm ? `\n     └ ${t.activeForm}...` : '';
          return `  ${icon} ${t.id}  ${t.subject}${blockedInfo}${activeInfo}`;
        });
        addMessage('system', [
          `TASKS [${pending} pending, ${inProgress} in_progress, ${completed} completed]`,
          '',
          ...taskLines,
          '',
          'Toggle panel: Alt+K',
        ].join('\n'));
        return;
      }

      case 'context':
      case 'ctx': {
        const agentState = agent.getState();
        const mcpStats = mcpClient.getContextStats();
        const estimateTokens = (str: string) => Math.ceil(str.length / 3.2);
        const systemPrompt = agent.getSystemPromptWithMode ? agent.getSystemPromptWithMode() : '';
        const systemTokens = estimateTokens(systemPrompt);
        const mcpTokens = mcpStats.summaryTokens + mcpStats.definitionTokens;
        const agentTools = agent.getTools().filter((t: any) => !t.name.startsWith('mcp_'));
        const agentToolTokens = agentTools.length * 150;
        const convTokens = agentState.messages
          .filter((m: any) => m.role !== 'system')
          .reduce((sum: number, m: any) => sum + estimateTokens(typeof m.content === 'string' ? m.content : JSON.stringify(m.content)), 0);
        const totalTokens = systemTokens + mcpTokens + agentToolTokens + convTokens;
        const contextLimit = agent.getMaxContextTokens();
        const percent = Math.round((totalTokens / contextLimit) * 100);
        const bar = '='.repeat(Math.min(20, Math.round(percent / 5))) + '-'.repeat(Math.max(0, 20 - Math.round(percent / 5)));

        addMessage('system', [
          `Context (~${totalTokens.toLocaleString()} / ${(contextLimit / 1000)}k)`,
          `  [${bar}] ${percent}%`,
          `  System: ~${systemTokens.toLocaleString()}`,
          `  Tools:  ~${agentToolTokens.toLocaleString()} (${agentTools.length})`,
          `  MCP:    ~${mcpTokens.toLocaleString()} (${mcpStats.loadedCount}/${mcpStats.totalTools})`,
          `  Conv:   ~${convTokens.toLocaleString()} (${agentState.messages.length} msgs)`,
          percent >= 80 ? '  ! Consider /compact' : '  OK',
        ].join('\n'));
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
          setStatus(s => ({ ...s, mode: 'compacting' }));
          const result = await compactor.compact(agentState.messages);
          agent.loadMessages(result.preservedMessages);
          addMessage('system', `Compacted: ${result.compactedCount + result.preservedMessages.length} -> ${result.preservedMessages.length} msgs`);
        } catch (e) {
          addMessage('error', (e as Error).message);
        }
        setIsProcessing(false);
        setStatus(s => ({ ...s, mode: 'ready' }));
        return;

      case 'mcp': {
        if (args[0] === 'tools') {
          const tools = mcpClient.getAllTools();
          if (tools.length === 0) {
            addMessage('system', 'No MCP tools available.');
          } else {
            const stats = mcpClient.getContextStats();
            addMessage('system', `MCP Tools (${stats.loadedCount}/${stats.totalTools}):\n${tools.slice(0, 15).map((t: any) => `  ${mcpClient.isToolLoaded(t.name) ? '[Y]' : '[ ]'} ${t.name}`).join('\n')}`);
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
          addMessage('system', [
            `MCP Servers:`,
            ...servers.map((s: any) => `  ${s.status === 'connected' ? '[OK]' : '[ ]'} ${s.name} - ${s.toolCount || 0} tools`),
            `Loaded: ${stats.loadedCount}/${stats.totalTools}`,
          ].join('\n'));
        }
        return;
      }

      case 'tools': {
        const allTools = agent.getTools();
        const builtIn = allTools.filter((t: any) => !t.name.startsWith('mcp_'));
        const mcpTools = allTools.filter((t: any) => t.name.startsWith('mcp_'));
        addMessage('system', [
          `Tools (${allTools.length}):`,
          `Built-in (${builtIn.length}):`,
          ...builtIn.slice(0, 10).map((t: any) => `  * ${t.name}`),
          builtIn.length > 10 ? `  ... +${builtIn.length - 10}` : '',
          `MCP (${mcpTools.length}):`,
          ...(mcpTools.length > 0 ? mcpTools.slice(0, 5).map((t: any) => `  * ${t.name}`) : ['  (none)']),
        ].filter(Boolean).join('\n'));
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
            addMessage('system', `Checkpoints:\n${cps.map((cp: any) => `  ${cp.id}${cp.label ? ` - ${cp.label}` : ''}`).join('\n')}`);
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
          setMessages(msgs.map((m: any, i: number) => ({
            id: `msg-${i}`,
            role: m.role,
            content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
            ts: new Date(),
          })));
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
          setMessages(msgs.map((m: any, i: number) => ({
            id: `msg-${i}`,
            role: m.role,
            content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
            ts: new Date(),
          })));
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
            addMessage('system', 'Threads:\n' + threads.map((t: any) =>
              `  ${t.id}${t.name ? ` - ${t.name}` : ''} (${t.messages?.length || 0} msgs)`
            ).join('\n'));
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
            setMessages(msgs.map((m: any, i: number) => ({
              id: `msg-${i}`,
              role: m.role,
              content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
              ts: new Date(),
            })));
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
          addMessage('system', [
            `Mode: ${modeInfo.icon} ${modeInfo.name}`,
            hasPlan ? `  Pending: ${agent.getPendingChangeCount()} changes` : '',
            agent.getAvailableModes(),
          ].filter(Boolean).join('\n'));
        } else {
          agent.setMode(args[0].toLowerCase());
          const modeInfo = agent.getModeInfo();
          setStatus(s => ({ ...s, mode: modeInfo.name === 'Plan' ? 'ready (plan)' : 'ready' }));
          addMessage('system', `Mode: ${modeInfo.icon} ${modeInfo.name}`);
        }
        return;
      }

      case 'plan': {
        agent.togglePlanMode();
        const modeInfo = agent.getModeInfo();
        setStatus(s => ({ ...s, mode: modeInfo.name === 'Plan' ? 'ready (plan)' : 'ready' }));
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
        setStatus(s => ({ ...s, mode: 'executing plan' }));

        try {
          const count = args[0] ? parseInt(args[0], 10) : undefined;
          const result = await agent.approvePlan(count);

          if (result.success) {
            addMessage('system', `[OK] Executed ${result.executed} change(s)`);
          } else {
            addMessage('system', `[!] ${result.executed} done, ${result.errors.length} errors:\n${result.errors.join('\n')}`);
          }
        } catch (e) {
          addMessage('error', `Plan execution failed: ${(e as Error).message}`);
        } finally {
          executionModeRef.current = 'idle';
          setExecutionMode('idle');
          setIsProcessing(false);
          setToolCalls([]);
          if (agent.getMode() === 'plan') {
            agent.setMode('build');
          }
          setStatus(s => ({ ...s, mode: 'ready' }));
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
          setStatus(s => ({ ...s, mode: 'ready' }));
        }
        return;

      case 'theme': {
        const availableThemes = getThemeNames();
        if (!args[0]) {
          addMessage('system', `Theme: ${currentThemeName}\nAvailable: ${availableThemes.join(', ')}`);
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
        addMessage('system', servers.length > 0
          ? `LSP Active:\n${servers.map((s: string) => `  [OK] ${s}`).join('\n')}`
          : 'No LSP servers running');
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
        setStatus(s => ({ ...s, mode: 'spawning' }));
        try {
          const [agentName, ...taskParts] = args;
          const task = taskParts.join(' ');
          const result = await agent.spawnAgent(agentName, task);
          addMessage('assistant', `Agent ${agentName}: ${result.success ? 'OK' : 'Failed'}\n${result.output}`);
        } catch (e) {
          addMessage('error', (e as Error).message);
        }
        setIsProcessing(false);
        setStatus(s => ({ ...s, mode: 'ready' }));
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
            const sortedSubagents = hierarchy.subagents.sort((a, b) =>
              (a.spawnedAtIteration || 0) - (b.spawnedAtIteration || 0)
            );

            for (const sub of sortedSubagents) {
              const durationSec = Math.round(sub.duration / 1000);
              lines.push(`  └─ ${sub.agentId} (spawned iter ${sub.spawnedAtIteration || '?'})`);
              lines.push(`     ├─ ${sub.inputTokens.toLocaleString()} in / ${sub.outputTokens.toLocaleString()} out tokens`);
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
            addMessage('system', [
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
            ].join('\n'));
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

            const lines = ['Efficiency Analysis:', '', `Anomalies Detected: ${summary.anomalies.length}`];

            if (summary.anomalies.length === 0) {
              lines.push('  No significant issues detected.');
            } else {
              for (const anomaly of summary.anomalies) {
                lines.push(`  [${anomaly.severity.toUpperCase()}] ${anomaly.type}`);
                lines.push(`       ${anomaly.description}`);
              }
            }

            lines.push('', 'Tool Patterns:');
            lines.push(`  Unique tools used: ${Object.keys(summary.toolPatterns.frequency).length}`);
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
                const icon = anomaly.severity === 'high' ? '!' : anomaly.severity === 'medium' ? '*' : '-';
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
          addMessage('system', [
            'Usage:',
            '  /trace              - Show current session trace summary',
            '  /trace --analyze    - Run efficiency analysis',
            '  /trace issues       - List detected inefficiencies',
            '  /trace fixes        - List pending improvements',
          ].join('\n'));
        }
        return;
      }

      default:
        addMessage('system', `Unknown: /${cmd}. Try /help`);
    }
  }, [addMessage, exit, agent, mcpClient, lspManager, sessionStore, compactor, model, currentThemeName, currentSessionId, formatSessionsTable, saveCheckpointToStore, showThinking]);

  // =========================================================================
  // SUBMIT HANDLER
  // =========================================================================

  const handleSubmit = useCallback(async (input: string) => {
    const trimmed = input.trim();
    if (!trimmed) return;

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
    setStatus(s => ({ ...s, mode: 'thinking' }));

    try {
      const result = await agent.run(trimmed);
      const metrics = agent.getMetrics();
      const modeInfo = agent.getModeInfo();
      setStatus({ iter: metrics.llmCalls, tokens: metrics.totalTokens, cost: metrics.estimatedCost, mode: modeInfo.name === 'Plan' ? 'ready (plan)' : 'ready' });

      // Calculate current context size (what's actually in the window now)
      const agentState = agent.getState();
      const estimateTokens = (str: string) => Math.ceil(str.length / 3.2);
      const currentContextTokens = agentState.messages.reduce((sum: number, m: any) =>
        sum + estimateTokens(typeof m.content === 'string' ? m.content : JSON.stringify(m.content)), 0);
      const contextLimit = agent.getMaxContextTokens();
      const contextPct = Math.round((currentContextTokens / contextLimit) * 100);

      const durationSec = (metrics.duration / 1000).toFixed(1);
      // Format: Session total (cumulative cost) | Current context (compaction awareness)
      const sessionIn = metrics.inputTokens >= 1000 ? `${(metrics.inputTokens / 1000).toFixed(1)}k` : metrics.inputTokens.toLocaleString();
      const sessionOut = metrics.outputTokens >= 1000 ? `${(metrics.outputTokens / 1000).toFixed(1)}k` : metrics.outputTokens.toLocaleString();
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
        addMessage('assistant', (result.response || result.error || 'No response') + metricsLine);
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
        } catch (e) {
          persistenceDebug.error('[TUI] Checkpoint failed', e);
        }
      }
    } catch (e) {
      addMessage('error', (e as Error).message);
    } finally {
      executionModeRef.current = 'idle';
      setExecutionMode('idle');
      setIsProcessing(false);
      setToolCalls([]);
    }
  }, [addMessage, handleCommand, agent, sessionStore, saveCheckpointToStore, persistenceDebug]);

  // =========================================================================
  // COMMAND PALETTE ITEMS
  // =========================================================================

  const commandPaletteItems: CommandPaletteItem[] = useMemo(() => [
    { id: 'help', label: 'Help', shortcut: '/help', category: 'General', action: () => handleCommand('help', []) },
    { id: 'status', label: 'Show Status', shortcut: '/status', category: 'General', action: () => handleCommand('status', []) },
    { id: 'clear', label: 'Clear Screen', shortcut: 'Ctrl+L', category: 'General', action: () => { setMessages([]); setToolCalls([]); } },
    { id: 'save', label: 'Save Session', shortcut: '/save', category: 'Sessions', action: () => handleCommand('save', []) },
    { id: 'sessions', label: 'List Sessions', shortcut: '/sessions', category: 'Sessions', action: () => handleCommand('sessions', []) },
    { id: 'context', label: 'Context Info', shortcut: '/context', category: 'Context', action: () => handleCommand('context', []) },
    { id: 'compact', label: 'Compact Context', shortcut: '/compact', category: 'Context', action: () => handleCommand('compact', []) },
    { id: 'mcp', label: 'MCP Servers', shortcut: '/mcp', category: 'MCP', action: () => handleCommand('mcp', []) },
    { id: 'mcp-tools', label: 'MCP Tools', shortcut: '/mcp tools', category: 'MCP', action: () => handleCommand('mcp', ['tools']) },
    { id: 'plan', label: 'Toggle Plan Mode', shortcut: '/plan', category: 'Plan', action: () => handleCommand('plan', []) },
    { id: 'show-plan', label: 'Show Plan', shortcut: '/show-plan', category: 'Plan', action: () => handleCommand('show-plan', []) },
    { id: 'approve', label: 'Approve Plan', shortcut: '/approve', category: 'Plan', action: () => handleCommand('approve', []) },
    { id: 'reject', label: 'Reject Plan', shortcut: '/reject', category: 'Plan', action: () => handleCommand('reject', []) },
    { id: 'tools', label: 'List Tools', shortcut: '/tools', category: 'Debug', action: () => handleCommand('tools', []) },
    { id: 'theme', label: 'Change Theme', shortcut: '/theme', category: 'Settings', action: () => handleCommand('theme', []) },
    { id: 'exit', label: 'Exit', shortcut: 'Ctrl+C', category: 'General', action: () => agent.cleanup().then(() => exit()) },
  ], [handleCommand, agent, exit]);

  // Get filtered command palette items for current query
  const filteredCommandItems = useMemo(() => {
    if (!commandPaletteQuery) return commandPaletteItems;
    const q = commandPaletteQuery.toLowerCase();
    return commandPaletteItems.filter(item =>
      item.label.toLowerCase().includes(q) ||
      item.id.toLowerCase().includes(q) ||
      (item.shortcut && item.shortcut.toLowerCase().includes(q))
    );
  }, [commandPaletteItems, commandPaletteQuery]);

  // Handle command palette keyboard input (called from MemoizedInputArea)
  const handleCommandPaletteInput = useCallback((input: string, key: any) => {
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
      setCommandPaletteIndex(i => Math.max(0, i - 1));
      return;
    }
    if (key.downArrow) {
      setCommandPaletteIndex(i => Math.min(filteredCommandItems.length - 1, i + 1));
      return;
    }

    // Backspace
    if (key.backspace || key.delete) {
      setCommandPaletteQuery(q => q.slice(0, -1));
      setCommandPaletteIndex(0);
      return;
    }

    // Regular character input
    if (input && !key.ctrl && !key.meta) {
      setCommandPaletteQuery(q => q + input);
      setCommandPaletteIndex(0);
    }
  }, [filteredCommandItems, commandPaletteIndex]);

  // Handle approval deny reason input (called from MemoizedInputArea)
  const handleApprovalDenyReasonInput = useCallback((input: string, key: any) => {
    // Enter submits the deny reason
    if (key.return) {
      handleDeny(denyReason || 'User denied');
      return;
    }

    // Backspace
    if (key.backspace || key.delete) {
      setDenyReason(r => r.slice(0, -1));
      return;
    }

    // Regular character input
    if (input && !key.ctrl && !key.meta) {
      setDenyReason(r => r + input);
    }
  }, [denyReason, handleDeny]);

  // =========================================================================
  // KEYBOARD CALLBACKS
  // =========================================================================

  const handleCtrlC = useCallback(() => {
    agent.cleanup().then(() => mcpClient.cleanup()).then(() => lspManager.cleanup()).then(() => exit());
  }, [agent, mcpClient, lspManager, exit]);

  const handleCtrlL = useCallback(() => {
    setMessages([]);
    setToolCalls([]);
  }, []);

  const handleCtrlP = useCallback(() => {
    setCommandPaletteOpen(prev => !prev);
    setCommandPaletteQuery('');
    setCommandPaletteIndex(0);
  }, []);

  const handleEscape = useCallback(() => {
    // Close command palette first if open
    if (commandPaletteOpen) {
      setCommandPaletteOpen(false);
      setCommandPaletteQuery('');
      setCommandPaletteIndex(0);
      return;
    }
    // Otherwise cancel processing
    if (isProcessingRef.current) {
      agent.cancel('Cancelled by ESC');
      setIsProcessing(false);
      addMessage('system', '[STOP] Cancelled');
    }
  }, [agent, addMessage, commandPaletteOpen]);

  const handleToggleToolExpand = useCallback(() => {
    setToolCallsExpanded(prev => {
      addMessage('system', !prev ? '[*] Tool details: expanded' : '[ ] Tool details: collapsed');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleThinking = useCallback(() => {
    setShowThinking(prev => {
      addMessage('system', !prev ? '[*] Thinking: verbose' : '[ ] Thinking: minimal');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleTransparency = useCallback(() => {
    setTransparencyExpanded(prev => {
      addMessage('system', !prev ? '[v] Transparency panel: visible' : '[^] Transparency panel: hidden');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleActiveAgents = useCallback(() => {
    setActiveAgentsExpanded(prev => {
      addMessage('system', !prev ? '[v] Active agents: visible' : '[^] Active agents: hidden');
      return !prev;
    });
  }, [addMessage]);

  const handleToggleTasks = useCallback(() => {
    setTasksExpanded(prev => {
      addMessage('system', !prev ? '[v] Tasks: visible' : '[^] Tasks: hidden');
      return !prev;
    });
  }, [addMessage]);

  // Update context tokens
  useEffect(() => {
    const agentState = agent.getState();
    const estimateTokens = (str: string) => Math.ceil(str.length / 3.2);
    const tokens = agentState.messages.reduce((sum: number, m: any) =>
      sum + estimateTokens(typeof m.content === 'string' ? m.content : JSON.stringify(m.content)), 0);
    setContextTokens(tokens);
  }, [status.tokens, messages.length, agent]);

  // Track elapsed time
  useEffect(() => {
    if (isProcessing) {
      processingStartRef.current = Date.now();
      setElapsedTime(0);
      const interval = setInterval(() => {
        if (processingStartRef.current) {
          setElapsedTime(Math.floor((Date.now() - processingStartRef.current) / 1000));
        }
      }, 1000);
      return () => clearInterval(interval);
    } else {
      processingStartRef.current = null;
      return undefined;
    }
  }, [isProcessing]);

  const modelShort = (model || 'unknown').split('/').pop() || model || 'unknown';
  const contextPct = Math.round((contextTokens / agent.getMaxContextTokens()) * 100);
  const costStr = status.cost > 0 ? `$${status.cost.toFixed(4)}` : '$0.00';

  // =========================================================================
  // RENDER
  // =========================================================================

  return (
    <>
      {/* Static messages - rendered once, never re-render */}
      <Static items={messages}>
        {(m: TUIMessage) => (
          <MessageItem key={m.id} msg={m} colors={colors} />
        )}
      </Static>

      {/* Dynamic section */}
      <Box flexDirection="column">
        {toolCalls.length > 0 && (
          <Box flexDirection="column" marginBottom={1}>
            <Text color="#DDA0DD" bold>{`Tools ${toolCallsExpanded ? '[-]' : '[+]'}`}</Text>
            {toolCalls.slice(-5).map(tc => (
              <ToolCallItem key={`${tc.id}-${tc.status}`} tc={tc} expanded={toolCallsExpanded} colors={colors} />
            ))}
          </Box>
        )}

        {/* Transparency Panel (toggle with Alt+I) */}
        {transparencyExpanded && transparencyState && (
          <Box flexDirection="column" marginBottom={1} borderStyle="single" borderColor={colors.border} paddingX={1}>
            <Text color={colors.accent} bold>[v] Transparency Panel</Text>
            <Box marginLeft={2} flexDirection="column">
              <Text color={colors.text}>REASONING</Text>
              {transparencyState.lastRouting ? (
                <>
                  <Text color={colors.textMuted}>  Routing: {transparencyState.lastRouting.model}</Text>
                  <Text color={colors.textMuted}>    {transparencyState.lastRouting.reason}</Text>
                </>
              ) : (
                <Text color={colors.textMuted}>  Routing: (no routing decisions yet)</Text>
              )}
              {transparencyState.lastPolicy && (
                <Text color={transparencyState.lastPolicy.decision === 'blocked' ? colors.error :
                             transparencyState.lastPolicy.decision === 'prompted' ? colors.warning : colors.success}>
                  Policy: {transparencyState.lastPolicy.decision === 'allowed' ? '+' :
                           transparencyState.lastPolicy.decision === 'blocked' ? 'x' : '?'} {transparencyState.lastPolicy.tool}
                </Text>
              )}
            </Box>
            <Box marginLeft={2} marginTop={1} flexDirection="column">
              <Text color={colors.text}>CONTEXT</Text>
              {transparencyState.contextHealth ? (
                <>
                  <Text color={colors.textMuted}>
                    {'  [' + '='.repeat(Math.round((transparencyState.contextHealth.percentUsed / 100) * 20)) +
                     '-'.repeat(20 - Math.round((transparencyState.contextHealth.percentUsed / 100) * 20)) +
                     '] ' + transparencyState.contextHealth.percentUsed + '%'}
                  </Text>
                  <Text color={colors.textMuted}>
                    {'  ' + (transparencyState.contextHealth.currentTokens / 1000).toFixed(1) + 'k / ' +
                     (transparencyState.contextHealth.maxTokens / 1000).toFixed(0) + 'k tokens'}
                  </Text>
                  <Text color={colors.textMuted}>
                    {'  ~' + transparencyState.contextHealth.estimatedExchanges + ' exchanges remaining'}
                  </Text>
                </>
              ) : (
                <Text color={colors.textMuted}>  (no context data yet)</Text>
              )}
            </Box>
            {transparencyState.activeLearnings.length > 0 && (
              <Box marginLeft={2} marginTop={1} flexDirection="column">
                <Text color={colors.text}>MEMORY</Text>
                <Text color={colors.textMuted}>  Learnings applied: {transparencyState.activeLearnings.length}</Text>
              </Box>
            )}
          </Box>
        )}

        {/* Approval Dialog (positioned above input when active) */}
        {pendingApproval && (
          <ApprovalDialog
            visible={true}
            request={{
              id: pendingApproval.id,
              tool: pendingApproval.tool || pendingApproval.action,
              args: pendingApproval.args || {},
              risk: pendingApproval.risk,
              context: pendingApproval.context,
            }}
            onApprove={handleApprove}
            onDeny={handleDeny}
            colors={colors}
            denyReasonMode={denyReasonMode}
            denyReason={denyReason}
          />
        )}

        {/* Tasks Panel (positioned above input for task tracking) */}
        <TasksPanel
          tasks={tasks}
          colors={colors}
          expanded={tasksExpanded}
        />

        {/* Active Agents Panel (positioned above input when agents are running) */}
        <ActiveAgentsPanel
          agents={activeAgents}
          colors={colors}
          expanded={activeAgentsExpanded}
        />

        <MemoizedInputArea
          onSubmit={handleSubmit}
          disabled={isProcessing || !!pendingApproval}
          borderColor={pendingApproval ? '#FFD700' : '#87CEEB'}
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

        {/* Status bar */}
        <Box
          borderStyle="single"
          borderColor={isProcessing ? colors.info : colors.textMuted}
          paddingX={1}
          justifyContent="space-between"
        >
          <Box gap={1}>
            <Text color={isProcessing ? colors.info : '#98FB98'} bold={isProcessing}>
              {isProcessing ? '[~]' : '[*]'}
            </Text>
            <Text color={isProcessing ? colors.info : colors.text} bold={isProcessing}>
              {status.mode.length > 40 ? status.mode.slice(0, 37) + '...' : status.mode}
            </Text>
            {isProcessing && elapsedTime > 0 && <Text color={colors.textMuted} dimColor>| {elapsedTime}s</Text>}
            {status.iter > 0 && <Text color={colors.textMuted} dimColor>| iter {status.iter}</Text>}
          </Box>
          <Box gap={2}>
            <Text color="#DDA0DD" dimColor>{modelShort}</Text>
            {/* Mini context bar: [====----] 42% */}
            <Text color={contextPct > 70 ? '#FFD700' : colors.textMuted} dimColor>
              {'[' + '='.repeat(Math.min(8, Math.round((contextPct / 100) * 8))) +
               '-'.repeat(Math.max(0, 8 - Math.round((contextPct / 100) * 8))) + '] ' +
               contextPct + '%'}
            </Text>
            <Text color="#98FB98" dimColor>{costStr}</Text>
            {gitBranch && <Text color="#87CEEB" dimColor>{gitBranch}</Text>}
            {/* Show learnings count if any */}
            {transparencyState?.activeLearnings && transparencyState.activeLearnings.length > 0 && (
              <Text color="#87CEEB" dimColor>L:{transparencyState.activeLearnings.length}</Text>
            )}
            <Text color={colors.textMuted} dimColor>^P:help</Text>
          </Box>
        </Box>
      </Box>
    </>
  );
}

export default TUIApp;
