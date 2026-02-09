/**
 * Adapters to bridge different interfaces in the production agent.
 *
 * The production agent has its own type definitions that differ from
 * the earlier lessons. These adapters allow seamless integration.
 */

import type {
  LLMProvider as ProductionLLMProvider,
  ChatOptions as ProductionChatOptions,
  ChatResponse as ProductionChatResponse,
  ToolDefinition as ProductionToolDefinition,
  Message as ProductionMessage,
} from './types.js';

import type {
  LLMProviderWithTools,
  ToolDefinitionSchema,
} from './providers/types.js';

import { stableStringify } from './integrations/index.js';

import type { ToolDescription } from './tools/types.js';
import type { ToolRegistry } from './tools/registry.js';

import { safeParseJson } from './tricks/json-utils.js';

// =============================================================================
// PROVIDER ADAPTER
// =============================================================================

/**
 * Adapts LLMProviderWithTools (lesson 02) to ProductionLLMProvider (lesson 25).
 *
 * Key differences:
 * - Lesson 02: chatWithTools(messages, { tools, tool_choice, model })
 * - Lesson 25: chat(messages, { tools, model }) where tools are ToolDefinition[]
 */
export class ProviderAdapter implements ProductionLLMProvider {
  constructor(
    private provider: LLMProviderWithTools,
    private defaultModel?: string
  ) {}

  async chat(
    messages: ProductionMessage[],
    options?: ProductionChatOptions
  ): Promise<ProductionChatResponse> {
    // Convert ProductionMessage[] to provider message format
    const providerMessages = messages.map(m => ({
      role: m.role as 'system' | 'user' | 'assistant' | 'tool',
      content: m.content,
      tool_calls: m.toolCalls?.map(tc => ({
        id: tc.id,
        type: 'function' as const,
        function: {
          name: tc.name,
          arguments: stableStringify(tc.arguments),
        },
      })),
      tool_call_id: m.toolCallId,
      name: m.toolCallId ? messages.find(msg =>
        msg.toolCalls?.some(tc => tc.id === m.toolCallId)
      )?.toolCalls?.find(tc => tc.id === m.toolCallId)?.name : undefined,
    }));

    // Convert ProductionToolDefinition[] to ToolDefinitionSchema[]
    const toolSchemas: ToolDefinitionSchema[] | undefined = options?.tools?.map(t => ({
      type: 'function' as const,
      function: {
        name: t.name,
        description: t.description,
        parameters: t.parameters,
      },
    }));

    const model = options?.model || this.defaultModel;

    // Call the underlying provider
    const response = await this.provider.chatWithTools(providerMessages, {
      tools: toolSchemas,
      tool_choice: toolSchemas && toolSchemas.length > 0 ? 'auto' : undefined,
      model,
      maxTokens: options?.maxTokens,
    });

    // Convert response to ProductionChatResponse
    return {
      content: response.content,
      thinking: response.thinking,
      stopReason: response.stopReason,
      toolCalls: response.toolCalls?.map(tc => {
        let args: Record<string, unknown>;
        let parseError: string | undefined;
        if (typeof tc.function.arguments === 'string') {
          const result = safeParseJson<Record<string, unknown>>(tc.function.arguments, {
            context: `tool ${tc.function.name}`,
          });
          if (!result.success) {
            console.warn(
              `[ProviderAdapter] Failed to parse tool call arguments for ${tc.function.name}: ${result.error}. ` +
              `First 100 chars: ${tc.function.arguments.slice(0, 100)}... ` +
              `Last 50 chars: ...${tc.function.arguments.slice(-50)}`
            );
            parseError = `Failed to parse arguments as JSON. Raw text (first 200 chars): ${tc.function.arguments.slice(0, 200)}`;
          }
          args = result.success && result.value ? result.value : {};
        } else {
          args = tc.function.arguments;
        }
        return {
          id: tc.id,
          name: tc.function.name,
          arguments: args,
          ...(parseError ? { parseError } : {}),
        };
      }),
      usage: response.usage ? {
        inputTokens: response.usage.inputTokens,
        outputTokens: response.usage.outputTokens,
        totalTokens: (response.usage.inputTokens || 0) + (response.usage.outputTokens || 0),
        cacheReadTokens: response.usage.cacheReadTokens ?? response.usage.cachedTokens,
        cacheWriteTokens: response.usage.cacheWriteTokens,
        cost: response.usage.cost,
      } : undefined,
      model: model,
    };
  }
}

// =============================================================================
// TOOL CONVERTER
// =============================================================================

/**
 * Converts tools from ToolRegistry (lesson 03) to ProductionToolDefinition[] (lesson 25).
 * @param registry - Tool registry to convert from
 * @param options - Optional configuration
 * @param options.defaultTimeout - Default timeout for bash commands (ms). Overrides tool defaults.
 */
export function convertToolsFromRegistry(
  registry: ToolRegistry,
  options?: { defaultTimeout?: number },
): ProductionToolDefinition[] {
  const descriptions = registry.getDescriptions();

  return descriptions.map(desc => ({
    name: desc.name,
    description: desc.description,
    parameters: desc.input_schema as unknown as Record<string, unknown>,
    execute: async (args: Record<string, unknown>) => {
      // Inject default timeout for bash tool if not specified by the model
      if (options?.defaultTimeout && desc.name === 'bash' && !args.timeout) {
        args = { ...args, timeout: options.defaultTimeout };
      }
      const result = await registry.execute(desc.name, args);
      if (result.success) {
        return result.output;
      } else {
        throw new Error(result.output);
      }
    },
    dangerLevel: categorizeToolDanger(desc.name),
  }));
}

/**
 * Converts a single ToolDescription to ProductionToolDefinition.
 */
export function convertTool(
  desc: ToolDescription,
  executor: (args: Record<string, unknown>) => Promise<unknown>
): ProductionToolDefinition {
  return {
    name: desc.name,
    description: desc.description,
    parameters: desc.input_schema as unknown as Record<string, unknown>,
    execute: executor,
    dangerLevel: categorizeToolDanger(desc.name),
  };
}

/**
 * Categorize tool danger level based on name.
 */
function categorizeToolDanger(toolName: string): 'safe' | 'moderate' | 'dangerous' {
  const dangerous = ['bash', 'write_file', 'edit_file', 'delete_file'];
  const moderate = ['list_files', 'glob'];

  if (dangerous.includes(toolName)) return 'dangerous';
  if (moderate.includes(toolName)) return 'moderate';
  return 'safe';
}

// =============================================================================
// APPROVAL HANDLER FOR REPL
// =============================================================================

import * as readline from 'node:readline/promises';

/**
 * Creates an interactive approval handler for the REPL.
 * Unlike the broken auto-approve, this actually asks the user.
 */
export function createInteractiveApprovalHandler(
  rl: readline.Interface
): (request: { id: string; action: string; tool?: string; args?: Record<string, unknown>; risk: string; context: string }) => Promise<{ approved: boolean; reason?: string }> {
  return async (request) => {
    const colors = {
      reset: '\x1b[0m',
      yellow: '\x1b[33m',
      cyan: '\x1b[36m',
      dim: '\x1b[2m',
    };

    console.log(`\n${colors.yellow}⚠️  Approval Required${colors.reset}`);
    console.log(`${colors.cyan}Action:${colors.reset} ${request.action}`);
    if (request.tool) {
      console.log(`${colors.cyan}Tool:${colors.reset} ${request.tool}`);
    }
    if (request.args) {
      console.log(`${colors.cyan}Args:${colors.reset} ${JSON.stringify(request.args, null, 2)}`);
    }
    console.log(`${colors.cyan}Risk:${colors.reset} ${request.risk}`);
    console.log(`${colors.dim}${request.context}${colors.reset}`);

    const answer = await rl.question(`\n${colors.yellow}Approve? (y/n/reason): ${colors.reset}`);
    const trimmed = answer.trim().toLowerCase();

    if (trimmed === 'y' || trimmed === 'yes') {
      return { approved: true };
    } else if (trimmed === 'n' || trimmed === 'no') {
      return { approved: false, reason: 'User denied' };
    } else if (trimmed.startsWith('n ')) {
      return { approved: false, reason: trimmed.slice(2) };
    } else {
      // Treat any other input as denial with reason
      return { approved: false, reason: trimmed || 'User denied' };
    }
  };
}

// =============================================================================
// APPROVAL HANDLER FOR TUI
// =============================================================================

import type { ApprovalRequest, ApprovalResponse } from './types.js';

/**
 * TUI Approval Bridge
 *
 * Manages the communication between the agent's approval system and the TUI.
 * The bridge is created before the agent, and then connected to TUI callbacks
 * once the TUI component mounts.
 */
export interface TUIApprovalBridge {
  /** The approval handler to pass to the agent config */
  handler: (request: ApprovalRequest) => Promise<ApprovalResponse>;

  /** Connect TUI callbacks after TUI mounts */
  connect: (callbacks: {
    onRequest: (request: ApprovalRequest) => void;
  }) => void;

  /** Resolve the current pending approval */
  resolve: (response: ApprovalResponse) => void;

  /** Check if there's a pending approval */
  hasPending: () => boolean;

  /** Check if TUI is connected and ready to handle approvals */
  isConnected: () => boolean;
}

/**
 * Configuration for the TUI approval bridge.
 */
export interface TUIApprovalBridgeConfig {
  /**
   * Timeout for approval requests in milliseconds.
   * If an approval is not resolved within this time, it will be automatically denied.
   * Default: 120000 (2 minutes)
   */
  timeout?: number;
  /**
   * Callback when a timeout occurs, for logging/telemetry.
   */
  onTimeout?: (request: ApprovalRequest) => void;
}

/**
 * Creates a TUI approval bridge that enables communication between
 * the agent's human-in-loop system and the TUI's approval dialog.
 *
 * Usage:
 * 1. Create the bridge before creating the agent
 * 2. Pass bridge.handler to the agent's humanInLoop.approvalHandler
 * 3. Pass bridge to TUIApp props
 * 4. TUIApp calls bridge.connect() with its callbacks on mount
 * 5. When approval is needed, bridge calls onRequest callback
 * 6. TUIApp shows dialog, user responds, TUIApp calls bridge.resolve()
 *
 * Safety features:
 * - 2-minute timeout (configurable) - prevents agent from hanging if TUI crashes
 * - Timeout results in denial (fail-safe default)
 * - Logs timeout events for debugging
 */
export function createTUIApprovalBridge(config: TUIApprovalBridgeConfig = {}): TUIApprovalBridge {
  const DEFAULT_TIMEOUT_MS = 120000; // 2 minutes
  const timeoutMs = config.timeout ?? DEFAULT_TIMEOUT_MS;

  let pendingResolve: ((response: ApprovalResponse) => void) | null = null;
  let pendingTimeoutId: ReturnType<typeof setTimeout> | null = null;
  let onRequestCallback: ((request: ApprovalRequest) => void) | null = null;
  let connected = false;

  const clearPendingTimeout = () => {
    if (pendingTimeoutId) {
      clearTimeout(pendingTimeoutId);
      pendingTimeoutId = null;
    }
  };

  const handler = async (request: ApprovalRequest): Promise<ApprovalResponse> => {
    return new Promise((resolve) => {
      pendingResolve = resolve;

      if (onRequestCallback && connected) {
        // TUI is connected, show dialog
        onRequestCallback(request);

        // Set up timeout - deny if not resolved within the timeout period
        pendingTimeoutId = setTimeout(() => {
          if (pendingResolve) {
            console.warn(`[TUI Approval] Timeout after ${timeoutMs}ms - denying operation for safety`);
            config.onTimeout?.(request);
            pendingResolve({
              approved: false,
              reason: `Approval timed out after ${Math.round(timeoutMs / 1000)}s - operation denied for safety`,
            });
            pendingResolve = null;
            pendingTimeoutId = null;
          }
        }, timeoutMs);
      } else {
        // TUI not connected yet - BLOCK dangerous operations instead of auto-approving
        // This is a safety fallback to prevent operations when the approval system isn't ready
        console.warn('[TUI Approval] No TUI connected - blocking operation for safety');
        resolve({ approved: false, reason: 'Approval system not ready - TUI not connected' });
        pendingResolve = null;
      }
    });
  };

  const connect = (callbacks: { onRequest: (request: ApprovalRequest) => void }) => {
    onRequestCallback = callbacks.onRequest;
    connected = true;
  };

  const resolve = (response: ApprovalResponse) => {
    clearPendingTimeout();
    if (pendingResolve) {
      pendingResolve(response);
      pendingResolve = null;
    }
  };

  const hasPending = () => pendingResolve !== null;

  const isConnected = () => connected;

  return { handler, connect, resolve, hasPending, isConnected };
}
