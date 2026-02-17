/**
 * Message builder extracted from ProductionAgent.buildMessages().
 *
 * Constructs the system prompt and message array for LLM calls,
 * with support for cache-aware prompt building (Trick P) and
 * budget-aware codebase context selection.
 */

import type { Message, ToolDefinition, AgentState } from '../types.js';
import type { buildConfig } from '../defaults.js';
import type { ModeManager } from '../modes.js';

import type {
  RulesManager,
  SkillManager,
  MemoryManager,
  LearningStore,
  CodebaseContextManager,
  ContextEngineeringManager,
  CacheableContentBlock,
  ComplexityAssessment,
} from '../integrations/index.js';

import {
  buildContextFromChunks,
  generateLightweightRepoMap,
  getEnvironmentFacts,
  formatFactsBlock,
  getThinkingSystemPrompt,
  getScalingGuidance,
} from '../integrations/index.js';

import { createComponentLogger } from '../integrations/utilities/logger.js';

const log = createComponentLogger('MessageBuilder');

// =============================================================================
// DEPS INTERFACE
// =============================================================================

/**
 * Interface describing the private fields that buildMessages needs from
 * the ProductionAgent.  Kept deliberately narrow so the function can be
 * tested in isolation with a lightweight stub.
 */
export interface MessageBuilderDeps {
  // ---- read-only config / core ----
  config: ReturnType<typeof buildConfig>;
  tools: Map<string, ToolDefinition>;
  state: AgentState;

  // ---- nullable integration managers (read) ----
  rules: RulesManager | null;
  skillManager: SkillManager | null;
  memory: MemoryManager | null;
  learningStore: LearningStore | null;
  codebaseContext: CodebaseContextManager | null;
  contextEngineering: ContextEngineeringManager | null;
  modeManager: ModeManager;
  lastComplexityAssessment: ComplexityAssessment | null;

  // ---- mutable fields the builder writes back ----
  codebaseAnalysisTriggered: boolean;
  cacheableSystemBlocks: CacheableContentBlock[] | null;
  lastSystemPromptLength: number;

  // ---- methods the builder delegates to ----
  selectRelevantCodeSync(
    task: string,
    maxTokens: number,
  ): {
    chunks: Array<{ filePath: string; content: string; tokenCount: number; importance: number }>;
    totalTokens: number;
    lspBoostedFiles?: string[];
  };
}

// =============================================================================
// BUILD MESSAGES
// =============================================================================

/**
 * Build the messages array for an LLM call.
 *
 * Uses cache-aware system prompt building (Trick P) when contextEngineering
 * is available, ensuring static content is ordered for optimal KV-cache reuse.
 */
export async function buildMessages(deps: MessageBuilderDeps, task: string): Promise<Message[]> {
  const messages: Message[] = [];

  // Gather all context components
  const rulesContent = deps.rules?.getRulesContent() ?? '';
  const skillsPrompt = deps.skillManager?.getActiveSkillsPrompt() ?? '';
  const memoryContext = deps.memory?.getContextStrings(task) ?? [];

  // Get relevant learnings from past sessions
  const learningsContext =
    deps.learningStore?.getLearningContext({
      query: task,
      maxLearnings: 5,
    }) ?? '';

  // Budget-aware codebase context selection
  let codebaseContextStr = '';
  if (deps.codebaseContext) {
    // Calculate available budget for codebase context
    // Reserve tokens for: rules (~2000), tools (~2500), memory (~1000), conversation (~5000)
    const reservedTokens = 10500;
    const maxContextTokens = (deps.config.maxContextTokens ?? 80000) - reservedTokens;
    const codebaseBudget = Math.min(maxContextTokens * 0.3, 15000); // Up to 30% or 15K tokens

    // Synchronous analysis on first system prompt build so context is available immediately
    if (!deps.codebaseContext.getRepoMap() && !deps.codebaseAnalysisTriggered) {
      deps.codebaseAnalysisTriggered = true;
      try {
        await deps.codebaseContext.analyze();
      } catch {
        // non-fatal -- agent can still work without codebase context
      }
    }

    // Get repo map AFTER analysis so we have fresh data on first prompt
    const repoMap = deps.codebaseContext.getRepoMap();
    if (repoMap) {
      try {
        const selection = deps.selectRelevantCodeSync(task, codebaseBudget);
        if (selection.chunks.length > 0) {
          codebaseContextStr = buildContextFromChunks(selection.chunks, {
            includeFilePaths: true,
            includeSeparators: true,
            maxTotalTokens: codebaseBudget,
          });
        } else {
          // Fallback: lightweight repo map when task-specific selection finds nothing
          codebaseContextStr = generateLightweightRepoMap(repoMap, codebaseBudget);
        }
      } catch {
        // Selection error -- skip
      }
    }
  }

  // Build tool descriptions
  let toolDescriptions = '';
  if (deps.tools.size > 0) {
    const toolLines: string[] = [];
    for (const tool of deps.tools.values()) {
      toolLines.push(`- ${tool.name}: ${tool.description}`);
    }
    toolDescriptions = toolLines.join('\n');
  }

  // Add MCP tool summaries
  if (deps.config.mcpToolSummaries && deps.config.mcpToolSummaries.length > 0) {
    const mcpLines = deps.config.mcpToolSummaries.map((s) => `- ${s.name}: ${s.description}`);
    if (toolDescriptions) {
      toolDescriptions += '\n\nMCP tools (call directly, they auto-load):\n' + mcpLines.join('\n');
    } else {
      toolDescriptions = 'MCP tools (call directly, they auto-load):\n' + mcpLines.join('\n');
    }
  }

  // Build system prompt using cache-aware builder if available (Trick P)
  // Combine memory, learnings, codebase context, and environment facts
  const combinedContextParts = [
    // Environment facts -- temporal/platform grounding (prevents stale date hallucinations)
    formatFactsBlock(getEnvironmentFacts()),
    ...(memoryContext.length > 0 ? memoryContext : []),
    ...(learningsContext ? [learningsContext] : []),
    ...(codebaseContextStr ? [`\n## Relevant Code\n${codebaseContextStr}`] : []),
  ];

  // Inject thinking directives and scaling guidance for non-simple tasks
  if (deps.lastComplexityAssessment) {
    const thinkingPrompt = getThinkingSystemPrompt(deps.lastComplexityAssessment.tier);
    if (thinkingPrompt) {
      combinedContextParts.push(thinkingPrompt);
    }
    if (deps.lastComplexityAssessment.tier !== 'simple') {
      combinedContextParts.push(getScalingGuidance(deps.lastComplexityAssessment));
    }
  }

  const combinedContext = combinedContextParts.join('\n');

  const promptOptions = {
    rules: rulesContent + (skillsPrompt ? '\n\n' + skillsPrompt : ''),
    tools: toolDescriptions,
    memory: combinedContext.length > 0 ? combinedContext : undefined,
    dynamic: {
      mode: deps.modeManager?.getMode() ?? 'default',
    },
  };

  if (deps.contextEngineering) {
    // Build cache-aware system prompt with cache_control markers (Improvement P1).
    // Store structured blocks for callLLM() to inject as MessageWithContent.
    // The string version is still used for token estimation and debugging.
    const cacheableBlocks = deps.contextEngineering.buildCacheableSystemPrompt(promptOptions);

    // Safety check: ensure we have content (empty array = no cache context configured)
    if (cacheableBlocks.length === 0 || cacheableBlocks.every((b) => b.text.trim().length === 0)) {
      deps.cacheableSystemBlocks = null;
      messages.push({
        role: 'system',
        content: deps.config.systemPrompt || 'You are a helpful AI assistant.',
      });
    } else {
      // Store cacheable blocks for provider injection
      deps.cacheableSystemBlocks = cacheableBlocks;
      // Push a regular string Message for backward compatibility (token estimation, etc.)
      const flatPrompt = cacheableBlocks.map((b) => b.text).join('');
      messages.push({ role: 'system', content: flatPrompt });
    }
  } else {
    // Fallback: manual concatenation (original behavior) -- no cache markers
    deps.cacheableSystemBlocks = null;
    let systemPrompt = deps.config.systemPrompt;
    if (rulesContent) systemPrompt += '\n\n' + rulesContent;
    if (skillsPrompt) systemPrompt += skillsPrompt;
    if (combinedContext.length > 0) {
      systemPrompt += '\n\nRelevant context:\n' + combinedContext;
    }
    if (toolDescriptions) {
      systemPrompt += '\n\nAvailable tools:\n' + toolDescriptions;
    }

    // Safety check: ensure system prompt is not empty
    if (!systemPrompt || systemPrompt.trim().length === 0) {
      log.warn('Empty system prompt detected, using fallback');
      systemPrompt = deps.config.systemPrompt || 'You are a helpful AI assistant.';
    }

    messages.push({ role: 'system', content: systemPrompt });
  }

  // Add existing conversation
  for (const msg of deps.state.messages) {
    if (msg.role !== 'system') {
      messages.push(msg);
    }
  }

  // Add current task
  messages.push({ role: 'user', content: task });

  // Track system prompt length for context % estimation
  const sysMsg = messages.find((m) => m.role === 'system');
  if (sysMsg) {
    const content =
      typeof sysMsg.content === 'string' ? sysMsg.content : JSON.stringify(sysMsg.content);
    deps.lastSystemPromptLength = content.length;
  }

  return messages;
}
