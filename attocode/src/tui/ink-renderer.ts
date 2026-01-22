/**
 * Ink-based TUI Renderer
 *
 * Rich terminal UI using Ink (React for CLI).
 * This file is only loaded when Ink is available.
 *
 * To use this, install Ink:
 *   npm install ink ink-spinner ink-text-input react
 *
 * Note: This file uses dynamic imports and 'any' types to avoid
 * requiring Ink/React as compile-time dependencies.
 */

import type { TUIRenderer, TUIConfig, ToolCallDisplay, StatusDisplay } from './index.js';

// Use 'any' to avoid requiring ink/react type declarations at compile time
/* eslint-disable @typescript-eslint/no-explicit-any */
type InkInstance = any;
type ReactModule = any;
type InkModule = any;

// =============================================================================
// INK RENDERER
// =============================================================================

/**
 * Ink-based renderer for rich terminal UI.
 *
 * Note: This is a stub implementation. When Ink is installed,
 * this would be implemented with React components.
 */
export class InkRenderer implements TUIRenderer {
  private tuiConfig: Required<TUIConfig>;
  private inkInstance: unknown = null;
  private state = {
    messages: [] as Array<{ role: string; content: string }>,
    toolCalls: new Map<string, ToolCallDisplay>(),
    status: null as StatusDisplay | null,
    thinking: '',
    spinner: { visible: false, message: '' },
  };

  constructor(config: TUIConfig = {}) {
    this.tuiConfig = {
      enabled: config.enabled ?? true,
      showStreaming: config.showStreaming ?? true,
      showToolCalls: config.showToolCalls ?? true,
      showThinking: config.showThinking ?? false,
      theme: config.theme ?? 'auto',
      maxPanelHeight: config.maxPanelHeight ?? 20,
    };
  }

  async init(): Promise<void> {
    try {
      // Dynamically import Ink - this will throw if not installed
      // Use variables to prevent TypeScript from trying to resolve modules
      const inkModule = 'ink';
      const reactModule = 'react';
      const ink: InkModule = await import(inkModule);
      const React: ReactModule = await import(reactModule);

      // Create the root component
      const App = this.createAppComponent(React);

      // Render using Ink
      this.inkInstance = ink.render(React.createElement(App)) as InkInstance;
    } catch (error) {
      console.error('Failed to initialize Ink TUI:', error);
      throw error;
    }
  }

  /**
   * Create the main App component.
   * This would be expanded with full React/Ink implementation.
   */
  private createAppComponent(React: ReactModule): ReactModule {
    const self = this;

    return function App() {
      // In a full implementation, this would use:
      // - ink's Box, Text, Newline components
      // - ink-spinner for loading indicators
      // - ink-text-input for user input
      // - useInput for keyboard shortcuts

      return React.createElement('ink-box', {
        flexDirection: 'column',
        children: [
          // Header
          React.createElement('ink-text', { key: 'header', color: 'cyan' }, '🤖 Production Agent'),

          // Messages area
          ...self.state.messages.map((msg, i) =>
            React.createElement('ink-text', {
              key: `msg-${i}`,
              color: msg.role === 'user' ? 'blue' : 'green',
            }, `${msg.role}: ${msg.content}`)
          ),

          // Status bar
          self.state.status && React.createElement('ink-text', {
            key: 'status',
            color: 'gray',
          }, `Mode: ${self.state.status.mode} | Tokens: ${self.state.status.tokens}`),
        ],
      });
    };
  }

  renderUserMessage(message: string): void {
    this.state.messages.push({ role: 'user', content: message });
    this.rerender();
  }

  renderAssistantMessage(content: string, streaming = false): void {
    if (streaming) {
      // For streaming, update the last assistant message or create new
      const last = this.state.messages[this.state.messages.length - 1];
      if (last?.role === 'assistant') {
        last.content += content;
      } else {
        this.state.messages.push({ role: 'assistant', content });
      }
    } else {
      this.state.messages.push({ role: 'assistant', content });
    }
    this.rerender();
  }

  renderToolCall(toolCall: ToolCallDisplay): void {
    this.state.toolCalls.set(toolCall.id, toolCall);
    this.rerender();
  }

  updateToolCallResult(id: string, result: unknown, error?: string): void {
    const toolCall = this.state.toolCalls.get(id);
    if (toolCall) {
      toolCall.status = error ? 'error' : 'success';
      toolCall.result = result;
      toolCall.error = error;
      this.rerender();
    }
  }

  renderThinking(content: string): void {
    this.state.thinking = content;
    this.rerender();
  }

  updateStatus(status: StatusDisplay): void {
    this.state.status = status;
    this.rerender();
  }

  showSpinner(message: string): void {
    this.state.spinner = { visible: true, message };
    this.rerender();
  }

  hideSpinner(): void {
    this.state.spinner = { visible: false, message: '' };
    this.rerender();
  }

  async promptInput(prompt: string): Promise<string> {
    // In full implementation, would use ink-text-input
    const readline = await import('readline');
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });

    return new Promise((resolve) => {
      rl.question(`${prompt} `, (answer) => {
        rl.close();
        resolve(answer);
      });
    });
  }

  showError(error: string): void {
    this.state.messages.push({ role: 'error', content: error });
    this.rerender();
  }

  showSuccess(message: string): void {
    this.state.messages.push({ role: 'success', content: message });
    this.rerender();
  }

  clear(): void {
    this.state.messages = [];
    this.state.toolCalls.clear();
    this.state.thinking = '';
    this.rerender();
  }

  cleanup(): void {
    if (this.inkInstance && typeof (this.inkInstance as { unmount?: () => void }).unmount === 'function') {
      (this.inkInstance as { unmount: () => void }).unmount();
    }
  }

  private rerender(): void {
    // Ink handles re-rendering automatically when state changes
    // In a full implementation, would use React state management
  }

  /**
   * Get the TUI configuration.
   */
  getConfig(): Required<TUIConfig> {
    return this.tuiConfig;
  }
}

// =============================================================================
// COMPONENT STUBS
// =============================================================================

/**
 * These would be full React components when Ink is installed.
 * Showing the structure for reference.
 */

/*
// Message panel component
function MessagePanel({ messages, maxHeight }) {
  return (
    <Box flexDirection="column" height={maxHeight}>
      {messages.map((msg, i) => (
        <Box key={i}>
          <Text color={msg.role === 'user' ? 'blue' : 'green'}>
            {msg.role === 'user' ? '👤' : '🤖'} {msg.content}
          </Text>
        </Box>
      ))}
    </Box>
  );
}

// Tool call panel component
function ToolCallPanel({ toolCalls }) {
  return (
    <Box flexDirection="column" borderStyle="single" borderColor="yellow">
      <Text bold>Tool Calls</Text>
      {Array.from(toolCalls.values()).map(tc => (
        <Box key={tc.id}>
          <Text color={tc.status === 'error' ? 'red' : 'green'}>
            {tc.status === 'running' ? <Spinner /> : statusEmoji[tc.status]} {tc.name}
          </Text>
        </Box>
      ))}
    </Box>
  );
}

// Status bar component
function StatusBar({ status }) {
  if (!status) return null;
  return (
    <Box borderStyle="single" borderColor="gray" paddingX={1}>
      <Text color="gray">
        Mode: {status.mode} | Iter: {status.iteration} |
        Tokens: {status.tokens} | Cost: ${status.cost.toFixed(4)}
      </Text>
    </Box>
  );
}

// Main App component
function App({ renderer }) {
  const [messages, setMessages] = useState([]);
  const [toolCalls, setToolCalls] = useState(new Map());
  const [status, setStatus] = useState(null);
  const [spinner, setSpinner] = useState({ visible: false, message: '' });

  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      renderer.cleanup();
      process.exit(0);
    }
  });

  return (
    <Box flexDirection="column">
      <Box borderStyle="double" borderColor="cyan" paddingX={1}>
        <Text bold color="cyan">🤖 Production Agent</Text>
      </Box>

      <MessagePanel messages={messages} maxHeight={20} />

      {toolCalls.size > 0 && <ToolCallPanel toolCalls={toolCalls} />}

      {spinner.visible && (
        <Box>
          <Spinner /> <Text>{spinner.message}</Text>
        </Box>
      )}

      <StatusBar status={status} />
    </Box>
  );
}
*/
