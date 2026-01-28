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
import type { ProductionAgent } from '../agent.js';
import type { SQLiteStore } from '../integrations/sqlite-store.js';
import type { MCPClient } from '../integrations/mcp-client.js';
import type { Compactor } from '../integrations/compaction.js';
import type { ThemeColors, CommandPaletteItem } from './types.js';
import { getTheme, getThemeNames } from './theme/index.js';
import { ControlledCommandPalette } from './input/CommandPalette.js';
import { ApprovalDialog } from './components/ApprovalDialog.js';
import type { TUIApprovalBridge } from '../adapters.js';
import type { ApprovalRequest as TypesApprovalRequest } from '../types.js';

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
          <Box marginLeft={3}>
            <Text color="#98FB98" dimColor>
              {`-> ${String(tc.result).slice(0, 150)}${String(tc.result).length > 150 ? '...' : ''}`}
            </Text>
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

  return (
    <Box marginLeft={2} gap={1}>
      <Text color={statusColor}>{icon}</Text>
      <Text color="#DDA0DD" bold>{tc.name}</Text>
      {argsStr ? <Text color={colors.textMuted} dimColor>{argsStr}</Text> : null}
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
    onToggleToolExpand, onToggleThinking,
    onPageUp, onPageDown, onHome, onEnd,
    commandPaletteOpen, onCommandPaletteInput,
    approvalDialogOpen, approvalDenyReasonMode,
    onApprovalApprove, onApprovalAlwaysAllow, onApprovalDeny, onApprovalDenyWithReason,
    onApprovalCancelDenyReason, onApprovalDenyReasonInput,
  });
  callbacksRef.current = {
    onSubmit, onCtrlC, onCtrlL, onCtrlP, onEscape,
    onToggleToolExpand, onToggleThinking,
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

  // Display toggles
  const [toolCallsExpanded, setToolCallsExpanded] = useState(false);
  const [showThinking, setShowThinking] = useState(true);

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
          '> SESSIONS',
          '  /save             Save session',
          '  /sessions         List sessions',
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
          '> SUBAGENTS',
          '  /agents           List available agents',
          '  /spawn <a> <task> Run agent with task',
          '',
          '> PLAN MODE',
          '  /mode             Show current mode',
          '  /plan             Toggle plan mode',
          '  /show-plan        Display pending plan',
          '  /approve [n]      Approve plan',
          '  /reject           Reject plan',
          '',
          '===== SHORTCUTS =====',
          '  Ctrl+C      Exit',
          '  Ctrl+L      Clear screen',
          '  Ctrl+P      Help',
          '  Alt+T       Toggle tool details',
          '  Alt+O       Toggle thinking',
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
        const contextLimit = 80000;
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
        const count = args[0] ? parseInt(args[0], 10) : undefined;
        const result = await agent.approvePlan(count);
        if (result.success) {
          addMessage('system', `[OK] Executed ${result.executed} change(s)`);
        } else {
          addMessage('system', `[!] ${result.executed} done, ${result.errors.length} errors`);
        }
        if (agent.getMode() === 'plan') {
          agent.setMode('build');
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

      // Subagent commands
      case 'agents':
        try {
          const agentList = agent.formatAgentList();
          addMessage('system', `Available Agents:\n${agentList}`);
        } catch (e) {
          addMessage('error', (e as Error).message);
        }
        return;

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

      default:
        addMessage('system', `Unknown: /${cmd}. Try /help`);
    }
  }, [addMessage, exit, agent, mcpClient, lspManager, sessionStore, compactor, model, currentThemeName, currentSessionId, formatSessionsTable, saveCheckpointToStore]);

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

    setIsProcessing(true);
    setStatus(s => ({ ...s, mode: 'thinking' }));

    const unsub = agent.subscribe((event: any) => {
      // Check if event is from a subagent
      const subagentPrefix = event.subagent ? `[${event.subagent}] ` : '';

      if (event.type === 'agent.spawn') {
        // A subagent is starting
        addMessage('system', `[AGENT] Spawning ${event.name}: ${event.task.slice(0, 100)}${event.task.length > 100 ? '...' : ''}`);
      } else if (event.type === 'agent.complete') {
        // A subagent finished
        addMessage('system', `[AGENT] ${event.agentId} ${event.success ? 'completed' : 'failed'}`);
      } else if (event.type === 'tool.start') {
        const displayName = event.subagent ? `${event.subagent}:${event.tool}` : event.tool;
        setStatus(s => ({ ...s, mode: `calling ${displayName}` }));
        setToolCalls(prev => [...prev.slice(-4), {
          id: `${displayName}-${Date.now()}`,
          name: displayName,
          args: event.args || {},
          status: 'running',
          startTime: new Date(),
        }]);
      } else if (event.type === 'tool.complete') {
        const displayName = event.subagent ? `${event.subagent}:${event.tool}` : event.tool;
        setStatus(s => ({ ...s, mode: event.subagent ? `${event.subagent} thinking` : 'thinking' }));
        setToolCalls(prev => prev.map(t => t.name === displayName ? {
          ...t,
          status: 'success',
          result: event.result,
          duration: t.startTime ? Date.now() - t.startTime.getTime() : undefined,
        } : t));
      } else if (event.type === 'tool.blocked') {
        const displayName = event.subagent ? `${event.subagent}:${event.tool}` : event.tool;
        setToolCalls(prev => prev.map(t => t.name === displayName ? {
          ...t,
          status: 'error',
          error: event.reason || 'Blocked',
        } : t));
      } else if (event.type === 'llm.start') {
        setStatus(s => ({ ...s, mode: event.subagent ? `${event.subagent} thinking` : 'thinking', iter: s.iter + 1 }));
      } else if (event.type === 'insight.tokens' && showThinking) {
        const e = event as { inputTokens: number; outputTokens: number; cost?: number; subagent?: string };
        addMessage('system', `${subagentPrefix}* ${e.inputTokens.toLocaleString()} in, ${e.outputTokens.toLocaleString()} out${e.cost ? ` $${e.cost.toFixed(6)}` : ''}`);
      } else if (event.type === 'plan.change.queued') {
        addMessage('system', `[PLAN] Queued: ${event.tool}`);
      }
    });

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
      const contextLimit = 80000;
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
      unsub();
      setIsProcessing(false);
      setToolCalls([]);
    }
  }, [addMessage, handleCommand, agent, sessionStore, saveCheckpointToStore, persistenceDebug, showThinking]);

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
  const contextPct = Math.round((contextTokens / 80000) * 100);
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
            <Text color={contextPct > 70 ? '#FFD700' : colors.textMuted} dimColor>{`${(contextTokens / 1000).toFixed(1)}k`}</Text>
            <Text color="#98FB98" dimColor>{costStr}</Text>
            {gitBranch && <Text color="#87CEEB" dimColor>{gitBranch}</Text>}
            <Text color={colors.textMuted} dimColor>ESC:cancel ^P:help</Text>
          </Box>
        </Box>
      </Box>
    </>
  );
}

export default TUIApp;
