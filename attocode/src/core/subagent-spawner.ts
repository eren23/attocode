/**
 * Subagent Spawner Module (Phase 2.1)
 *
 * Extracted from ProductionAgent.spawnAgent(), getSubagentBudget(),
 * and spawnAgentsParallel(). Handles the full subagent lifecycle:
 * config, budget, delegation, timeout, cleanup.
 *
 * Uses SubAgentFactory to create subagent instances without importing
 * ProductionAgent directly — avoids circular dependencies.
 */

import type {
  SandboxConfig,
} from '../types.js';

import type { AgentContext, AgentContextMutators, SubAgentFactory } from './types.js';
import type { SpawnConstraints } from '../tools/agent.js';

import {
  getSubagentTimeout,
  getSubagentMaxIterations,
} from '../defaults.js';

import {
  calculateTaskSimilarity,
  SUBAGENT_PLAN_MODE_ADDITION,
} from '../modes.js';

import {
  SUBAGENT_BUDGET,
  filterToolsForAgent,
  isCancellationError,
  CancellationError,
  createLinkedToken,
  createGracefulTimeout,
  race,
  createDynamicBudgetPool,
  buildDelegationPrompt,
  createMinimalDelegationSpec,
  getSubagentQualityPrompt,
  ToolRecommendationEngine,
  createSubagentSupervisor,
  createSubagentHandle,
  type SpawnResult,
  type StructuredClosureReport,
  type SwarmConfig,
  type ExecutionBudget,
  type SubagentOutput,
} from '../integrations/index.js';

import {
  mergeApprovalScopeWithProfile,
  resolvePolicyProfile,
} from '../integrations/policy-engine.js';

/** Duplicate spawn prevention window (60 seconds). */
const SPAWN_DEDUP_WINDOW_MS = 60000;

/**
 * Parse a structured closure report from a subagent's text response.
 * The subagent may have produced JSON in response to a TIMEOUT_WRAPUP_PROMPT.
 */
export function parseStructuredClosureReport(
  text: string,
  defaultExitReason: StructuredClosureReport['exitReason'],
  fallbackTask?: string,
): StructuredClosureReport | undefined {
  if (!text) {
    if (fallbackTask) {
      return {
        findings: [],
        actionsTaken: [],
        failures: ['Timeout before producing structured summary'],
        remainingWork: [fallbackTask],
        exitReason: 'timeout_hard',
      };
    }
    return undefined;
  }

  try {
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      if (parsed.findings || parsed.actionsTaken || parsed.failures || parsed.remainingWork) {
        return {
          findings: Array.isArray(parsed.findings) ? parsed.findings : [],
          actionsTaken: Array.isArray(parsed.actionsTaken) ? parsed.actionsTaken : [],
          failures: Array.isArray(parsed.failures) ? parsed.failures : [],
          remainingWork: Array.isArray(parsed.remainingWork) ? parsed.remainingWork : [],
          exitReason: defaultExitReason,
          suggestedNextSteps: Array.isArray(parsed.suggestedNextSteps) ? parsed.suggestedNextSteps : undefined,
        };
      }
    }
  } catch {
    // JSON parse failed — fall through to fallback
  }

  if (defaultExitReason !== 'completed') {
    return {
      findings: [text.slice(0, 500)],
      actionsTaken: [],
      failures: ['Did not produce structured JSON summary'],
      remainingWork: fallbackTask ? [fallbackTask] : [],
      exitReason: defaultExitReason === 'timeout_graceful' ? 'timeout_hard' : defaultExitReason,
    };
  }

  return undefined;
}

/**
 * Get budget for a subagent, using the pooled budget when available.
 * Falls back to the static SUBAGENT_BUDGET if no pool is configured.
 */
export function getSubagentBudget(
  ctx: AgentContext,
  agentName: string,
  constraints?: { maxTokens?: number },
): { budget: Partial<ExecutionBudget>; allocationId: string | null } {
  if (constraints?.maxTokens) {
    return {
      budget: { ...SUBAGENT_BUDGET, maxTokens: constraints.maxTokens },
      allocationId: null,
    };
  }

  if (ctx.budgetPool) {
    const allocationId = `${agentName}-${Date.now()}`;
    const allocation = ctx.budgetPool.reserve(allocationId);
    if (allocation) {
      return {
        budget: {
          ...SUBAGENT_BUDGET,
          maxTokens: allocation.tokenBudget,
          softTokenLimit: Math.floor(allocation.tokenBudget * 0.7),
          maxCost: allocation.costBudget,
        },
        allocationId,
      };
    }
    return {
      budget: {
        ...SUBAGENT_BUDGET,
        maxTokens: 5000,
        softTokenLimit: 3000,
        maxCost: 0.01,
      },
      allocationId: null,
    };
  }

  return { budget: SUBAGENT_BUDGET, allocationId: null };
}

/**
 * Spawn a single subagent to handle a delegated task.
 * Extracted from ProductionAgent.spawnAgent().
 */
export async function spawnAgent(
  agentName: string,
  task: string,
  ctx: AgentContext,
  createSubAgent: SubAgentFactory,
  constraints?: SpawnConstraints,
): Promise<SpawnResult> {
  if (!ctx.agentRegistry) {
    return {
      success: false,
      output: 'Agent registry not initialized',
      metrics: { tokens: 0, duration: 0, toolCalls: 0 },
    };
  }

  const agentDef = ctx.agentRegistry.getAgent(agentName);
  if (!agentDef) {
    return {
      success: false,
      output: `Agent not found: ${agentName}`,
      metrics: { tokens: 0, duration: 0, toolCalls: 0 },
    };
  }

  // DUPLICATE SPAWN PREVENTION with SEMANTIC SIMILARITY
  const isSwarmWorker = agentName.startsWith('swarm-');

  const SEMANTIC_SIMILARITY_THRESHOLD = 0.75;
  const taskKey = `${agentName}:${task.slice(0, 150).toLowerCase().replace(/\s+/g, ' ').trim()}`;
  const now = Date.now();

  // Clean up old entries
  for (const [key, entry] of ctx.spawnedTasks.entries()) {
    if (now - entry.timestamp > SPAWN_DEDUP_WINDOW_MS) {
      ctx.spawnedTasks.delete(key);
    }
  }

  let existingMatch: { timestamp: number; result: string; queuedChanges: number } | undefined;
  let matchType: 'exact' | 'semantic' = 'exact';

  if (!isSwarmWorker) {
    existingMatch = ctx.spawnedTasks.get(taskKey);

    if (!existingMatch) {
      for (const [key, entry] of ctx.spawnedTasks.entries()) {
        if (!key.startsWith(`${agentName}:`)) continue;
        if (now - entry.timestamp >= SPAWN_DEDUP_WINDOW_MS) continue;

        const existingTask = key.slice(agentName.length + 1);
        const similarity = calculateTaskSimilarity(task, existingTask);

        if (similarity >= SEMANTIC_SIMILARITY_THRESHOLD) {
          existingMatch = entry;
          matchType = 'semantic';
          ctx.observability?.logger?.debug('Semantic duplicate detected', {
            agent: agentName,
            newTask: task.slice(0, 80),
            existingTask: existingTask.slice(0, 80),
            similarity: (similarity * 100).toFixed(1) + '%',
          });
          break;
        }
      }
    }
  }

  if (existingMatch && now - existingMatch.timestamp < SPAWN_DEDUP_WINDOW_MS) {
    ctx.observability?.logger?.warn('Duplicate spawn prevented', {
      agent: agentName,
      task: task.slice(0, 100),
      matchType,
      originalTimestamp: existingMatch.timestamp,
      elapsedMs: now - existingMatch.timestamp,
    });

    const duplicateMessage = `[DUPLICATE SPAWN PREVENTED${matchType === 'semantic' ? ' - SEMANTIC MATCH' : ''}]\n` +
      `This task was already spawned ${Math.round((now - existingMatch.timestamp) / 1000)}s ago.\n` +
      `${existingMatch.queuedChanges > 0
        ? `The previous spawn queued ${existingMatch.queuedChanges} change(s) to the pending plan.\n` +
          `These changes are already in your plan - do NOT spawn again.\n`
        : ''
      }Previous result summary:\n${existingMatch.result.slice(0, 500)}`;

    return {
      success: true,
      output: duplicateMessage,
      metrics: { tokens: 0, duration: 0, toolCalls: 0 },
    };
  }

  const agentId = `spawn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  ctx.emit({ type: 'agent.spawn', agentId, name: agentName, task });
  ctx.observability?.logger?.info('Spawning agent', { name: agentName, task });

  const startTime = Date.now();
  const childSessionId = `subagent-${agentName}-${Date.now()}`;
  const childTraceId = `trace-${childSessionId}`;
  let workerResultId: string | undefined;

  try {
    // Filter tools for this agent
    let agentTools = filterToolsForAgent(agentDef, Array.from(ctx.tools.values()));

    // Resolve policy profile
    const inferredTaskType = agentDef.taskType ?? ToolRecommendationEngine.inferTaskType(agentName);
    const policyResolution = resolvePolicyProfile({
      policyEngine: ctx.config.policyEngine,
      requestedProfile: agentDef.policyProfile,
      swarmConfig: isSwarmWorker && ctx.config.swarm && typeof ctx.config.swarm === 'object'
        ? ctx.config.swarm as SwarmConfig
        : undefined,
      taskType: inferredTaskType,
      isSwarmWorker,
      sandboxConfig: ctx.config.sandbox && typeof ctx.config.sandbox === 'object'
        ? ctx.config.sandbox
        : undefined,
    });
    ctx.emit({
      type: 'policy.profile.resolved',
      profile: policyResolution.profileName,
      context: isSwarmWorker ? 'swarm' : 'subagent',
      selectionSource: policyResolution.metadata.selectionSource,
      usedLegacyMappings: policyResolution.metadata.usedLegacyMappings,
      legacySources: policyResolution.metadata.legacyMappingSources,
    });
    if (policyResolution.metadata.usedLegacyMappings) {
      ctx.emit({
        type: 'policy.legacy.fallback.used',
        profile: policyResolution.profileName,
        sources: policyResolution.metadata.legacyMappingSources,
        warnings: policyResolution.metadata.warnings,
      });
      ctx.observability?.logger?.warn('Policy legacy mappings used', {
        agent: agentName,
        profile: policyResolution.profileName,
        sources: policyResolution.metadata.legacyMappingSources,
      });
    }

    // Apply tool recommendations
    if (ctx.toolRecommendation && agentTools.length > 15) {
      const taskType = ToolRecommendationEngine.inferTaskType(agentName);
      const recommendations = ctx.toolRecommendation.recommendTools(
        task, taskType, agentTools.map(t => t.name)
      );
      if (recommendations.length > 0) {
        const recommendedNames = new Set(recommendations.map(r => r.toolName));
        const alwaysKeep = new Set(['spawn_agent', 'spawn_agents_parallel']);
        if (policyResolution.profile.allowedTools) {
          for (const t of policyResolution.profile.allowedTools) alwaysKeep.add(t);
        }
        agentTools = agentTools.filter(t =>
          recommendedNames.has(t.name) || alwaysKeep.has(t.name)
        );
      }
    }

    // Enforce unified tool policy
    if (policyResolution.profile.toolAccessMode === 'whitelist' && policyResolution.profile.allowedTools) {
      const allowed = new Set(policyResolution.profile.allowedTools);
      agentTools = agentTools.filter(t => allowed.has(t.name));
    } else if (policyResolution.profile.deniedTools && policyResolution.profile.deniedTools.length > 0) {
      const denied = new Set(policyResolution.profile.deniedTools);
      agentTools = agentTools.filter(t => !denied.has(t.name));
    }

    if (agentTools.length === 0) {
      throw new Error(`Worker '${agentName}' has zero available tools after filtering. Check toolAccessMode and policy profile '${policyResolution.profileName}'.`);
    }

    // Resolve model
    const resolvedModel = (agentDef.model && agentDef.model.includes('/'))
      ? agentDef.model
      : ctx.config.model;

    // Persist subagent task lifecycle
    if (ctx.store?.hasWorkerResultsFeature()) {
      try {
        workerResultId = ctx.store.createWorkerResult(
          agentId,
          task.slice(0, 500),
          resolvedModel || 'default'
        );
      } catch (storeErr) {
        ctx.observability?.logger?.warn('Failed to create worker result record', {
          agentId,
          error: (storeErr as Error).message,
        });
      }
    }

    // Get subagent config with agent-type-specific timeouts and iteration limits
    const subagentConfig = ctx.config.subagent;
    const hasSubagentConfig = subagentConfig !== false && subagentConfig !== undefined;

    // Timeout precedence
    const agentTypeTimeout = getSubagentTimeout(agentName);
    const rawPerTypeTimeout = hasSubagentConfig
      ? (subagentConfig as { timeouts?: Record<string, number> }).timeouts?.[agentName]
      : undefined;
    const rawGlobalTimeout = hasSubagentConfig
      ? (subagentConfig as { defaultTimeout?: number }).defaultTimeout
      : undefined;
    const isValidTimeout = (v: number | undefined): v is number =>
      v !== undefined && Number.isFinite(v) && v > 0;
    const agentDefTimeout = isValidTimeout(agentDef.timeout) ? agentDef.timeout : undefined;
    const perTypeConfigTimeout = isValidTimeout(rawPerTypeTimeout) ? rawPerTypeTimeout : undefined;
    const globalConfigTimeout = isValidTimeout(rawGlobalTimeout) ? rawGlobalTimeout : undefined;
    const subagentTimeout = agentDefTimeout ?? perTypeConfigTimeout ?? agentTypeTimeout ?? globalConfigTimeout ?? 300000;

    // Iteration precedence
    const agentTypeMaxIter = getSubagentMaxIterations(agentName);
    const rawPerTypeMaxIter = hasSubagentConfig
      ? (subagentConfig as { maxIterations?: Record<string, number> }).maxIterations?.[agentName]
      : undefined;
    const rawGlobalMaxIter = hasSubagentConfig
      ? (subagentConfig as { defaultMaxIterations?: number }).defaultMaxIterations
      : undefined;
    const isValidIter = (v: number | undefined): v is number =>
      v !== undefined && Number.isFinite(v) && v > 0 && Number.isInteger(v);
    const perTypeConfigMaxIter = isValidIter(rawPerTypeMaxIter) ? rawPerTypeMaxIter : undefined;
    const globalConfigMaxIter = isValidIter(rawGlobalMaxIter) ? rawGlobalMaxIter : undefined;
    const defaultMaxIterations = agentDef.maxIterations ?? perTypeConfigMaxIter ?? agentTypeMaxIter ?? globalConfigMaxIter ?? 15;

    // BLACKBOARD CONTEXT INJECTION
    let blackboardContext = '';
    const parentAgentId = `parent-${Date.now()}`;

    if (ctx.blackboard) {
      ctx.blackboard.post(parentAgentId, {
        topic: 'spawn.parent_context',
        content: `Parent spawning ${agentName} for task: ${task.slice(0, 200)}`,
        type: 'progress',
        confidence: 1,
        metadata: { agentName, taskPreview: task.slice(0, 100) },
      });

      const recentFindings = ctx.blackboard.query({
        limit: 5,
        types: ['discovery', 'analysis', 'progress'],
        minConfidence: 0.7,
      });

      if (recentFindings.length > 0) {
        const findingsSummary = recentFindings
          .map(f => `- [${f.agentId}] ${f.topic}: ${f.content.slice(0, 150)}${f.content.length > 150 ? '...' : ''}`)
          .join('\n');
        blackboardContext = `\n\n**BLACKBOARD CONTEXT (from parent/sibling agents):**\n${findingsSummary}\n`;
      }
    }

    // Check for files already in parent's pending plan
    const currentPlan = ctx.pendingPlanManager.getPendingPlan();
    if (currentPlan && currentPlan.proposedChanges.length > 0) {
      const pendingFiles = currentPlan.proposedChanges
        .filter((c: { tool: string }) => c.tool === 'write_file' || c.tool === 'edit_file')
        .map((c: { args: { path?: string; file_path?: string } }) => c.args.path || c.args.file_path)
        .filter(Boolean) as string[];

      if (pendingFiles.length > 0) {
        blackboardContext += `\n**FILES ALREADY IN PENDING PLAN (do not duplicate):**\n${pendingFiles.slice(0, 10).join('\n')}\n`;
      }
    }

    // CONSTRAINT INJECTION
    const constraintParts: string[] = [];

    const subagentBudgetTokens = constraints?.maxTokens ?? SUBAGENT_BUDGET.maxTokens ?? 100000;
    const subagentBudgetMinutes = Math.round((SUBAGENT_BUDGET.maxDuration ?? 240000) / 60000);

    if (isSwarmWorker) {
      constraintParts.push(
        `**Execution Mode:** You are a focused worker agent.\n` +
        `- Complete your assigned task using tool calls.\n` +
        `- Your FIRST action must be a tool call (read_file, write_file, edit_file, grep, glob, etc.).\n` +
        `- To create files use write_file. To modify files use edit_file. Do NOT use bash for file operations.\n` +
        `- You will receive a system message if you need to wrap up. Until then, work normally.\n` +
        `- Do NOT produce summaries or reports — produce CODE and FILE CHANGES.`
      );
    } else {
      constraintParts.push(
        `**RESOURCE AWARENESS (CRITICAL):**\n` +
        `- Token budget: ~${(subagentBudgetTokens / 1000).toFixed(0)}k tokens\n` +
        `- Time limit: ~${subagentBudgetMinutes} minutes\n` +
        `- You will receive warnings at 70% usage. When warned, WRAP UP immediately.\n` +
        `- Do not explore indefinitely - be focused and efficient.\n` +
        `- If approaching limits, summarize findings and return.\n` +
        `- **STRUCTURED WRAPUP:** When told to wrap up, respond with ONLY this JSON (no tool calls):\n` +
        `  {"findings":[...], "actionsTaken":[...], "failures":[...], "remainingWork":[...], "suggestedNextSteps":[...]}`
      );
    }

    if (constraints) {
      if (constraints.focusAreas && constraints.focusAreas.length > 0) {
        constraintParts.push(`**FOCUS AREAS (limit exploration to these paths):**\n${constraints.focusAreas.map(a => `  - ${a}`).join('\n')}`);
      }
      if (constraints.excludeAreas && constraints.excludeAreas.length > 0) {
        constraintParts.push(`**EXCLUDED AREAS (do NOT explore these):**\n${constraints.excludeAreas.map(a => `  - ${a}`).join('\n')}`);
      }
      if (constraints.requiredDeliverables && constraints.requiredDeliverables.length > 0) {
        constraintParts.push(`**REQUIRED DELIVERABLES (you must produce these):**\n${constraints.requiredDeliverables.map(d => `  - ${d}`).join('\n')}`);
      }
      if (constraints.timeboxMinutes) {
        constraintParts.push(`**TIME LIMIT:** ${constraints.timeboxMinutes} minutes (soft limit - wrap up if approaching)`);
      }
    }

    const constraintContext = `\n\n**EXECUTION CONSTRAINTS:**\n${constraintParts.join('\n\n')}\n`;

    // Build delegation-enhanced system prompt
    let delegationContext = '';
    if (ctx.lastComplexityAssessment && ctx.lastComplexityAssessment.tier !== 'simple') {
      const spec = createMinimalDelegationSpec(task, agentName);
      delegationContext = '\n\n' + buildDelegationPrompt(spec);
    }

    const qualityPrompt = '\n\n' + getSubagentQualityPrompt();

    // Build subagent system prompt
    const parentMode = ctx.modeManager.getMode();
    const subagentSystemPrompt = parentMode === 'plan'
      ? `${agentDef.systemPrompt}\n\n${SUBAGENT_PLAN_MODE_ADDITION}${blackboardContext}${constraintContext}${delegationContext}${qualityPrompt}`
      : `${agentDef.systemPrompt}${blackboardContext}${constraintContext}${delegationContext}${qualityPrompt}`;

    // Allocate budget
    const pooledBudget = getSubagentBudget(ctx, agentName, constraints);
    const poolAllocationId = pooledBudget.allocationId;

    const deniedByProfile = new Set(policyResolution.profile.deniedTools ?? []);
    const policyToolPolicies: Record<string, { policy: 'allow' | 'prompt' | 'forbidden'; reason?: string }> = {};
    for (const toolName of deniedByProfile) {
      policyToolPolicies[toolName] = {
        policy: 'forbidden',
        reason: `Denied by policy profile '${policyResolution.profileName}'`,
      };
    }
    if ((policyResolution.profile.bashMode ?? 'full') === 'disabled') {
      policyToolPolicies.bash = {
        policy: 'forbidden',
        reason: `Bash is disabled by policy profile '${policyResolution.profileName}'`,
      };
    }

    // Create the sub-agent via factory (avoids circular import)
    const subAgent = createSubAgent({
      provider: ctx.provider,
      tools: agentTools,
      toolResolver: ctx.toolResolver || undefined,
      mcpToolSummaries: ctx.config.mcpToolSummaries,
      systemPrompt: subagentSystemPrompt,
      model: resolvedModel,
      maxIterations: agentDef.maxIterations || defaultMaxIterations,
      memory: false,
      planning: false,
      reflection: false,
      compaction: {
        enabled: true,
        mode: 'auto',
        tokenThreshold: 40000,
        preserveRecentCount: 4,
        preserveToolResults: false,
        summaryMaxTokens: 500,
      },
      maxContextTokens: 80000,
      observability: ctx.config.observability,
      sandbox: (() => {
        const swarm = ctx.config.swarm;
        const extraCmds = swarm && typeof swarm === 'object' && (swarm as SwarmConfig).permissions?.additionalAllowedCommands;
        const baseSbx = ctx.config.sandbox;
        if (baseSbx && typeof baseSbx === 'object') {
          const sbx = baseSbx as SandboxConfig;
          const allowedCommands = extraCmds
            ? [...(sbx.allowedCommands || []), ...extraCmds]
            : sbx.allowedCommands;
          return {
            ...sbx,
            allowedCommands,
            bashMode: policyResolution.profile.bashMode ?? sbx.bashMode,
            bashWriteProtection: policyResolution.profile.bashWriteProtection ?? sbx.bashWriteProtection,
            blockFileCreationViaBash:
              (policyResolution.profile.bashWriteProtection ?? 'off') === 'block_file_mutation'
                ? true
                : sbx.blockFileCreationViaBash,
          };
        }
        return baseSbx;
      })(),
      // Subagents: raise riskThreshold to 'high' so moderate-risk tools (write_file, edit_file)
      // pass without approval dialogs. High-risk tools (delete_file) still require approval.
      // The scopedApprove paths still constrain WHERE subagents can write.
      humanInLoop: ctx.config.humanInLoop
        ? {
            ...ctx.config.humanInLoop,
            riskThreshold: 'high' as const,
          }
        : ctx.config.humanInLoop,
      executionPolicy: (() => {
        const hasPolicyOverrides = Object.keys(policyToolPolicies).length > 0;
        if (ctx.config.executionPolicy) {
          return {
            ...ctx.config.executionPolicy,
            defaultPolicy: 'allow' as const,
            toolPolicies: {
              ...(ctx.config.executionPolicy.toolPolicies ?? {}),
              ...policyToolPolicies,
            },
          };
        }
        if (hasPolicyOverrides) {
          return {
            enabled: true,
            defaultPolicy: 'allow' as const,
            toolPolicies: policyToolPolicies,
            intentAware: false,
          };
        }
        return { enabled: true, defaultPolicy: 'allow' as const, toolPolicies: {}, intentAware: false };
      })(),
      policyEngine: ctx.config.policyEngine
        ? { ...ctx.config.policyEngine, defaultProfile: policyResolution.profileName }
        : ctx.config.policyEngine,
      threads: false,
      hooks: ctx.config.hooks === false ? false : {
        enabled: true,
        builtIn: { logging: false, timing: false, metrics: false },
        custom: [],
      },
      agentId,
      blackboard: ctx.blackboard || undefined,
      fileCache: ctx.fileCache || undefined,
      budget: agentDef.economicsTuning
        ? { ...pooledBudget.budget, tuning: agentDef.economicsTuning }
        : pooledBudget.budget,
      sharedContextState: ctx.sharedContextState || undefined,
      sharedEconomicsState: ctx.sharedEconomicsState || undefined,
    });

    // Inherit parent's mode
    if (parentMode !== 'build') {
      subAgent.setMode(parentMode);
    }

    // APPROVAL BATCHING
    const swarmPerms = ctx.config.swarm && typeof ctx.config.swarm === 'object'
      ? (ctx.config.swarm as SwarmConfig).permissions : undefined;

    const baseAutoApprove = ['read_file', 'list_files', 'glob', 'grep', 'show_file_history', 'show_session_changes'];
    const baseScopedApprove: Record<string, { paths: string[] }> = isSwarmWorker
      ? {
          write_file: { paths: ['src/', 'tests/', 'tools/'] },
          edit_file: { paths: ['src/', 'tests/', 'tools/'] },
          bash: { paths: ['src/', 'tests/', 'tools/'] },
        }
      : {
          write_file: { paths: ['src/', 'tests/', 'tools/'] },
          edit_file: { paths: ['src/', 'tests/', 'tools/'] },
        };
    const baseRequireApproval = isSwarmWorker ? ['delete_file'] : ['bash', 'delete_file'];
    const mergedScope = mergeApprovalScopeWithProfile({
      autoApprove: swarmPerms?.autoApprove
        ? [...new Set([...baseAutoApprove, ...swarmPerms.autoApprove])]
        : baseAutoApprove,
      scopedApprove: swarmPerms?.scopedApprove
        ? { ...baseScopedApprove, ...swarmPerms.scopedApprove }
        : baseScopedApprove,
      requireApproval: swarmPerms?.requireApproval
        ? swarmPerms.requireApproval
        : baseRequireApproval,
    }, policyResolution.profile);

    subAgent.setApprovalScope(mergedScope);
    subAgent.setParentIterations(ctx.getTotalIterations());

    // UNIFIED TRACING
    if (ctx.traceCollector) {
      const subagentTraceView = ctx.traceCollector.createSubagentView({
        parentSessionId: ctx.traceCollector.getSessionId() || 'unknown',
        agentType: agentName,
        spawnedAtIteration: ctx.state.iteration,
      });
      subAgent.setTraceCollector(subagentTraceView);
    }

    // GRACEFUL TIMEOUT with WRAPUP PHASE
    const IDLE_TIMEOUT = agentDef.idleTimeout ?? 120000;
    let WRAPUP_WINDOW = 30000;
    let IDLE_CHECK_INTERVAL = 5000;
    if (ctx.config.subagent) {
      WRAPUP_WINDOW = ctx.config.subagent.wrapupWindowMs ?? WRAPUP_WINDOW;
      IDLE_CHECK_INTERVAL = ctx.config.subagent.idleCheckIntervalMs ?? IDLE_CHECK_INTERVAL;
    }
    const progressAwareTimeout = createGracefulTimeout(
      subagentTimeout,
      IDLE_TIMEOUT,
      WRAPUP_WINDOW,
      IDLE_CHECK_INTERVAL
    );

    progressAwareTimeout.onWrapupWarning(() => {
      ctx.emit({
        type: 'subagent.wrapup.started',
        agentId,
        agentType: agentName,
        reason: 'Timeout approaching - graceful wrapup window opened',
        elapsedMs: Date.now() - startTime,
      });
      subAgent.requestWrapup('Timeout approaching — produce structured summary');
    });

    // Forward events from subagent
    const unsubSubAgent = subAgent.subscribe(event => {
      const taggedEvent = { ...event, subagent: agentName, subagentId: agentId };
      ctx.emit(taggedEvent);

      const progressEvents = ['tool.start', 'tool.complete', 'llm.start', 'llm.complete'];
      if (progressEvents.includes(event.type)) {
        progressAwareTimeout.reportProgress();
      }
    });

    // Link parent's cancellation
    const parentSource = ctx.cancellation?.getSource();
    const effectiveSource = parentSource
      ? createLinkedToken(parentSource, progressAwareTimeout)
      : progressAwareTimeout;

    subAgent.setExternalCancellation(effectiveSource.token);

    // Pause parent's duration timer
    ctx.economics?.pauseDuration();

    try {
      const result = await race(subAgent.run(task), effectiveSource.token);
      const duration = Date.now() - startTime;

      // Extract subagent's pending plan and merge into parent's plan
      let queuedChangeSummary = '';
      let queuedChangesCount = 0;
      if (subAgent.hasPendingPlan()) {
        const subPlan = subAgent.getPendingPlan();
        if (subPlan && subPlan.proposedChanges.length > 0) {
          queuedChangesCount = subPlan.proposedChanges.length;

          ctx.emit({
            type: 'agent.pending_plan',
            agentId: agentName,
            changes: subPlan.proposedChanges,
          });

          const changeSummaries = subPlan.proposedChanges.map(c => {
            if (c.tool === 'write_file' || c.tool === 'edit_file') {
              const path = c.args.path || c.args.file_path || '(unknown file)';
              return `  - [${c.tool}] ${path}: ${c.reason}`;
            } else if (c.tool === 'bash') {
              const cmd = String(c.args.command || '').slice(0, 60);
              return `  - [bash] ${cmd}${String(c.args.command || '').length > 60 ? '...' : ''}: ${c.reason}`;
            }
            return `  - [${c.tool}]: ${c.reason}`;
          });

          queuedChangeSummary = `\n\n[PLAN MODE - CHANGES QUEUED TO PARENT]\n` +
            `The following ${subPlan.proposedChanges.length} change(s) have been queued in the parent's pending plan:\n` +
            changeSummaries.join('\n') + '\n' +
            `\nThese changes are now in YOUR pending plan. The task for this subagent is COMPLETE.\n` +
            `Do NOT spawn another agent for the same task - the changes are already queued.\n` +
            `Use /show-plan to see all pending changes, /approve to execute them.`;

          for (const change of subPlan.proposedChanges) {
            ctx.pendingPlanManager.addProposedChange(
              change.tool,
              { ...change.args, _fromSubagent: agentName },
              `[${agentName}] ${change.reason}`,
              change.toolCallId
            );
          }
        }

        if (subPlan?.explorationSummary) {
          ctx.pendingPlanManager.appendExplorationFinding(
            `[${agentName}] ${subPlan.explorationSummary}`
          );
        }
      }

      const finalOutput = queuedChangeSummary
        ? (result.response || '') + queuedChangeSummary
        : (result.response || result.error || '');

      const structured = parseStructuredClosureReport(
        result.response || '',
        'completed'
      );

      const subagentFilePaths = subAgent.getModifiedFilePaths();

      const spawnResultFinal: SpawnResult = {
        success: result.success,
        output: finalOutput,
        metrics: {
          tokens: result.metrics.totalTokens,
          duration,
          toolCalls: result.metrics.toolCalls,
        },
        structured,
        filesModified: subagentFilePaths,
      };

      // Save to output store
      if (ctx.subagentOutputStore) {
        const outputEntry: SubagentOutput = {
          id: agentId,
          agentId,
          agentName,
          task,
          fullOutput: finalOutput,
          structured,
          filesModified: subagentFilePaths,
          filesCreated: [],
          timestamp: new Date(),
          tokensUsed: result.metrics.totalTokens,
          durationMs: duration,
        };
        const storeId = ctx.subagentOutputStore.save(outputEntry);
        spawnResultFinal.outputStoreId = storeId;
      }

      if (workerResultId && ctx.store?.hasWorkerResultsFeature()) {
        try {
          ctx.store.completeWorkerResult(workerResultId, {
            fullOutput: finalOutput,
            summary: finalOutput.slice(0, 500),
            artifacts: structured ? [{ type: 'structured_report', data: structured }] : undefined,
            metrics: {
              tokens: result.metrics.totalTokens,
              duration,
              toolCalls: result.metrics.toolCalls,
            },
          });
        } catch (storeErr) {
          ctx.observability?.logger?.warn('Failed to persist worker result', {
            agentId,
            error: (storeErr as Error).message,
          });
        }
      }

      ctx.emit({
        type: 'agent.complete',
        agentId,
        agentType: agentName,
        success: result.success,
        output: finalOutput.slice(0, 500),
      });
      if (progressAwareTimeout.isInWrapupPhase()) {
        ctx.emit({
          type: 'subagent.wrapup.completed',
          agentId,
          agentType: agentName,
          elapsedMs: Date.now() - startTime,
        });
      }

      // Enhanced tracing
      ctx.traceCollector?.record({
        type: 'subagent.link',
        data: {
          parentSessionId: ctx.traceCollector.getSessionId() || 'unknown',
          childSessionId,
          childTraceId,
          childConfig: {
            agentType: agentName,
            model: resolvedModel || 'default',
            task,
            tools: agentTools.map(t => t.name),
          },
          spawnContext: {
            reason: `Delegated task: ${task.slice(0, 100)}`,
            expectedOutcome: agentDef.description,
            parentIteration: ctx.state.iteration,
          },
          result: {
            success: result.success,
            summary: (result.response || result.error || '').slice(0, 500),
            tokensUsed: result.metrics.totalTokens,
            durationMs: duration,
          },
        },
      });

      unsubSubAgent();
      await subAgent.cleanup();

      ctx.spawnedTasks.set(taskKey, {
        timestamp: Date.now(),
        result: finalOutput,
        queuedChanges: queuedChangesCount,
      });

      return spawnResultFinal;
    } catch (err) {
      // Handle cancellation
      if (isCancellationError(err)) {
        const duration = Date.now() - startTime;
        const isUserCancellation = parentSource?.isCancellationRequested;
        const reason = isUserCancellation
          ? 'User cancelled'
          : (err as CancellationError).reason || `Timed out after ${subagentTimeout}ms`;
        ctx.emit({ type: 'agent.error', agentId, agentType: agentName, error: reason });
        if (!isUserCancellation) {
          ctx.emit({
            type: 'subagent.timeout.hard_kill',
            agentId,
            agentType: agentName,
            reason,
            elapsedMs: Date.now() - startTime,
          });
        }

        // PRESERVE PARTIAL RESULTS
        const subagentState = subAgent.getState();
        const subagentMetrics = subAgent.getMetrics();

        const assistantMessages = subagentState.messages.filter(m => m.role === 'assistant');
        const lastAssistantMsg = assistantMessages[assistantMessages.length - 1];
        const partialResponse = typeof lastAssistantMsg?.content === 'string'
          ? lastAssistantMsg.content
          : '';

        let cancelledQueuedSummary = '';
        if (subAgent.hasPendingPlan()) {
          const subPlan = subAgent.getPendingPlan();
          if (subPlan && subPlan.proposedChanges.length > 0) {
            ctx.emit({
              type: 'agent.pending_plan',
              agentId: agentName,
              changes: subPlan.proposedChanges,
            });

            const changeSummaries = subPlan.proposedChanges.map(c => {
              if (c.tool === 'write_file' || c.tool === 'edit_file') {
                const path = c.args.path || c.args.file_path || '(unknown file)';
                return `  - [${c.tool}] ${path}: ${c.reason}`;
              } else if (c.tool === 'bash') {
                const cmd = String(c.args.command || '').slice(0, 60);
                return `  - [bash] ${cmd}...: ${c.reason}`;
              }
              return `  - [${c.tool}]: ${c.reason}`;
            });

            cancelledQueuedSummary = `\n\n[PLAN MODE - CHANGES QUEUED BEFORE CANCELLATION]\n` +
              `${subPlan.proposedChanges.length} change(s) were queued to the parent plan:\n` +
              changeSummaries.join('\n') + '\n' +
              `These changes are preserved in your pending plan.`;

            for (const change of subPlan.proposedChanges) {
              ctx.pendingPlanManager.addProposedChange(
                change.tool,
                { ...change.args, _fromSubagent: agentName },
                `[${agentName}] ${change.reason}`,
                change.toolCallId
              );
            }
          }

          if (subPlan?.explorationSummary) {
            ctx.pendingPlanManager.appendExplorationFinding(
              `[${agentName}] ${subPlan.explorationSummary}`
            );
          }
        }

        const subagentFilePaths = subAgent.getModifiedFilePaths();

        unsubSubAgent();
        try {
          await subAgent.cleanup();
        } catch {
          // Ignore cleanup errors on cancellation
        }

        const baseOutput = isUserCancellation
          ? `Subagent '${agentName}' was cancelled by user.`
          : `Subagent '${agentName}' timed out after ${Math.round(subagentTimeout / 1000)}s.`;

        const partialResultSection = partialResponse
          ? `\n\n[PARTIAL RESULTS BEFORE TIMEOUT]\n${partialResponse.slice(0, 2000)}${partialResponse.length > 2000 ? '...(truncated)' : ''}`
          : '';

        ctx.traceCollector?.record({
          type: 'subagent.link',
          data: {
            parentSessionId: ctx.traceCollector.getSessionId() || 'unknown',
            childSessionId,
            childTraceId,
            childConfig: {
              agentType: agentName,
              model: resolvedModel || 'default',
              task,
              tools: agentTools.map(t => t.name),
            },
            spawnContext: {
              reason: `Delegated task: ${task.slice(0, 100)}`,
              expectedOutcome: agentDef.description,
              parentIteration: ctx.state.iteration,
            },
            result: {
              success: false,
              summary: `[TIMEOUT] ${baseOutput}\n${partialResponse.slice(0, 200)}`,
              tokensUsed: subagentMetrics.totalTokens,
              durationMs: duration,
            },
          },
        });

        const exitReason = isUserCancellation ? 'cancelled' as const : 'timeout_graceful' as const;
        const structured = parseStructuredClosureReport(
          partialResponse,
          exitReason,
          task
        );

        if (workerResultId && ctx.store?.hasWorkerResultsFeature()) {
          try {
            ctx.store.failWorkerResult(workerResultId, reason);
          } catch (storeErr) {
            ctx.observability?.logger?.warn('Failed to mark cancelled worker result as failed', {
              agentId,
              error: (storeErr as Error).message,
            });
          }
        }

        return {
          success: false,
          output: baseOutput + partialResultSection + cancelledQueuedSummary,
          metrics: {
            tokens: subagentMetrics.totalTokens,
            duration,
            toolCalls: subagentMetrics.toolCalls,
          },
          structured,
          filesModified: subagentFilePaths,
        };
      }
      throw err;
    } finally {
      ctx.economics?.resumeDuration();
      effectiveSource.dispose();
      progressAwareTimeout.dispose();

      if (ctx.budgetPool && poolAllocationId) {
        const subMetrics = subAgent.getMetrics();
        ctx.budgetPool.recordUsage(
          poolAllocationId,
          subMetrics.totalTokens,
          subMetrics.estimatedCost,
        );
        ctx.budgetPool.release(poolAllocationId);
      }
    }
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    ctx.emit({ type: 'agent.error', agentId, agentType: agentName, error });

    if (workerResultId && ctx.store?.hasWorkerResultsFeature()) {
      try {
        ctx.store.failWorkerResult(workerResultId, error);
      } catch (storeErr) {
        ctx.observability?.logger?.warn('Failed to mark worker result as failed', {
          agentId,
          error: (storeErr as Error).message,
        });
      }
    }

    return {
      success: false,
      output: `Agent error: ${error}`,
      metrics: { tokens: 0, duration: Date.now() - startTime, toolCalls: 0 },
    };
  }
}

/**
 * Spawn multiple agents in parallel to work on independent tasks.
 * Uses DynamicBudgetPool for parallel spawns and SubagentSupervisor for monitoring.
 * Extracted from ProductionAgent.spawnAgentsParallel().
 */
export async function spawnAgentsParallel(
  tasks: Array<{ agent: string; task: string }>,
  ctx: AgentContext,
  mutators: AgentContextMutators,
  createSubAgent: SubAgentFactory,
): Promise<SpawnResult[]> {
  ctx.emit({
    type: 'parallel.spawn.start',
    count: tasks.length,
    agents: tasks.map(t => t.agent),
  });

  let settled: PromiseSettledResult<SpawnResult>[];
  const originalPool = ctx.budgetPool;

  const supervisor = tasks.length > 1 ? createSubagentSupervisor() : null;

  if (ctx.budgetPool && tasks.length > 1) {
    const poolStats = ctx.budgetPool.getStats();
    const dynamicPool = createDynamicBudgetPool(poolStats.tokensRemaining, 0.1);
    dynamicPool.setExpectedChildren(tasks.length);

    // Temporarily replace the budget pool
    mutators.setBudgetPool(dynamicPool);
    try {
      const promises = tasks.map(({ agent, task }) => {
        const spawnPromise = spawnAgent(agent, task, ctx, createSubAgent);
        if (supervisor) {
          const handle = createSubagentHandle(
            `parallel-${agent}-${Date.now()}`,
            agent,
            task,
            spawnPromise,
            {},
          );
          supervisor.add(handle);
        }
        return spawnPromise;
      });
      settled = await Promise.allSettled(promises);
    } finally {
      mutators.setBudgetPool(originalPool);
      supervisor?.stop();
    }
  } else {
    const promises = tasks.map(({ agent, task }) =>
      spawnAgent(agent, task, ctx, createSubAgent)
    );
    settled = await Promise.allSettled(promises);
  }

  const results: SpawnResult[] = settled.map((result, i) => {
    if (result.status === 'fulfilled') {
      return result.value;
    }
    const error = result.reason instanceof Error ? result.reason.message : String(result.reason);
    ctx.emit({
      type: 'agent.error',
      agentId: tasks[i].agent,
      error: `Unexpected parallel spawn error: ${error}`,
    });
    return {
      success: false,
      output: `Parallel spawn error: ${error}`,
      metrics: { tokens: 0, duration: 0, toolCalls: 0 },
    };
  });

  ctx.emit({
    type: 'parallel.spawn.complete',
    count: tasks.length,
    successCount: results.filter(r => r.success).length,
    results: results.map((r, i) => ({
      agent: tasks[i].agent,
      success: r.success,
      tokens: r.metrics?.tokens || 0,
    })),
  });

  return results;
}
