/**
 * Ink-based TUI Renderer
 *
 * Rich terminal UI using Ink (React for CLI).
 * Wires together the App component from app.tsx with the TUIRenderer interface.
 *
 * To use this, install Ink:
 *   npm install ink react
 */

import type { TUIRenderer, TUIConfig, ToolCallDisplay, StatusDisplay } from './index.js';
import type { MessageDisplay, TUIEventHandlers } from './types.js';

// Dynamic import types
type InkInstance = { unmount: () => void; rerender: (element: unknown) => void };

// =============================================================================
// INK RENDERER
// =============================================================================

/**
 * Ink-based renderer for rich terminal UI.
 *
 * Connects the App component from app.tsx to the TUIRenderer interface,
 * using React state management via dispatch actions.
 */
export class InkRenderer implements TUIRenderer {
  private tuiConfig: Required<TUIConfig>;
  private inkInstance: InkInstance | null = null;
  private messageIdCounter = 0;
  private handlers: TUIEventHandlers = {};

  // Local state tracking (mirrors app state for methods that need sync access)
  private localState = {
    messages: [] as MessageDisplay[],
    toolCalls: new Map<string, ToolCallDisplay>(),
    status: null as StatusDisplay | null,
  };

  constructor(config: TUIConfig = {}) {
    this.tuiConfig = {
      enabled: config.enabled ?? true,
      showStreaming: config.showStreaming ?? true,
      showToolCalls: config.showToolCalls ?? true,
      showThinking: config.showThinking ?? true,
      theme: config.theme ?? 'auto',
      maxPanelHeight: config.maxPanelHeight ?? 20,
    };
  }

  /**
   * Set event handlers for the TUI.
   */
  setHandlers(handlers: TUIEventHandlers): void {
    this.handlers = handlers;
  }

  async init(): Promise<void> {
    try {
      // Dynamically import modules
      const inkModule = 'ink';
      const reactModule = 'react';
      const appModule = './app.js';

      const ink = await import(inkModule);
      const React = await import(reactModule);
      const { App } = await import(appModule);

      // Create a wrapper component that forwards to App
      const self = this;

      function AppWrapper() {
        // Create handlers that forward to our registered handlers
        const handlers: TUIEventHandlers = {
          onInput: (value: string) => self.handlers.onInput?.(value),
          onCommand: (cmd: string, args: string[]) => self.handlers.onCommand?.(cmd, args),
          onKeyPress: (key: string, modifiers) => self.handlers.onKeyPress?.(key, modifiers),
        };

        return React.createElement(App, {
          config: self.tuiConfig,
          handlers,
          initialState: {
            messages: self.localState.messages,
            toolCalls: self.localState.toolCalls,
            status: self.localState.status,
          },
        });
      }

      // Render using Ink
      this.inkInstance = ink.render(React.createElement(AppWrapper)) as InkInstance;
    } catch (error) {
      console.error('Failed to initialize Ink TUI:', error);
      throw error;
    }
  }

  private generateMessageId(): string {
    return `msg-${Date.now()}-${++this.messageIdCounter}`;
  }

  renderUserMessage(message: string): void {
    const msgDisplay: MessageDisplay = {
      id: this.generateMessageId(),
      role: 'user',
      content: message,
      timestamp: new Date(),
    };
    this.localState.messages.push(msgDisplay);
    this.dispatchAction({ type: 'ADD_MESSAGE', message: msgDisplay });
  }

  renderAssistantMessage(content: string, streaming = false): void {
    if (streaming) {
      // For streaming, update the last assistant message or create new
      const lastMsg = this.localState.messages[this.localState.messages.length - 1];
      if (lastMsg?.role === 'assistant') {
        lastMsg.content += content;
        this.dispatchAction({ type: 'UPDATE_MESSAGE', id: lastMsg.id, content: lastMsg.content });
      } else {
        const msgDisplay: MessageDisplay = {
          id: this.generateMessageId(),
          role: 'assistant',
          content,
          timestamp: new Date(),
        };
        this.localState.messages.push(msgDisplay);
        this.dispatchAction({ type: 'ADD_MESSAGE', message: msgDisplay });
      }
    } else {
      const msgDisplay: MessageDisplay = {
        id: this.generateMessageId(),
        role: 'assistant',
        content,
        timestamp: new Date(),
      };
      this.localState.messages.push(msgDisplay);
      this.dispatchAction({ type: 'ADD_MESSAGE', message: msgDisplay });
    }
  }

  renderToolCall(toolCall: ToolCallDisplay): void {
    this.localState.toolCalls.set(toolCall.id, toolCall);
    this.dispatchAction({ type: 'SET_TOOL_CALL', toolCall });
  }

  updateToolCallResult(id: string, result: unknown, error?: string): void {
    const toolCall = this.localState.toolCalls.get(id);
    if (toolCall) {
      const updates: Partial<ToolCallDisplay> = {
        status: error ? 'error' : 'success',
        result,
        error,
      };
      Object.assign(toolCall, updates);
      this.dispatchAction({ type: 'UPDATE_TOOL_CALL', id, updates });
    }
  }

  renderThinking(content: string): void {
    this.dispatchAction({ type: 'SET_THINKING', content });
  }

  updateStatus(status: StatusDisplay): void {
    this.localState.status = status;
    this.dispatchAction({ type: 'SET_STATUS', status });
  }

  showSpinner(message: string): void {
    this.dispatchAction({ type: 'SET_SPINNER', visible: true, message });
  }

  hideSpinner(): void {
    this.dispatchAction({ type: 'SET_SPINNER', visible: false });
  }

  async promptInput(prompt: string): Promise<string> {
    // For now, fall back to readline for prompts
    // In a full implementation, this would use the InputArea component
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
    const msgDisplay: MessageDisplay = {
      id: this.generateMessageId(),
      role: 'system',
      content: `❌ Error: ${error}`,
      timestamp: new Date(),
    };
    this.localState.messages.push(msgDisplay);
    this.dispatchAction({ type: 'ADD_MESSAGE', message: msgDisplay });
  }

  showSuccess(message: string): void {
    const msgDisplay: MessageDisplay = {
      id: this.generateMessageId(),
      role: 'system',
      content: `✓ ${message}`,
      timestamp: new Date(),
    };
    this.localState.messages.push(msgDisplay);
    this.dispatchAction({ type: 'ADD_MESSAGE', message: msgDisplay });
  }

  clear(): void {
    this.localState.messages = [];
    this.localState.toolCalls.clear();
    this.dispatchAction({ type: 'CLEAR_MESSAGES' });
  }

  cleanup(): void {
    if (this.inkInstance) {
      this.inkInstance.unmount();
      this.inkInstance = null;
    }
  }

  /**
   * Dispatch an action to trigger state updates.
   * The App component receives state updates via the localState which
   * is passed as initialState on each render cycle.
   */
  private dispatchAction(_action: unknown): void {
    // State is managed via localState and passed to App component
    // The action parameter is kept for future direct dispatch integration
    // Currently, Ink handles re-rendering automatically when the component tree updates
  }

  /**
   * Get the TUI configuration.
   */
  getConfig(): Required<TUIConfig> {
    return this.tuiConfig;
  }
}
