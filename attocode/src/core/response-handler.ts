/**
 * Response Handler Module (Phase 2.1)
 *
 * Extracted from ProductionAgent.callLLM().
 * Handles system prompt building for cache control, provider.chat() calls,
 * usage recording, routing, and tracing.
 */

import type {
  Message,
  ChatResponse,
} from '../types.js';

import type { AgentContext } from './types.js';
import type { MessageWithContent } from '../providers/types.js';
import { estimateTokenCount } from '../integrations/utilities/token-estimate.js';

import { createComponentLogger } from '../integrations/utilities/logger.js';

const log = createComponentLogger('ResponseHandler');

/**
 * Call the LLM with routing and observability.
 * Replaces ProductionAgent.callLLM() — extracted as a standalone function
 * that receives AgentContext instead of using `this`.
 */
export async function callLLM(
  messages: Message[],
  ctx: AgentContext,
): Promise<ChatResponse> {
  const spanId = ctx.observability?.tracer?.startSpan('llm.call');

  ctx.emit({ type: 'llm.start', model: ctx.config.model || 'default' });

  // Prompt caching: Replace system message with structured content for Anthropic models
  const configModel = ctx.config.model || 'default';
  const isAnthropicModel = configModel.startsWith('anthropic/') || configModel.startsWith('claude-');
  let providerMessages: (Message | MessageWithContent)[] = messages;
  if (isAnthropicModel && ctx.cacheableSystemBlocks && ctx.cacheableSystemBlocks.length > 0) {
    providerMessages = messages.map((m, i) => {
      if (i === 0 && m.role === 'system') {
        return {
          role: 'system' as const,
          content: ctx.cacheableSystemBlocks!,
        } as MessageWithContent;
      }
      return m;
    });
  }

  // Emit context insight for verbose feedback
  const estimatedTokens = messages.reduce((sum, m) => {
    const content = typeof m.content === 'string' ? m.content : JSON.stringify(m.content);
    return sum + Math.ceil(content.length / 3.5);
  }, 0);
  const contextLimit = ctx.getMaxContextTokens();
  ctx.emit({
    type: 'insight.context',
    currentTokens: estimatedTokens,
    maxTokens: contextLimit,
    messageCount: messages.length,
    percentUsed: Math.round((estimatedTokens / contextLimit) * 100),
  });

  const startTime = Date.now();
  const requestId = `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  // Debug: Log message count and structure
  if (process.env.DEBUG_LLM) {
    log.debug('Sending messages to LLM', { messageCount: messages.length });
    messages.forEach((m, i) => {
      log.debug('Message detail', { index: i, role: m.role, preview: m.content?.slice(0, 50) });
    });
  }

  // Validate messages are not empty
  if (!messages || messages.length === 0) {
    throw new Error('No messages to send to LLM');
  }

  // Record LLM request for tracing
  const model = ctx.config.model || 'default';
  const provider = (ctx.config.provider as { name?: string })?.name || 'unknown';
  ctx.traceCollector?.record({
    type: 'llm.request',
    data: {
      requestId,
      model,
      provider,
      messages: messages.map(m => ({
        role: m.role as 'system' | 'user' | 'assistant' | 'tool',
        content: m.content,
        toolCallId: m.toolCallId,
        toolCalls: m.toolCalls?.map(tc => ({
          id: tc.id,
          name: tc.name,
          arguments: tc.arguments,
        })),
      })),
      tools: Array.from(ctx.tools.values()).map(t => ({
        name: t.name,
        description: t.description,
        parametersSchema: t.parameters,
      })),
      parameters: {
        maxTokens: ctx.config.maxTokens,
        temperature: ctx.config.temperature,
      },
    },
  });

  // Pause duration budget during LLM call
  ctx.economics?.pauseDuration();

  try {
    let response: ChatResponse;
    let actualModel = model;

    // Use routing if enabled
    if (ctx.routing) {
      const complexity = ctx.routing.estimateComplexity(messages[messages.length - 1]?.content || '');
      const routingContext = {
        task: messages[messages.length - 1]?.content || '',
        complexity,
        hasTools: ctx.tools.size > 0,
        hasImages: false,
        taskType: 'general',
        estimatedTokens: messages.reduce((sum, m) => sum + estimateTokenCount(m.content), 0),
      };

      const result = await ctx.routing.executeWithFallback(providerMessages, routingContext);
      response = result.response;
      actualModel = result.model;

      // Emit routing insight
      ctx.emit({
        type: 'insight.routing',
        model: actualModel,
        reason: actualModel !== model ? 'Routed based on complexity' : 'Default model',
        complexity: complexity <= 0.3 ? 'low' : complexity <= 0.7 ? 'medium' : 'high',
      });

      // Emit decision transparency event
      ctx.emit({
        type: 'decision.routing',
        model: actualModel,
        reason: actualModel !== model
          ? `Complexity ${(complexity * 100).toFixed(0)}% - using ${actualModel}`
          : 'Default model for current task',
        alternatives: actualModel !== model
          ? [{ model, rejected: 'complexity threshold exceeded' }]
          : undefined,
      });

      // Enhanced tracing: Record routing decision
      ctx.traceCollector?.record({
        type: 'decision',
        data: {
          type: 'routing',
          decision: `Selected model: ${actualModel}`,
          outcome: 'allowed',
          reasoning: actualModel !== model
            ? `Task complexity ${(complexity * 100).toFixed(0)}% exceeded threshold - routed to ${actualModel}`
            : `Default model ${model} suitable for task complexity ${(complexity * 100).toFixed(0)}%`,
          factors: [
            { name: 'complexity', value: complexity, weight: 0.8 },
            { name: 'hasTools', value: routingContext.hasTools, weight: 0.1 },
            { name: 'taskType', value: routingContext.taskType, weight: 0.1 },
          ],
          alternatives: actualModel !== model
            ? [{ option: model, reason: 'complexity threshold exceeded', rejected: true }]
            : undefined,
          confidence: 0.9,
        },
      });
    } else {
      response = await ctx.provider.chat(providerMessages, {
        model: ctx.config.model,
        tools: Array.from(ctx.tools.values()),
      });
    }

    const duration = Date.now() - startTime;

    // Debug cache stats
    if (process.env.DEBUG_CACHE) {
      const cr = response.usage?.cacheReadTokens ?? 0;
      const cw = response.usage?.cacheWriteTokens ?? 0;
      const inp = response.usage?.inputTokens ?? 0;
      const hitRate = inp > 0 ? ((cr / inp) * 100).toFixed(1) : '0.0';
      log.debug('Cache stats', { model: actualModel, read: cr, write: cw, input: inp, hitRate: `${hitRate}%` });
    }

    // Record LLM response for tracing
    ctx.traceCollector?.record({
      type: 'llm.response',
      data: {
        requestId,
        content: response.content || '',
        toolCalls: response.toolCalls?.map(tc => ({
          id: tc.id,
          name: tc.name,
          arguments: tc.arguments,
        })),
        stopReason: response.stopReason === 'end_turn' ? 'end_turn'
          : response.stopReason === 'tool_use' ? 'tool_use'
          : response.stopReason === 'max_tokens' ? 'max_tokens'
          : 'stop_sequence',
        usage: {
          inputTokens: response.usage?.inputTokens || 0,
          outputTokens: response.usage?.outputTokens || 0,
          cacheReadTokens: response.usage?.cacheReadTokens,
          cacheWriteTokens: response.usage?.cacheWriteTokens,
          cost: response.usage?.cost,
        },
        durationMs: duration,
      },
    });

    // Record thinking blocks if present
    if (response.thinking) {
      ctx.traceCollector?.record({
        type: 'llm.thinking',
        data: {
          requestId,
          content: response.thinking,
          summarized: response.thinking.length > 10000,
          originalLength: response.thinking.length,
          durationMs: duration,
        },
      });
    }

    // Record metrics
    ctx.observability?.metrics?.recordLLMCall(
      response.usage?.inputTokens || 0,
      response.usage?.outputTokens || 0,
      duration,
      actualModel,
      response.usage?.cost
    );

    ctx.state.metrics.llmCalls++;
    ctx.state.metrics.inputTokens += response.usage?.inputTokens || 0;
    ctx.state.metrics.outputTokens += response.usage?.outputTokens || 0;
    ctx.state.metrics.totalTokens = ctx.state.metrics.inputTokens + ctx.state.metrics.outputTokens;

    ctx.emit({ type: 'llm.complete', response });

    // Emit token usage insight
    if (response.usage) {
      ctx.emit({
        type: 'insight.tokens',
        inputTokens: response.usage.inputTokens,
        outputTokens: response.usage.outputTokens,
        cacheReadTokens: response.usage.cacheReadTokens,
        cacheWriteTokens: response.usage.cacheWriteTokens,
        cost: response.usage.cost,
        model: actualModel,
      });
    }

    ctx.observability?.tracer?.endSpan(spanId);

    return response;
  } catch (err) {
    const error = err instanceof Error ? err : new Error(String(err));
    ctx.observability?.tracer?.recordError(error);
    ctx.observability?.tracer?.endSpan(spanId);
    throw error;
  } finally {
    // Resume duration budget after LLM call
    ctx.economics?.resumeDuration();
  }
}
