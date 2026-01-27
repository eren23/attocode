/**
 * Lesson 4: Streaming UI
 * 
 * Terminal UI for displaying streaming output.
 */

import chalk from 'chalk';
import type { StreamEvent, StreamEventHandler } from './types.js';

// =============================================================================
// STREAM RENDERER
// =============================================================================

/**
 * Configuration for the stream renderer.
 */
export interface RendererConfig {
  /** Show tool executions */
  showTools?: boolean;
  
  /** Show thinking/reasoning */
  showThinking?: boolean;
  
  /** Color theme */
  theme?: 'default' | 'minimal' | 'colorful';
  
  /** Show timestamps */
  timestamps?: boolean;
}

/**
 * Create a stream event handler that renders to the terminal.
 */
export function createStreamRenderer(config: RendererConfig = {}): StreamEventHandler {
  const { 
    showTools = true, 
    showThinking = true,
    theme = 'default',
    timestamps = false,
  } = config;

  const colors = getThemeColors(theme);
  let currentLine = '';
  let toolDepth = 0;

  return (event: StreamEvent) => {
    const prefix = timestamps ? chalk.gray(`[${getTimestamp()}] `) : '';

    switch (event.type) {
      case 'text':
        // Write text incrementally
        process.stdout.write(colors.text(event.text));
        currentLine += event.text;
        
        // Track newlines for formatting
        if (event.text.includes('\n')) {
          currentLine = event.text.split('\n').pop() ?? '';
        }
        break;

      case 'thinking':
        if (showThinking) {
          // Dim thinking text
          if (currentLine.length > 0) {
            process.stdout.write('\n');
            currentLine = '';
          }
          process.stdout.write(prefix + colors.thinking(`💭 ${event.text}\n`));
        }
        break;

      case 'tool_start':
        if (showTools) {
          if (currentLine.length > 0) {
            process.stdout.write('\n');
            currentLine = '';
          }
          toolDepth++;
          const indent = '  '.repeat(toolDepth - 1);
          process.stdout.write(prefix + indent + colors.toolStart(`🔧 ${event.tool}\n`));
        }
        break;

      case 'tool_input':
        if (showTools) {
          const indent = '  '.repeat(toolDepth);
          const inputStr = JSON.stringify(event.input, null, 2)
            .split('\n')
            .map(line => indent + colors.toolInput(line))
            .join('\n');
          process.stdout.write(inputStr + '\n');
        }
        break;

      case 'tool_end':
        if (showTools) {
          const indent = '  '.repeat(toolDepth);
          const icon = event.success ? '✅' : '❌';
          const outputPreview = event.output.slice(0, 100).replace(/\n/g, ' ');
          process.stdout.write(
            prefix + indent + colors.toolEnd(`${icon} ${outputPreview}${event.output.length > 100 ? '...' : ''}\n`)
          );
          toolDepth = Math.max(0, toolDepth - 1);
        }
        break;

      case 'error':
        if (currentLine.length > 0) {
          process.stdout.write('\n');
          currentLine = '';
        }
        const errorIcon = event.recoverable ? '⚠️' : '❌';
        process.stdout.write(prefix + colors.error(`${errorIcon} ${event.error}\n`));
        break;

      case 'done':
        if (currentLine.length > 0) {
          process.stdout.write('\n');
        }
        process.stdout.write('\n' + prefix + colors.done(`✨ Done (${event.reason})\n`));
        break;
    }
  };
}

// =============================================================================
// THEMES
// =============================================================================

interface ThemeColors {
  text: (s: string) => string;
  thinking: (s: string) => string;
  toolStart: (s: string) => string;
  toolInput: (s: string) => string;
  toolEnd: (s: string) => string;
  error: (s: string) => string;
  done: (s: string) => string;
}

function getThemeColors(theme: string): ThemeColors {
  switch (theme) {
    case 'minimal':
      return {
        text: (s) => s,
        thinking: (s) => chalk.dim(s),
        toolStart: (s) => chalk.dim(s),
        toolInput: (s) => chalk.dim(s),
        toolEnd: (s) => chalk.dim(s),
        error: (s) => chalk.red(s),
        done: (s) => chalk.dim(s),
      };

    case 'colorful':
      return {
        text: (s) => chalk.white(s),
        thinking: (s) => chalk.magenta(s),
        toolStart: (s) => chalk.cyan.bold(s),
        toolInput: (s) => chalk.cyan.dim(s),
        toolEnd: (s) => chalk.cyan(s),
        error: (s) => chalk.red.bold(s),
        done: (s) => chalk.green.bold(s),
      };

    default:
      return {
        text: (s) => s,
        thinking: (s) => chalk.dim.italic(s),
        toolStart: (s) => chalk.yellow(s),
        toolInput: (s) => chalk.gray(s),
        toolEnd: (s) => chalk.yellow(s),
        error: (s) => chalk.red(s),
        done: (s) => chalk.green(s),
      };
  }
}

function getTimestamp(): string {
  const now = new Date();
  return now.toLocaleTimeString('en-US', { 
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

// =============================================================================
// SPINNER
// =============================================================================

const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

/**
 * Create a terminal spinner.
 */
export function createSpinner(message: string): { stop: () => void; update: (msg: string) => void } {
  let frame = 0;
  let currentMessage = message;
  let running = true;

  const interval = setInterval(() => {
    if (!running) return;
    
    process.stdout.write(`\r${chalk.cyan(SPINNER_FRAMES[frame])} ${currentMessage}`);
    frame = (frame + 1) % SPINNER_FRAMES.length;
  }, 80);

  return {
    stop: () => {
      running = false;
      clearInterval(interval);
      process.stdout.write('\r' + ' '.repeat(currentMessage.length + 3) + '\r');
    },
    update: (msg: string) => {
      currentMessage = msg;
    },
  };
}

// =============================================================================
// PROGRESS BAR
// =============================================================================

/**
 * Create a simple progress bar.
 */
export function createProgressBar(total: number, width = 40): {
  update: (current: number) => void;
  complete: () => void;
} {
  let lastRendered = -1;

  return {
    update: (current: number) => {
      const percent = Math.min(100, Math.floor((current / total) * 100));
      if (percent === lastRendered) return;
      lastRendered = percent;

      const filled = Math.floor((percent / 100) * width);
      const empty = width - filled;
      const bar = chalk.green('█'.repeat(filled)) + chalk.gray('░'.repeat(empty));
      
      process.stdout.write(`\r[${bar}] ${percent}%`);
    },
    complete: () => {
      process.stdout.write('\n');
    },
  };
}
