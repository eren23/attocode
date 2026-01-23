/**
 * Terminal User Interface (TUI)
 *
 * Provides a rich terminal interface for the agent using Ink (React for CLI).
 * Falls back to simple text output if Ink is not installed.
 *
 * Features:
 * - Streaming message display
 * - Tool call visualization
 * - Progress indicators
 * - Multi-panel layout
 * - Keyboard shortcuts
 */

// =============================================================================
// TYPES
// =============================================================================

export interface TUIConfig {
  /** Enable TUI mode (default: auto-detect) */
  enabled?: boolean;
  /** Show streaming output */
  showStreaming?: boolean;
  /** Show tool calls */
  showToolCalls?: boolean;
  /** Show thinking/reasoning */
  showThinking?: boolean;
  /** Color theme */
  theme?: 'dark' | 'light' | 'auto';
  /** Maximum height for message panels */
  maxPanelHeight?: number;
}

export interface MessageDisplay {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  timestamp?: Date;
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
}

export interface StatusDisplay {
  mode: string;
  iteration: number;
  tokens: number;
  cost: number;
  elapsed: number;
}

// =============================================================================
// TUI RENDERER INTERFACE
// =============================================================================

/**
 * Interface for TUI renderers.
 */
export interface TUIRenderer {
  /** Initialize the TUI */
  init(): Promise<void>;

  /** Render a user message */
  renderUserMessage(message: string): void;

  /** Render an assistant message (supports streaming) */
  renderAssistantMessage(content: string, streaming?: boolean): void;

  /** Render a tool call */
  renderToolCall(toolCall: ToolCallDisplay): void;

  /** Update a tool call result */
  updateToolCallResult(id: string, result: unknown, error?: string): void;

  /** Render thinking/reasoning */
  renderThinking(content: string): void;

  /** Update status bar */
  updateStatus(status: StatusDisplay): void;

  /** Show a progress spinner */
  showSpinner(message: string): void;

  /** Hide the spinner */
  hideSpinner(): void;

  /** Prompt for user input */
  promptInput(prompt: string): Promise<string>;

  /** Show an error */
  showError(error: string): void;

  /** Show a success message */
  showSuccess(message: string): void;

  /** Clear the screen */
  clear(): void;

  /** Cleanup and exit */
  cleanup(): void;
}

// =============================================================================
// SIMPLE TEXT RENDERER (Fallback)
// =============================================================================

// ANSI color codes for syntax highlighting
const syntax = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  // Code colors
  keyword: '\x1b[35m',      // magenta - keywords like def, class, if, return
  string: '\x1b[32m',       // green - string literals
  comment: '\x1b[90m',      // gray - comments
  number: '\x1b[33m',       // yellow - numbers
  function: '\x1b[36m',     // cyan - function names
  type: '\x1b[34m',         // blue - type annotations
  operator: '\x1b[37m',     // white - operators
  // UI colors
  codeBlock: '\x1b[48;5;236m', // dark gray background
  codeLang: '\x1b[33m',        // yellow - language label
};

/**
 * Simple syntax highlighting for code blocks.
 * Supports Python, JavaScript/TypeScript, and generic code.
 */
function highlightCode(code: string, lang: string): string {
  const lines = code.split('\n');
  const highlightedLines = lines.map(line => highlightLine(line, lang));
  return highlightedLines.join('\n');
}

function highlightLine(line: string, lang: string): string {
  // Common keywords by language
  const keywords: Record<string, string[]> = {
    python: ['def', 'class', 'if', 'elif', 'else', 'for', 'while', 'return', 'import', 'from', 'as', 'try', 'except', 'finally', 'with', 'lambda', 'yield', 'async', 'await', 'True', 'False', 'None', 'and', 'or', 'not', 'in', 'is'],
    javascript: ['function', 'const', 'let', 'var', 'if', 'else', 'for', 'while', 'return', 'import', 'export', 'from', 'class', 'extends', 'new', 'this', 'try', 'catch', 'finally', 'async', 'await', 'true', 'false', 'null', 'undefined', 'typeof', 'instanceof'],
    typescript: ['function', 'const', 'let', 'var', 'if', 'else', 'for', 'while', 'return', 'import', 'export', 'from', 'class', 'extends', 'new', 'this', 'try', 'catch', 'finally', 'async', 'await', 'true', 'false', 'null', 'undefined', 'typeof', 'instanceof', 'interface', 'type', 'enum', 'as', 'implements', 'private', 'public', 'protected'],
  };

  const langKeywords = keywords[lang.toLowerCase()] || keywords['javascript'] || [];
  let result = line;

  // Highlight comments first (so they don't get double-processed)
  const commentPatterns = [
    /^(\s*)(#.*)$/,           // Python comments
    /^(\s*)(\/\/.*)$/,        // JS/TS single-line comments
  ];
  for (const pattern of commentPatterns) {
    const match = result.match(pattern);
    if (match) {
      return match[1] + syntax.comment + match[2] + syntax.reset;
    }
  }

  // Highlight strings (simplified - doesn't handle escapes perfectly)
  result = result.replace(/(["'`])((?:\\\1|(?:(?!\1)).)*)(\1)/g,
    syntax.string + '$1$2$3' + syntax.reset);

  // Highlight numbers
  result = result.replace(/\b(\d+\.?\d*)\b/g,
    syntax.number + '$1' + syntax.reset);

  // Highlight keywords (word boundary matching)
  for (const kw of langKeywords) {
    const regex = new RegExp(`\\b(${kw})\\b`, 'g');
    result = result.replace(regex, syntax.keyword + '$1' + syntax.reset);
  }

  // Highlight function calls (word followed by open paren)
  result = result.replace(/\b([a-zA-Z_]\w*)\s*\(/g,
    syntax.function + '$1' + syntax.reset + '(');

  return result;
}

/**
 * Format assistant message with code block highlighting.
 */
function formatAssistantContent(content: string): string {
  // Detect and highlight markdown code blocks
  const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;

  return content.replace(codeBlockRegex, (_match, lang, code) => {
    const langLabel = lang ? `${syntax.codeLang}[${lang}]${syntax.reset}` : '';
    const highlighted = highlightCode(code.trimEnd(), lang || 'text');

    // Add visual code block formatting
    return `\n${langLabel}\n${syntax.dim}${'─'.repeat(40)}${syntax.reset}\n${highlighted}\n${syntax.dim}${'─'.repeat(40)}${syntax.reset}`;
  });
}

/**
 * Simple text-based renderer for when Ink is not available.
 */
export class SimpleTextRenderer implements TUIRenderer {
  private config: Required<TUIConfig>;
  private spinnerInterval: NodeJS.Timeout | null = null;

  constructor(config: TUIConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
      showStreaming: config.showStreaming ?? true,
      showToolCalls: config.showToolCalls ?? true,
      showThinking: config.showThinking ?? false,
      theme: config.theme ?? 'auto',
      maxPanelHeight: config.maxPanelHeight ?? 20,
    };
  }

  async init(): Promise<void> {
    // No initialization needed for simple text
  }

  renderUserMessage(message: string): void {
    console.log(`\n\x1b[36m👤 User:\x1b[0m ${message}`);
  }

  renderAssistantMessage(content: string, streaming = false): void {
    if (streaming) {
      process.stdout.write(content);
    } else {
      // Format content with code block highlighting
      const formatted = formatAssistantContent(content);
      console.log(`\n\x1b[32m🤖 Assistant:\x1b[0m ${formatted}`);
    }
  }

  renderToolCall(toolCall: ToolCallDisplay): void {
    if (!this.config.showToolCalls) return;

    const statusEmoji = {
      pending: '⏳',
      running: '🔄',
      success: '✅',
      error: '❌',
    }[toolCall.status];

    console.log(`\n${statusEmoji} \x1b[33mTool:\x1b[0m ${toolCall.name}`);

    if (Object.keys(toolCall.args).length > 0) {
      const argsStr = JSON.stringify(toolCall.args, null, 2)
        .split('\n')
        .map(line => '    ' + line)
        .join('\n');
      console.log(`\x1b[90m${argsStr}\x1b[0m`);
    }
  }

  updateToolCallResult(_id: string, result: unknown, error?: string): void {
    if (!this.config.showToolCalls) return;

    if (error) {
      console.log(`\x1b[31m    Error: ${error}\x1b[0m`);
    } else {
      const resultStr = typeof result === 'string'
        ? result
        : JSON.stringify(result, null, 2);
      const truncated = resultStr.length > 500
        ? resultStr.slice(0, 500) + '...'
        : resultStr;
      console.log(`\x1b[90m    Result: ${truncated}\x1b[0m`);
    }
  }

  renderThinking(content: string): void {
    if (!this.config.showThinking) return;
    console.log(`\x1b[90m💭 ${content}\x1b[0m`);
  }

  updateStatus(status: StatusDisplay): void {
    const statusLine = [
      `Mode: ${status.mode}`,
      `Iter: ${status.iteration}`,
      `Tokens: ${status.tokens.toLocaleString()}`,
      // TODO: Cost display disabled - OpenRouter cost retrieval needs fixing
      `Time: ${(status.elapsed / 1000).toFixed(1)}s`,
    ].join(' | ');

    console.log(`\x1b[90m[${statusLine}]\x1b[0m`);
  }

  showSpinner(message: string): void {
    const frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
    let i = 0;

    this.hideSpinner();
    this.spinnerInterval = setInterval(() => {
      process.stdout.write(`\r${frames[i % frames.length]} ${message}`);
      i++;
    }, 80);
  }

  hideSpinner(): void {
    if (this.spinnerInterval) {
      clearInterval(this.spinnerInterval);
      this.spinnerInterval = null;
      process.stdout.write('\r\x1b[K');
    }
  }

  async promptInput(prompt: string): Promise<string> {
    const readline = await import('readline');
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });

    return new Promise((resolve) => {
      rl.question(`\x1b[36m${prompt}\x1b[0m `, (answer) => {
        rl.close();
        resolve(answer);
      });
    });
  }

  showError(error: string): void {
    console.error(`\n\x1b[31m❌ Error: ${error}\x1b[0m`);
  }

  showSuccess(message: string): void {
    console.log(`\n\x1b[32m✅ ${message}\x1b[0m`);
  }

  clear(): void {
    console.clear();
  }

  cleanup(): void {
    this.hideSpinner();
  }
}

// =============================================================================
// INK RENDERER (Rich TUI)
// =============================================================================

/**
 * Check if Ink is available.
 */
async function isInkAvailable(): Promise<boolean> {
  try {
    // Dynamic import to check availability
    // Use a variable to prevent static analysis from trying to resolve the module
    const inkModule = 'ink';
    await import(inkModule);
    return true;
  } catch {
    return false;
  }
}

/**
 * Ink-based renderer for rich terminal UI.
 * This is loaded dynamically only when Ink is available.
 */
export async function createInkRenderer(config: TUIConfig = {}): Promise<TUIRenderer | null> {
  if (!await isInkAvailable()) {
    return null;
  }

  // Dynamic import to avoid loading Ink if not needed
  try {
    const { InkRenderer } = await import('./ink-renderer.js');
    return new InkRenderer(config);
  } catch {
    return null;
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a TUI renderer, preferring Ink if available.
 */
export async function createTUIRenderer(config: TUIConfig = {}): Promise<TUIRenderer> {
  // Check if we should use Ink
  if (config.enabled !== false) {
    const inkRenderer = await createInkRenderer(config);
    if (inkRenderer) {
      return inkRenderer;
    }
  }

  // Fall back to simple text renderer
  return new SimpleTextRenderer(config);
}

/**
 * Check TUI capabilities.
 */
export async function checkTUICapabilities(): Promise<{
  inkAvailable: boolean;
  colorSupport: boolean;
  unicodeSupport: boolean;
  interactiveTerminal: boolean;
}> {
  return {
    inkAvailable: await isInkAvailable(),
    colorSupport: process.stdout.isTTY && process.env.TERM !== 'dumb',
    unicodeSupport: process.env.TERM !== 'dumb',
    interactiveTerminal: process.stdin.isTTY && process.stdout.isTTY,
  };
}

// =============================================================================
// RE-EXPORTS
// =============================================================================

export { SimpleTextRenderer as FallbackRenderer };
export { formatAssistantContent, highlightCode };

// Types - export specific types to avoid conflicts
export type {
  TUIConfig as TUIConfigFull,
  TUIState,
  TUIEventHandlers,
  MessageDisplay as MessageDisplayFull,
  ToolCallDisplay as ToolCallDisplayFull,
  StatusDisplay as StatusDisplayFull,
  SessionDisplay,
  DialogType,
  DialogConfig,
  DialogOption,
  PermissionDialogConfig,
  CommandPaletteItem,
  KeyBinding,
  PanelConfig,
  LayoutConfig,
  ThemeName,
  DEFAULT_TUI_STATE,
} from './types.js';

// Theme system
export {
  getTheme,
  registerTheme,
  getThemeNames,
  detectSystemTheme,
  darkTheme,
  lightTheme,
  highContrastTheme,
  hexToAnsi,
  getAnsiColor,
  type Theme,
  type ThemeColors,
} from './theme/index.js';

// Layout components
export { Header, Footer, Sidebar } from './layout/index.js';
export type { HeaderProps, FooterProps, SidebarProps } from './layout/index.js';

// Core UI components
export { MessageList, CodeBlock, ToolCall, ToolCallList } from './components/index.js';
export type {
  MessageListProps,
  CodeBlockProps,
  ToolCallProps,
  ToolCallListProps,
} from './components/index.js';

// Input components
export { Editor, CommandPalette } from './input/index.js';
export type { EditorProps, CommandPaletteProps } from './input/index.js';

// Dialog components
export {
  BaseDialog,
  ConfirmDialog,
  PromptDialog,
  SelectDialog,
  PermissionDialog,
  SessionDialog,
  ModelDialog,
  defaultModels,
} from './dialogs/index.js';
export type {
  DialogProps,
  BaseDialogProps,
  ConfirmDialogProps,
  PromptDialogProps,
  SelectDialogProps,
  PermissionDialogProps,
  SessionDialogProps,
  ModelDialogProps,
  ModelInfo,
} from './dialogs/index.js';

// Command system
export {
  CommandRegistry,
  commandRegistry,
  commands,
} from './commands.js';
export type {
  CommandDefinition,
  CommandArgument,
  CommandCategory,
  CommandAction,
  CommandContext,
  CommandResult,
} from './commands.js';
