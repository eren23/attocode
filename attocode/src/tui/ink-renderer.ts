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

// Action type for dispatching to React state
type AppAction =
  | { type: 'ADD_MESSAGE'; message: MessageDisplay }
  | { type: 'UPDATE_MESSAGE'; id: string; content: string }
  | { type: 'SET_TOOL_CALL'; toolCall: ToolCallDisplay }
  | { type: 'UPDATE_TOOL_CALL'; id: string; updates: Partial<ToolCallDisplay> }
  | { type: 'SET_STATUS'; status: StatusDisplay | null }
  | { type: 'SET_THINKING'; content: string }
  | { type: 'SET_SPINNER'; visible: boolean; message?: string }
  | { type: 'SET_DIALOG'; dialog: unknown }
  | { type: 'TOGGLE_COMMAND_PALETTE' }
  | { type: 'SET_COMMAND_QUERY'; query: string }
  | { type: 'CLEAR_MESSAGES' }
  | { type: 'SET_FOCUS'; target: 'input' | 'messages' | 'tools' | 'sidebar' }
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'SET_SESSIONS'; sessions: unknown[] }
  | { type: 'SET_ACTIVE_SESSION'; sessionId: string | null };

// Type for the dispatch function ref
type DispatchFn = (action: AppAction) => void;

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

  // Ref to dispatch function set by App component
  private dispatchRef: DispatchFn | null = null;

  // Batching for rapid updates
  private pendingActions: AppAction[] = [];
  private batchTimeout: ReturnType<typeof setTimeout> | null = null;
  private batchDelayMs = 16; // ~60fps

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

      // Create a wrapper component that forwards to App and captures dispatch
      const self = this;

      function AppWrapper() {
        // Create handlers that forward to our registered handlers
        const handlers: TUIEventHandlers = {
          onInput: (value: string) => self.handlers.onInput?.(value),
          onCommand: (cmd: string, args: string[]) => self.handlers.onCommand?.(cmd, args),
          onKeyPress: (key: string, modifiers) => self.handlers.onKeyPress?.(key, modifiers),
          onSessionSwitch: (sessionId: string) => self.handlers.onSessionSwitch?.(sessionId),
        };

        return React.createElement(App, {
          config: self.tuiConfig,
          handlers,
          initialState: {
            messages: self.localState.messages,
            toolCalls: self.localState.toolCalls,
            status: self.localState.status,
          },
          // Pass ref setter for dispatch function
          onDispatchReady: (dispatch: DispatchFn) => {
            self.dispatchRef = dispatch;
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
   * Uses batching to prevent flickering from rapid updates.
   */
  private dispatchAction(action: AppAction): void {
    // If no dispatch ref yet, queue the action
    if (!this.dispatchRef) {
      this.pendingActions.push(action);
      return;
    }

    // Flush any pending actions first
    if (this.pendingActions.length > 0) {
      for (const pending of this.pendingActions) {
        this.dispatchRef(pending);
      }
      this.pendingActions = [];
    }

    // Batch rapid updates to reduce flicker
    this.pendingActions.push(action);

    if (!this.batchTimeout) {
      this.batchTimeout = setTimeout(() => {
        if (this.dispatchRef) {
          for (const pending of this.pendingActions) {
            this.dispatchRef(pending);
          }
        }
        this.pendingActions = [];
        this.batchTimeout = null;
      }, this.batchDelayMs);
    }
  }

  /**
   * Flush any pending batched actions immediately.
   * Call this before operations that need synchronous state.
   */
  flushPendingActions(): void {
    if (this.batchTimeout) {
      clearTimeout(this.batchTimeout);
      this.batchTimeout = null;
    }
    if (this.dispatchRef && this.pendingActions.length > 0) {
      for (const pending of this.pendingActions) {
        this.dispatchRef(pending);
      }
      this.pendingActions = [];
    }
  }

  /**
   * Get the TUI configuration.
   */
  getConfig(): Required<TUIConfig> {
    return this.tuiConfig;
  }
}
