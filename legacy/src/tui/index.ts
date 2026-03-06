/**
 * Terminal User Interface (TUI)
 *
 * Main TUI component: TUIApp from ./app.tsx
 *
 * Features:
 * - Flicker-free rendering via Ink's <Static> component
 * - Single useInput hook (no input conflicts)
 * - Command palette with fuzzy search (Ctrl+P)
 * - Theme system (dark, light, high-contrast)
 *
 * Anti-flicker patterns used:
 * - Messages render once via <Static>, never re-render
 * - Ref-based callbacks prevent useInput re-subscription
 * - Custom memo comparators for controlled re-rendering
 *
 * Note: SimpleTextRenderer uses console.log/error for user-facing terminal output.
 * These are intentionally kept as console calls (not logger) since they render
 * visible output in the fallback TUI mode.
 */

import { logger } from '../integrations/utilities/logger.js';

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

export interface TUIRenderer {
  init(): Promise<void>;
  renderUserMessage(message: string): void;
  renderAssistantMessage(content: string, streaming?: boolean): void;
  renderToolCall(toolCall: ToolCallDisplay): void;
  updateToolCallResult(id: string, result: unknown, error?: string): void;
  renderThinking(content: string): void;
  updateStatus(status: StatusDisplay): void;
  showSpinner(message: string): void;
  hideSpinner(): void;
  promptInput(prompt: string): Promise<string>;
  showError(error: string): void;
  showSuccess(message: string): void;
  clear(): void;
  cleanup(): void;
}

// =============================================================================
// SIMPLE TEXT RENDERER (Fallback)
// =============================================================================

const syntax = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  keyword: '\x1b[35m',
  string: '\x1b[32m',
  comment: '\x1b[90m',
  number: '\x1b[33m',
  function: '\x1b[36m',
  type: '\x1b[34m',
  operator: '\x1b[37m',
  codeBlock: '\x1b[48;5;236m',
  codeLang: '\x1b[33m',
};

function highlightCode(code: string, lang: string): string {
  const lines = code.split('\n');
  return lines.map((line) => highlightLine(line, lang)).join('\n');
}

function highlightLine(line: string, lang: string): string {
  const keywords: Record<string, string[]> = {
    python: [
      'def',
      'class',
      'if',
      'elif',
      'else',
      'for',
      'while',
      'return',
      'import',
      'from',
      'as',
      'try',
      'except',
      'finally',
      'with',
      'lambda',
      'yield',
      'async',
      'await',
      'True',
      'False',
      'None',
      'and',
      'or',
      'not',
      'in',
      'is',
    ],
    javascript: [
      'function',
      'const',
      'let',
      'var',
      'if',
      'else',
      'for',
      'while',
      'return',
      'import',
      'export',
      'from',
      'class',
      'extends',
      'new',
      'this',
      'try',
      'catch',
      'finally',
      'async',
      'await',
      'true',
      'false',
      'null',
      'undefined',
      'typeof',
      'instanceof',
    ],
    typescript: [
      'function',
      'const',
      'let',
      'var',
      'if',
      'else',
      'for',
      'while',
      'return',
      'import',
      'export',
      'from',
      'class',
      'extends',
      'new',
      'this',
      'try',
      'catch',
      'finally',
      'async',
      'await',
      'true',
      'false',
      'null',
      'undefined',
      'typeof',
      'instanceof',
      'interface',
      'type',
      'enum',
      'as',
      'implements',
      'private',
      'public',
      'protected',
    ],
  };

  const langKeywords = keywords[lang.toLowerCase()] || keywords['javascript'] || [];
  let result = line;

  const commentPatterns = [/^(\s*)(#.*)$/, /^(\s*)(\/\/.*)$/];
  for (const pattern of commentPatterns) {
    const match = result.match(pattern);
    if (match) {
      return match[1] + syntax.comment + match[2] + syntax.reset;
    }
  }

  result = result.replace(
    /(["'`])((?:\\\1|(?:(?!\1)).)*)(\1)/g,
    syntax.string + '$1$2$3' + syntax.reset,
  );
  result = result.replace(/\b(\d+\.?\d*)\b/g, syntax.number + '$1' + syntax.reset);

  for (const kw of langKeywords) {
    const regex = new RegExp(`\\b(${kw})\\b`, 'g');
    result = result.replace(regex, syntax.keyword + '$1' + syntax.reset);
  }

  result = result.replace(/\b([a-zA-Z_]\w*)\s*\(/g, syntax.function + '$1' + syntax.reset + '(');
  return result;
}

function formatAssistantContent(content: string): string {
  const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
  return content.replace(codeBlockRegex, (_match, lang, code) => {
    const langLabel = lang ? `${syntax.codeLang}[${lang}]${syntax.reset}` : '';
    const highlighted = highlightCode(code.trimEnd(), lang || 'text');
    return `\n${langLabel}\n${syntax.dim}${'─'.repeat(40)}${syntax.reset}\n${highlighted}\n${syntax.dim}${'─'.repeat(40)}${syntax.reset}`;
  });
}

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

  async init(): Promise<void> {}

  renderUserMessage(message: string): void {
    // eslint-disable-next-line no-console
    console.log(`\n\x1b[36m👤 User:\x1b[0m ${message}`);
  }

  renderAssistantMessage(content: string, streaming = false): void {
    if (streaming) {
      process.stdout.write(content);
    } else {
      const formatted = formatAssistantContent(content);
      // eslint-disable-next-line no-console
      console.log(`\n\x1b[32m🤖 Assistant:\x1b[0m ${formatted}`);
    }
  }

  renderToolCall(toolCall: ToolCallDisplay): void {
    if (!this.config.showToolCalls) return;
    const statusEmoji = { pending: '⏳', running: '🔄', success: '✅', error: '❌' }[
      toolCall.status
    ];
    // eslint-disable-next-line no-console
    console.log(`\n${statusEmoji} \x1b[33mTool:\x1b[0m ${toolCall.name}`);
    if (Object.keys(toolCall.args).length > 0) {
      const argsStr = JSON.stringify(toolCall.args, null, 2)
        .split('\n')
        .map((line) => '    ' + line)
        .join('\n');
      // eslint-disable-next-line no-console
      console.log(`\x1b[90m${argsStr}\x1b[0m`);
    }
  }

  updateToolCallResult(_id: string, result: unknown, error?: string): void {
    if (!this.config.showToolCalls) return;
    if (error) {
      // eslint-disable-next-line no-console
      console.log(`\x1b[31m    Error: ${error}\x1b[0m`);
    } else {
      const resultStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
      const truncated = resultStr.length > 500 ? resultStr.slice(0, 500) + '...' : resultStr;
      // eslint-disable-next-line no-console
      console.log(`\x1b[90m    Result: ${truncated}\x1b[0m`);
    }
  }

  renderThinking(content: string): void {
    if (!this.config.showThinking) return;
    // eslint-disable-next-line no-console
    console.log(`\x1b[90m💭 ${content}\x1b[0m`);
  }

  updateStatus(status: StatusDisplay): void {
    const statusLine = [
      `Mode: ${status.mode}`,
      `Iter: ${status.iteration}`,
      `Tokens: ${status.tokens.toLocaleString()}`,
      `Time: ${(status.elapsed / 1000).toFixed(1)}s`,
    ].join(' | ');
    // eslint-disable-next-line no-console
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
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    return new Promise((resolve) => {
      rl.question(`\x1b[36m${prompt}\x1b[0m `, (answer) => {
        rl.close();
        resolve(answer);
      });
    });
  }

  showError(error: string): void {
    logger.error('SimpleTextRenderer error displayed', { error });
    // eslint-disable-next-line no-console
    console.error(`\n\x1b[31m❌ Error: ${error}\x1b[0m`);
  }

  showSuccess(message: string): void {
    // eslint-disable-next-line no-console
    console.log(`\n\x1b[32m✅ ${message}\x1b[0m`);
  }

  clear(): void {
    // eslint-disable-next-line no-console
    console.clear();
  }

  cleanup(): void {
    this.hideSpinner();
  }
}

// =============================================================================
// FACTORY
// =============================================================================

async function isInkAvailable(): Promise<boolean> {
  try {
    const inkModule = 'ink';
    await import(inkModule);
    return true;
  } catch {
    return false;
  }
}

export async function createTUIRenderer(config: TUIConfig = {}): Promise<TUIRenderer> {
  // The actual TUI is in main.ts - this is just the fallback renderer
  return new SimpleTextRenderer(config);
}

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

// Types from types.ts
export type { ThemeColors, Theme, ThemeName, TUIState, TUIEventHandlers } from './types.js';

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
} from './theme/index.js';

// =============================================================================
// COMPONENTS
// =============================================================================

// Main TUI App component
export { TUIApp, type TUIAppProps } from './app.js';

// UI components
export {
  ScrollableBox,
  type ScrollableBoxProps,
  MessageItem,
  type MessageItemProps,
  type TUIMessage,
  ToolCallItem,
  type ToolCallItemProps,
  type ToolCallDisplayItem,
  MemoizedInputArea,
  type InputAreaProps,
  ApprovalDialog,
  type ApprovalDialogProps,
  type ApprovalRequest as TUIApprovalRequest,
} from './components/index.js';

// Command palette
export {
  ControlledCommandPalette,
  CommandPalette,
  type ControlledCommandPaletteProps,
  type CommandPaletteProps,
} from './input/CommandPalette.js';

// Event display (console output handlers)
export { createEventDisplay, createJunctureLogger } from './event-display.js';

// Transparency aggregator (decision tracking)
export {
  TransparencyAggregator,
  createTransparencyAggregator,
  formatTransparencyState,
  getTransparencySummary,
  type TransparencyState,
  type DecisionRecord,
  type TransparencyAggregatorConfig,
} from './transparency-aggregator.js';

// =============================================================================
// NEW MODERNIZATION EXPORTS
// =============================================================================

// Error boundaries
export { TUIErrorBoundary, ErrorFallback, withErrorBoundary } from './components/ErrorBoundary.js';

// Message pruning hook
export {
  useMessagePruning,
  type TUIMessage as PruningTUIMessage,
  type MessagePruningConfig,
  type PruneStats,
  type UseMessagePruningResult,
} from './hooks/index.js';

// Cross-platform keyboard utilities
export {
  detectAltShortcut,
  isAltShortcut,
  normalizeShortcut,
  createShortcutHandler,
  formatShortcutDisplay,
  type KeyEvent,
  type NormalizedShortcut,
  type ShortcutHandlers,
} from './utils/index.js';
