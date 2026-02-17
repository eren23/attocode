/**
 * TUI Type Definitions
 *
 * Core types for the Terminal User Interface system.
 */

import type { AgentEvent } from '../types.js';

// =============================================================================
// CONFIGURATION
// =============================================================================

export interface TUIConfig {
  /** Enable TUI mode (default: auto-detect TTY) */
  enabled?: boolean;
  /** Show streaming output */
  showStreaming?: boolean;
  /** Show tool calls */
  showToolCalls?: boolean;
  /** Show thinking/reasoning */
  showThinking?: boolean;
  /** Color theme */
  theme?: ThemeName;
  /** Maximum height for message panels */
  maxPanelHeight?: number;
  /** Show sidebar with session info */
  showSidebar?: boolean;
  /** Enable keyboard shortcuts */
  enableShortcuts?: boolean;
  /** Image rendering protocol */
  imageProtocol?: 'sixel' | 'iterm' | 'kitty' | 'none' | 'auto';
}

export type ThemeName = 'dark' | 'light' | 'auto' | string;

// =============================================================================
// THEME
// =============================================================================

export interface ThemeColors {
  // Primary colors
  primary: string;
  secondary: string;
  accent: string;

  // Text colors
  text: string;
  textMuted: string;
  textInverse: string;

  // Background colors
  background: string;
  backgroundAlt: string;

  // Semantic colors
  success: string;
  error: string;
  warning: string;
  info: string;

  // Component colors
  border: string;
  borderFocus: string;

  // Role colors
  userMessage: string;
  assistantMessage: string;
  systemMessage: string;
  toolMessage: string;

  // Code colors
  codeBackground: string;
  codeKeyword: string;
  codeString: string;
  codeComment: string;
  codeNumber: string;
  codeFunction: string;
  codeType: string;
}

export interface Theme {
  name: string;
  colors: ThemeColors;
  borderStyle: 'single' | 'double' | 'round' | 'bold' | 'classic';
  spinnerType: 'dots' | 'line' | 'arc' | 'bounce';
}

// =============================================================================
// DISPLAY MODELS
// =============================================================================

export interface MessageDisplay {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  timestamp: Date;
  streaming?: boolean;
  metadata?: Record<string, unknown>;
}

export interface ToolCallDisplay {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: 'pending' | 'running' | 'success' | 'error';
  result?: unknown;
  error?: string;
  duration?: number;
  startTime?: Date;
}

export interface StatusDisplay {
  mode: string;
  iteration: number;
  tokens: number;
  maxTokens: number;
  cost: number;
  elapsed: number;
  model?: string;
  sessionId?: string;
}

export interface SessionDisplay {
  id: string;
  name?: string;
  createdAt: Date;
  lastActiveAt: Date;
  messageCount: number;
  tokenCount: number;
  active: boolean;
}

// =============================================================================
// DIALOG TYPES
// =============================================================================

export type DialogType =
  | 'permission'
  | 'session'
  | 'model'
  | 'settings'
  | 'confirm'
  | 'prompt'
  | 'search';

export interface DialogConfig {
  type: DialogType;
  title: string;
  message?: string;
  options?: DialogOption[];
  defaultValue?: string;
  onConfirm?: (value: unknown) => void;
  onCancel?: () => void;
}

export interface DialogOption {
  label: string;
  value: string;
  shortcut?: string;
  description?: string;
}

export interface PermissionDialogConfig extends DialogConfig {
  type: 'permission';
  tool: string;
  args: Record<string, unknown>;
  dangerLevel: 'safe' | 'moderate' | 'dangerous';
}

// =============================================================================
// INPUT TYPES
// =============================================================================

export interface CommandPaletteItem {
  id: string;
  label: string;
  description?: string;
  shortcut?: string;
  category?: string;
  action: () => void | Promise<void>;
}

export interface KeyBinding {
  key: string;
  ctrl?: boolean;
  alt?: boolean;
  meta?: boolean;
  shift?: boolean;
  action: string;
  description: string;
}

// =============================================================================
// LAYOUT TYPES
// =============================================================================

export interface PanelConfig {
  visible: boolean;
  height?: number | 'auto';
  width?: number | 'auto';
  minHeight?: number;
  maxHeight?: number;
}

export interface LayoutConfig {
  header: PanelConfig;
  sidebar: PanelConfig;
  main: PanelConfig;
  footer: PanelConfig;
  toolPanel: PanelConfig;
}

// =============================================================================
// EVENT HANDLERS
// =============================================================================

export interface TUIEventHandlers {
  onInput?: (input: string) => void;
  onCommand?: (command: string, args: string[]) => void;
  onKeyPress?: (
    key: string,
    modifiers: { ctrl: boolean; alt: boolean; meta: boolean; shift: boolean },
  ) => void;
  onAgentEvent?: (event: AgentEvent) => void;
  onPermissionRequest?: (tool: string, args: Record<string, unknown>) => Promise<boolean>;
  onSessionSwitch?: (sessionId: string) => void;
}

// =============================================================================
// COMPONENT PROPS
// =============================================================================

export interface MessageListProps {
  messages: MessageDisplay[];
  maxHeight?: number;
  showTimestamps?: boolean;
  onMessageClick?: (id: string) => void;
}

export interface ToolCallProps {
  toolCall: ToolCallDisplay;
  expanded?: boolean;
  onToggle?: () => void;
}

export interface CodeBlockProps {
  code: string;
  language?: string;
  showLineNumbers?: boolean;
  highlightLines?: number[];
  maxHeight?: number;
}

export interface InputEditorProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  disabled?: boolean;
}

// =============================================================================
// TUI STATE
// =============================================================================

export interface TUIState {
  messages: MessageDisplay[];
  toolCalls: Map<string, ToolCallDisplay>;
  status: StatusDisplay | null;
  thinking: string;
  spinner: { visible: boolean; message: string };
  dialog: DialogConfig | null;
  commandPalette: { visible: boolean; query: string };
  sessions: SessionDisplay[];
  activeSessionId: string | null;
  layout: LayoutConfig;
  focused: 'input' | 'messages' | 'tools' | 'sidebar';
  /** When true, all tool calls are expanded globally (Cmd+T toggle) */
  toolCallsExpanded: boolean;
  /** When true, thinking/reasoning panel is visible (Cmd+O toggle) */
  showThinkingPanel: boolean;
}

export const DEFAULT_TUI_STATE: TUIState = {
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
    sidebar: { visible: false, width: 30 },
    main: { visible: true },
    footer: { visible: true, height: 1 },
    toolPanel: { visible: true, height: 'auto', maxHeight: 10 },
  },
  focused: 'input',
  toolCallsExpanded: false,
  showThinkingPanel: true,
};
