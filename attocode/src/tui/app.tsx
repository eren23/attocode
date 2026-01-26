/**
 * Root Ink Application
 *
 * Main TUI application using Ink (React for CLI).
 * This file orchestrates all TUI components and state management.
 */

import React, { useState, useEffect, useCallback, createContext, useContext, memo } from 'react';
import { Box, Text, useApp, useInput } from 'ink';
import type {
  TUIConfig,
  TUIState,
  TUIEventHandlers,
  MessageDisplay,
  ToolCallDisplay,
  StatusDisplay,
  DialogConfig,
  ThemeName,
} from './types.js';
import { getTheme, type Theme } from './theme/index.js';

// =============================================================================
// THEME CONTEXT
// =============================================================================

interface ThemeContextValue {
  theme: Theme;
  setTheme: (name: ThemeName) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: getTheme('dark'),
  setTheme: () => {},
});

export const useTheme = () => useContext(ThemeContext);

// =============================================================================
// APP STATE CONTEXT
// =============================================================================

interface AppStateContextValue {
  state: TUIState;
  dispatch: (action: AppAction) => void;
}

type AppAction =
  | { type: 'ADD_MESSAGE'; message: MessageDisplay }
  | { type: 'UPDATE_MESSAGE'; id: string; content: string }
  | { type: 'SET_TOOL_CALL'; toolCall: ToolCallDisplay }
  | { type: 'UPDATE_TOOL_CALL'; id: string; updates: Partial<ToolCallDisplay> }
  | { type: 'SET_STATUS'; status: StatusDisplay | null }
  | { type: 'SET_THINKING'; content: string }
  | { type: 'SET_SPINNER'; visible: boolean; message?: string }
  | { type: 'SET_DIALOG'; dialog: DialogConfig | null }
  | { type: 'TOGGLE_COMMAND_PALETTE' }
  | { type: 'SET_COMMAND_QUERY'; query: string }
  | { type: 'CLEAR_MESSAGES' }
  | { type: 'SET_FOCUS'; target: TUIState['focused'] }
  | { type: 'TOGGLE_ALL_TOOL_CALLS' }
  | { type: 'TOGGLE_THINKING_DISPLAY' };

function appReducer(state: TUIState, action: AppAction): TUIState {
  switch (action.type) {
    case 'ADD_MESSAGE':
      return { ...state, messages: [...state.messages, action.message] };
    case 'UPDATE_MESSAGE': {
      const messages = state.messages.map(m =>
        m.id === action.id ? { ...m, content: action.content } : m
      );
      return { ...state, messages };
    }
    case 'SET_TOOL_CALL': {
      const toolCalls = new Map(state.toolCalls);
      toolCalls.set(action.toolCall.id, action.toolCall);
      return { ...state, toolCalls };
    }
    case 'UPDATE_TOOL_CALL': {
      const toolCalls = new Map(state.toolCalls);
      const existing = toolCalls.get(action.id);
      if (existing) {
        toolCalls.set(action.id, { ...existing, ...action.updates });
      }
      return { ...state, toolCalls };
    }
    case 'SET_STATUS':
      return { ...state, status: action.status };
    case 'SET_THINKING':
      return { ...state, thinking: action.content };
    case 'SET_SPINNER':
      return { ...state, spinner: { visible: action.visible, message: action.message ?? '' } };
    case 'SET_DIALOG':
      return { ...state, dialog: action.dialog };
    case 'TOGGLE_COMMAND_PALETTE':
      return {
        ...state,
        commandPalette: { visible: !state.commandPalette.visible, query: '' },
      };
    case 'SET_COMMAND_QUERY':
      return { ...state, commandPalette: { ...state.commandPalette, query: action.query } };
    case 'CLEAR_MESSAGES':
      return { ...state, messages: [], toolCalls: new Map() };
    case 'SET_FOCUS':
      return { ...state, focused: action.target };
    case 'TOGGLE_ALL_TOOL_CALLS':
      return { ...state, toolCallsExpanded: !state.toolCallsExpanded };
    case 'TOGGLE_THINKING_DISPLAY':
      return { ...state, showThinkingPanel: !state.showThinkingPanel };
    default:
      return state;
  }
}

const AppStateContext = createContext<AppStateContextValue | null>(null);

export const useAppState = () => {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider');
  return ctx;
};

// =============================================================================
// HEADER COMPONENT
// =============================================================================

interface HeaderProps {
  status: StatusDisplay | null;
  title?: string;
}

/**
 * Header component - memoized since it only changes with status updates.
 */
const Header = memo(function Header({ status, title = 'Attocode' }: HeaderProps) {
  const { theme } = useTheme();

  return (
    <Box
      borderStyle="round"
      borderColor={theme.colors.primary}
      paddingX={1}
      justifyContent="space-between"
    >
      <Text bold color={theme.colors.primary}>
        {title}
      </Text>
      {status && (
        <Text color={theme.colors.textMuted}>
          {status.model ?? 'unknown'} | {status.tokens.toLocaleString()} tokens
        </Text>
      )}
    </Box>
  );
});

// =============================================================================
// FOOTER COMPONENT
// =============================================================================

interface FooterProps {
  mode?: string;
}

/**
 * Footer component - memoized since it only changes with mode updates.
 */
const Footer = memo(function Footer({ mode = 'ready' }: FooterProps) {
  const { theme } = useTheme();

  return (
    <Box paddingX={1} justifyContent="space-between">
      <Text color={theme.colors.textMuted}>
        Mode: {mode}
      </Text>
      <Text color={theme.colors.textMuted}>
        Ctrl+P: Commands | Ctrl+C: Exit
      </Text>
    </Box>
  );
});

// =============================================================================
// MESSAGE LIST COMPONENT
// =============================================================================

interface MessageItemProps {
  message: MessageDisplay;
}

/**
 * Single message display - memoized to prevent re-renders on input changes.
 */
const MessageItem = memo(function MessageItem({ message }: MessageItemProps) {
  const { theme } = useTheme();

  const roleColors: Record<string, string> = {
    user: theme.colors.userMessage,
    assistant: theme.colors.assistantMessage,
    system: theme.colors.systemMessage,
    tool: theme.colors.toolMessage,
  };

  const roleIcons: Record<string, string> = {
    user: 'You',
    assistant: 'AI',
    system: 'Sys',
    tool: 'Tool',
  };

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text bold color={roleColors[message.role] || theme.colors.text}>
        [{roleIcons[message.role] || message.role}]
      </Text>
      <Box marginLeft={2}>
        <Text wrap="wrap">{message.content}</Text>
      </Box>
    </Box>
  );
});

interface MessageListProps {
  messages: MessageDisplay[];
  maxHeight?: number;
}

function MessageList({ messages, maxHeight = 20 }: MessageListProps) {
  const { theme } = useTheme();

  // Show only the last N messages to fit in maxHeight
  const visibleMessages = messages.slice(-maxHeight);

  return (
    <Box flexDirection="column" flexGrow={1} overflowY="hidden">
      {visibleMessages.length === 0 ? (
        <Text color={theme.colors.textMuted}>No messages yet. Type a message to start.</Text>
      ) : (
        visibleMessages.map((msg) => <MessageItem key={msg.id} message={msg} />)
      )}
    </Box>
  );
}

// =============================================================================
// TOOL CALL COMPONENT
// =============================================================================

interface ToolCallItemProps {
  toolCall: ToolCallDisplay;
}

/**
 * Single tool call display - memoized to prevent re-renders during typing.
 */
const ToolCallItem = memo(function ToolCallItem({ toolCall }: ToolCallItemProps) {
  const { theme } = useTheme();

  const statusIcons: Record<string, string> = {
    pending: '...',
    running: '>>>',
    success: '+++',
    error: '!!!',
  };

  const statusColors: Record<string, string> = {
    pending: theme.colors.textMuted,
    running: theme.colors.info,
    success: theme.colors.success,
    error: theme.colors.error,
  };

  return (
    <Box>
      <Text color={statusColors[toolCall.status]}>
        [{statusIcons[toolCall.status]}] {toolCall.name}
      </Text>
      {toolCall.duration && (
        <Text color={theme.colors.textMuted}> ({toolCall.duration}ms)</Text>
      )}
    </Box>
  );
});

interface ToolCallListProps {
  toolCalls: Map<string, ToolCallDisplay>;
}

function ToolCallList({ toolCalls }: ToolCallListProps) {
  const { theme } = useTheme();
  const calls = Array.from(toolCalls.values());

  if (calls.length === 0) return null;

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor={theme.colors.border}
      paddingX={1}
      marginTop={1}
    >
      <Text bold color={theme.colors.toolMessage}>Tools</Text>
      {calls.slice(-5).map((tc) => (
        <ToolCallItem key={tc.id} toolCall={tc} />
      ))}
    </Box>
  );
}

// =============================================================================
// SPINNER COMPONENT
// =============================================================================

interface SpinnerDisplayProps {
  message: string;
}

/**
 * Static "working" indicator - no animation to avoid re-render flicker.
 * Animation causes terminal artifacts when content overflows screen height.
 */
function SpinnerDisplay({ message }: SpinnerDisplayProps) {
  const { theme } = useTheme();

  return (
    <Box>
      <Text color={theme.colors.info}>⏳ {message}</Text>
    </Box>
  );
}

// =============================================================================
// INPUT AREA COMPONENT
// =============================================================================

interface InputAreaProps {
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

function InputArea({ onSubmit, disabled = false }: InputAreaProps) {
  const { theme } = useTheme();
  const [value, setValue] = useState('');

  useInput((input, key) => {
    if (disabled) return;

    if (key.return) {
      if (value.trim()) {
        onSubmit(value);
        setValue('');
      }
    } else if (key.backspace || key.delete) {
      setValue((v) => v.slice(0, -1));
    } else if (!key.ctrl && !key.meta && input) {
      setValue((v) => v + input);
    }
  });

  return (
    <Box
      borderStyle="round"
      borderColor={disabled ? theme.colors.textMuted : theme.colors.borderFocus}
      paddingX={1}
    >
      <Text color={theme.colors.primary}>{'>'} </Text>
      <Text>{value}</Text>
      {!disabled && <Text color={theme.colors.textMuted}>|</Text>}
    </Box>
  );
}

// =============================================================================
// MAIN APP COMPONENT
// =============================================================================

export interface AppProps {
  config: TUIConfig;
  handlers: TUIEventHandlers;
  initialState?: Partial<TUIState>;
}

export function App({ config, handlers, initialState }: AppProps) {
  const { exit } = useApp();

  // Theme state
  const [themeName, setThemeName] = useState<ThemeName>(config.theme ?? 'dark');
  const theme = getTheme(themeName);

  // App state using reducer
  const [state, dispatch] = React.useReducer(appReducer, {
    messages: [],
    toolCalls: new Map(),
    status: null,
    thinking: '',
    spinner: { visible: false, message: '' },
    dialog: null,
    commandPalette: { visible: false, query: '' },
    sessions: [],
    activeSessionId: null,
    layout: {
      header: { visible: true, height: 3 },
      sidebar: { visible: config.showSidebar ?? false, width: 30 },
      main: { visible: true },
      footer: { visible: true, height: 1 },
      toolPanel: { visible: config.showToolCalls ?? true, height: 'auto', maxHeight: 10 },
    },
    focused: 'input',
    toolCallsExpanded: false,
    showThinkingPanel: config.showThinking ?? true,
    ...initialState,
  });

  // Handle keyboard shortcuts
  useInput((input, key) => {
    // Ctrl+C to exit
    if (key.ctrl && input === 'c') {
      exit();
      return;
    }

    // Ctrl+P for command palette
    if (key.ctrl && input === 'p') {
      dispatch({ type: 'TOGGLE_COMMAND_PALETTE' });
      return;
    }

    // Ctrl+L to clear
    if (key.ctrl && input === 'l') {
      dispatch({ type: 'CLEAR_MESSAGES' });
      return;
    }

    // Cmd+T (meta+t) to toggle all tool calls expanded/collapsed
    if (key.meta && input === 't') {
      dispatch({ type: 'TOGGLE_ALL_TOOL_CALLS' });
      return;
    }

    // Cmd+O (meta+o) to toggle thinking/reasoning display
    if (key.meta && input === 'o') {
      dispatch({ type: 'TOGGLE_THINKING_DISPLAY' });
      return;
    }

    // Forward to handler
    if (handlers.onKeyPress) {
      handlers.onKeyPress(input, {
        ctrl: key.ctrl ?? false,
        alt: key.meta ?? false,
        meta: key.meta ?? false,
        shift: key.shift ?? false,
      });
    }
  });

  // Handle input submission
  const handleSubmit = useCallback((value: string) => {
    // Check if it's a command
    if (value.startsWith('/')) {
      const [command, ...args] = value.slice(1).split(' ');
      handlers.onCommand?.(command, args);
    } else {
      handlers.onInput?.(value);
    }
  }, [handlers]);

  // Theme context value
  const themeContextValue: ThemeContextValue = {
    theme,
    setTheme: setThemeName,
  };

  // App state context value
  const appStateValue: AppStateContextValue = {
    state,
    dispatch,
  };

  // Keep last N messages visible
  const visibleMessages = state.messages.slice(-15);
  const toolCallsArray = Array.from(state.toolCalls.values()).slice(-5);

  return (
    <ThemeContext.Provider value={themeContextValue}>
      <AppStateContext.Provider value={appStateValue}>
        <Box flexDirection="column" height="100%">
          {/* Messages area - direct rendering */}
          <Box flexDirection="column" flexGrow={1}>
            {visibleMessages.length === 0 ? (
              <Text color={theme.colors.textMuted}>No messages yet. Type a message to start.</Text>
            ) : (
              visibleMessages.map((msg) => <MessageItem key={msg.id} message={msg} />)
            )}
          </Box>

          {/* Tool calls */}
          {toolCallsArray.length > 0 && (
            <Box flexDirection="column" marginBottom={1}>
              <Text bold color={theme.colors.toolMessage}>Tools</Text>
              {toolCallsArray.map((tc) => (
                <Box key={tc.id}>
                  <Text color={
                    tc.status === 'success' ? theme.colors.success :
                    tc.status === 'error' ? theme.colors.error :
                    tc.status === 'running' ? theme.colors.info :
                    theme.colors.textMuted
                  }>
                    [{tc.status === 'success' ? '✓' :
                      tc.status === 'error' ? '✗' :
                      tc.status === 'running' ? '⟳' : '...'}] {tc.name}
                  </Text>
                  {tc.duration && (
                    <Text color={theme.colors.textMuted}> ({tc.duration}ms)</Text>
                  )}
                </Box>
              ))}
            </Box>
          )}

          {/* Spinner - static icon */}
          {state.spinner.visible && (
            <Text color={theme.colors.info}>⏳ {state.spinner.message}</Text>
          )}

          {/* Input */}
          <InputArea
            onSubmit={handleSubmit}
            disabled={state.spinner.visible}
          />
          <Text color={theme.colors.textMuted} dimColor>
            Ctrl+C:Exit | Ctrl+L:Clear
          </Text>
        </Box>
      </AppStateContext.Provider>
    </ThemeContext.Provider>
  );
}

// =============================================================================
// EXPORTS
// =============================================================================

export { ThemeContext, AppStateContext };
export type { AppAction, ThemeContextValue, AppStateContextValue };
