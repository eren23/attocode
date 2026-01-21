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
} from '../02-provider-abstraction/types.js';

import { stableStringify } from './integrations/index.js';

import type { ToolDescription } from '../03-tool-system/types.js';
import type { ToolRegistry } from '../03-tool-system/registry.js';

import { safeParseJson } from '../tricks/json-utils.js';

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
      toolCalls: response.toolCalls?.map(tc => {
        let args: Record<string, unknown>;
        if (typeof tc.function.arguments === 'string') {
          const result = safeParseJson<Record<string, unknown>>(tc.function.arguments, {
            context: `tool ${tc.function.name}`,
          });
          args = result.success && result.value ? result.value : {};
        } else {
          args = tc.function.arguments;
        }
        return {
          id: tc.id,
          name: tc.function.name,
          arguments: args,
        };
      }),
      usage: response.usage ? {
        inputTokens: response.usage.inputTokens,
        outputTokens: response.usage.outputTokens,
        totalTokens: (response.usage.inputTokens || 0) + (response.usage.outputTokens || 0),
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
 */
export function convertToolsFromRegistry(registry: ToolRegistry): ProductionToolDefinition[] {
  const descriptions = registry.getDescriptions();

  return descriptions.map(desc => ({
    name: desc.name,
    description: desc.description,
    parameters: desc.input_schema as unknown as Record<string, unknown>,
    execute: async (args: Record<string, unknown>) => {
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
import { stdin, stdout } from 'node:process';

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
