/**
 * Inefficiency Detector
 *
 * Detects patterns that indicate inefficient agent behavior.
 */

import type { ParsedSession, ParsedIteration, Inefficiency } from '../types.js';

/**
 * Code location mapping for common inefficiencies.
 */
const CODE_LOCATIONS: Record<string, Array<{ file: string; component: string; relevance: 'primary' | 'secondary' | 'related' }>> = {
  excessive_iterations: [
    { file: 'src/agent.ts', component: 'ProductionAgent.run', relevance: 'primary' },
    { file: 'src/integrations/context-engineering.ts', component: 'ContextEngineering', relevance: 'secondary' },
  ],
  cache_inefficiency: [
    { file: 'src/tracing/cache-boundary-tracker.ts', component: 'CacheBoundaryTracker', relevance: 'primary' },
    { file: 'src/integrations/context-engineering.ts', component: 'ContextEngineering', relevance: 'secondary' },
  ],
  redundant_tool_calls: [
    { file: 'src/agent.ts', component: 'executeToolCalls', relevance: 'primary' },
    { file: 'src/tricks/failure-evidence.ts', component: 'FailureEvidence', relevance: 'secondary' },
  ],
  error_loop: [
    { file: 'src/tricks/failure-evidence.ts', component: 'FailureEvidence', relevance: 'primary' },
    { file: 'src/agent.ts', component: 'ProductionAgent.run', relevance: 'secondary' },
  ],
  slow_tool: [
    { file: 'src/tools/', component: 'Tool implementations', relevance: 'primary' },
    { file: 'src/integrations/mcp-client.ts', component: 'MCPClient', relevance: 'related' },
  ],
  token_spike: [
    { file: 'src/integrations/auto-compaction.ts', component: 'AutoCompactionManager', relevance: 'primary' },
    { file: 'src/tricks/reversible-compaction.ts', component: 'ReversibleCompaction', relevance: 'secondary' },
  ],
  thinking_overhead: [
    { file: 'src/providers/adapters/anthropic.ts', component: 'AnthropicProvider', relevance: 'primary' },
    { file: 'src/agent.ts', component: 'callLLM', relevance: 'secondary' },
  ],
  subagent_inefficiency: [
    { file: 'src/agent.ts', component: 'spawnAgent', relevance: 'primary' },
    { file: 'src/agent.ts', component: 'spawnAgentsParallel', relevance: 'secondary' },
  ],
  context_limit_warning: [
    { file: 'src/integrations/auto-compaction.ts', component: 'AutoCompactionManager', relevance: 'primary' },
    { file: 'src/agent.ts', component: 'ProductionAgent.run', relevance: 'secondary' },
  ],
  tool_timeout_patterns: [
    { file: 'src/tools/', component: 'Tool implementations', relevance: 'primary' },
    { file: 'src/integrations/cancellation.ts', component: 'CancellationManager', relevance: 'secondary' },
  ],
};

/**
 * Detects inefficiencies in session traces.
 */
export class InefficiencyDetector {
  private session: ParsedSession;
  private inefficiencies: Inefficiency[] = [];
  private idCounter = 0;

  constructor(session: ParsedSession) {
    this.session = session;
  }

  /**
   * Run all detection rules and return found inefficiencies.
   */
  detect(): Inefficiency[] {
    this.inefficiencies = [];
    this.idCounter = 0;

    this.detectExcessiveIterations();
    this.detectCacheInefficiency();
    this.detectRedundantToolCalls();
    this.detectErrorLoop();
    this.detectSlowTools();
    this.detectTokenSpike();
    this.detectThinkingOverhead();
    this.detectSubagentInefficiency();
    this.detectContextLimitWarning();
    this.detectToolTimeoutPatterns();

    // Sort by severity
    const severityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
    this.inefficiencies.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);

    return this.inefficiencies;
  }

  /**
   * Detect excessive iterations (> 5 iterations for most tasks).
   */
  private detectExcessiveIterations(): void {
    const count = this.session.iterations.length;
    if (count > 10) {
      this.addInefficiency({
        type: 'excessive_iterations',
        severity: 'high',
        description: `Session used ${count} iterations, which is significantly above typical (5-8)`,
        evidence: `Iteration count: ${count}`,
        suggestedFix: 'Review task complexity and consider breaking into subtasks or improving prompts',
      });
    } else if (count > 7) {
      this.addInefficiency({
        type: 'excessive_iterations',
        severity: 'medium',
        description: `Session used ${count} iterations, slightly above typical`,
        evidence: `Iteration count: ${count}`,
        suggestedFix: 'Consider improving prompt clarity or tool descriptions',
      });
    }
  }

  /**
   * Detect poor cache efficiency.
   */
  private detectCacheInefficiency(): void {
    const avgHitRate = this.session.metrics.avgCacheHitRate;

    if (avgHitRate < 0.3 && this.session.iterations.length > 2) {
      this.addInefficiency({
        type: 'cache_inefficiency',
        severity: 'high',
        description: `Very low cache hit rate: ${Math.round(avgHitRate * 100)}%`,
        evidence: `Expected >50% for multi-iteration sessions`,
        suggestedFix: 'Check for dynamic content in early messages or unstable system prompts',
      });
    } else if (avgHitRate < 0.5 && this.session.iterations.length > 3) {
      this.addInefficiency({
        type: 'cache_inefficiency',
        severity: 'medium',
        description: `Below-average cache hit rate: ${Math.round(avgHitRate * 100)}%`,
        evidence: `Expected >50% for longer sessions`,
        suggestedFix: 'Review message ordering and cache breakpoint patterns',
      });
    }

    // Check for sudden drops in cache hit rate
    let prevHitRate = 0;
    for (let i = 0; i < this.session.iterations.length; i++) {
      const hitRate = this.session.iterations[i].metrics.cacheHitRate;
      if (i > 0 && prevHitRate > 0.6 && hitRate < 0.2) {
        this.addInefficiency({
          type: 'cache_inefficiency',
          severity: 'medium',
          description: `Cache invalidation detected at iteration ${i + 1}`,
          evidence: `Cache hit rate dropped from ${Math.round(prevHitRate * 100)}% to ${Math.round(hitRate * 100)}%`,
          iterations: [i + 1],
          suggestedFix: 'Check what changed in iteration that caused cache invalidation',
        });
      }
      prevHitRate = hitRate;
    }
  }

  /**
   * Detect redundant tool calls.
   */
  private detectRedundantToolCalls(): void {
    const toolCallSignatures = new Map<string, number[]>();

    for (const iter of this.session.iterations) {
      for (const tool of iter.tools) {
        // Create a simple signature (tool name + stringified args hash)
        const signature = tool.name;
        const iterations = toolCallSignatures.get(signature) || [];
        iterations.push(iter.number);
        toolCallSignatures.set(signature, iterations);
      }
    }

    // Find tools called multiple times
    for (const [tool, iterations] of toolCallSignatures.entries()) {
      if (iterations.length >= 3) {
        this.addInefficiency({
          type: 'redundant_tool_calls',
          severity: iterations.length >= 5 ? 'high' : 'medium',
          description: `Tool "${tool}" called ${iterations.length} times`,
          evidence: `Called in iterations: ${iterations.join(', ')}`,
          iterations,
          suggestedFix: 'Consider caching tool results or improving memory/context management',
        });
      }
    }
  }

  /**
   * Detect error loops (repeated errors of same type).
   */
  private detectErrorLoop(): void {
    // Check for iterations with consecutive errors
    let consecutiveErrors = 0;
    const errorIterations: number[] = [];

    for (const iter of this.session.iterations) {
      const hasError = iter.tools.some(t => t.status === 'error');
      if (hasError) {
        consecutiveErrors++;
        errorIterations.push(iter.number);
      } else {
        if (consecutiveErrors >= 3) {
          this.addInefficiency({
            type: 'error_loop',
            severity: 'high',
            description: `${consecutiveErrors} consecutive iterations with errors`,
            evidence: `Error iterations: ${errorIterations.slice(-consecutiveErrors).join(', ')}`,
            iterations: errorIterations.slice(-consecutiveErrors),
            suggestedFix: 'Implement better error handling or failure detection to break loops',
          });
        }
        consecutiveErrors = 0;
      }
    }

    // Check final consecutive errors
    if (consecutiveErrors >= 3) {
      this.addInefficiency({
        type: 'error_loop',
        severity: 'critical',
        description: `Session ended with ${consecutiveErrors} consecutive errors`,
        evidence: `Error iterations: ${errorIterations.slice(-consecutiveErrors).join(', ')}`,
        iterations: errorIterations.slice(-consecutiveErrors),
        suggestedFix: 'Session likely failed due to unrecoverable error loop',
      });
    }
  }

  /**
   * Detect slow tools.
   */
  private detectSlowTools(): void {
    const toolDurations = new Map<string, number[]>();

    for (const iter of this.session.iterations) {
      for (const tool of iter.tools) {
        const durations = toolDurations.get(tool.name) || [];
        durations.push(tool.durationMs);
        toolDurations.set(tool.name, durations);
      }
    }

    for (const [tool, durations] of toolDurations.entries()) {
      const avgDuration = durations.reduce((a, b) => a + b, 0) / durations.length;
      const maxDuration = Math.max(...durations);

      if (avgDuration > 10000) { // > 10 seconds average
        this.addInefficiency({
          type: 'slow_tool',
          severity: 'high',
          description: `Tool "${tool}" is very slow (avg ${Math.round(avgDuration / 1000)}s)`,
          evidence: `Average: ${Math.round(avgDuration)}ms, Max: ${Math.round(maxDuration)}ms`,
          suggestedFix: 'Consider optimizing tool implementation or adding timeouts',
        });
      } else if (avgDuration > 5000) { // > 5 seconds
        this.addInefficiency({
          type: 'slow_tool',
          severity: 'medium',
          description: `Tool "${tool}" is slow (avg ${Math.round(avgDuration / 1000)}s)`,
          evidence: `Average: ${Math.round(avgDuration)}ms, Max: ${Math.round(maxDuration)}ms`,
          suggestedFix: 'Monitor tool performance and consider caching',
        });
      }
    }
  }

  /**
   * Detect token spikes (sudden large increases).
   */
  private detectTokenSpike(): void {
    let prevTokens = 0;
    for (let i = 0; i < this.session.iterations.length; i++) {
      const iter = this.session.iterations[i];
      const tokens = iter.metrics.inputTokens + iter.metrics.outputTokens;

      if (i > 0 && prevTokens > 0) {
        const increase = (tokens - prevTokens) / prevTokens;
        if (increase > 2 && tokens > 10000) { // 200% increase and significant absolute
          this.addInefficiency({
            type: 'token_spike',
            severity: 'medium',
            description: `Token spike at iteration ${i + 1} (+${Math.round(increase * 100)}%)`,
            evidence: `Tokens: ${prevTokens} → ${tokens}`,
            iterations: [i + 1],
            suggestedFix: 'Check for context explosion or large tool results',
          });
        }
      }
      prevTokens = tokens;
    }
  }

  /**
   * Detect excessive thinking tokens.
   */
  private detectThinkingOverhead(): void {
    let totalThinkingTokens = 0;
    let totalOutputTokens = 0;

    for (const iter of this.session.iterations) {
      if (iter.thinking) {
        totalThinkingTokens += iter.thinking.estimatedTokens;
      }
      totalOutputTokens += iter.metrics.outputTokens;
    }

    if (totalThinkingTokens > 0) {
      const thinkingRatio = totalThinkingTokens / (totalThinkingTokens + totalOutputTokens);
      if (thinkingRatio > 0.7) {
        this.addInefficiency({
          type: 'thinking_overhead',
          severity: 'medium',
          description: `High thinking overhead: ${Math.round(thinkingRatio * 100)}% of output`,
          evidence: `Thinking: ${totalThinkingTokens} tokens, Output: ${totalOutputTokens} tokens`,
          suggestedFix: 'Consider if extended thinking is necessary for this task type',
        });
      }
    }
  }

  /**
   * Detect subagent inefficiency (repeated failures).
   */
  private detectSubagentInefficiency(): void {
    const subagentFailures = this.session.subagentLinks.filter(link => link.success === false);
    const failedAgents = new Map<string, number>();

    for (const link of subagentFailures) {
      const count = (failedAgents.get(link.agentType) || 0) + 1;
      failedAgents.set(link.agentType, count);
    }

    // Check for same agent failing multiple times
    for (const [agentType, count] of failedAgents) {
      if (count >= 2) {
        this.addInefficiency({
          type: 'subagent_inefficiency',
          severity: count >= 3 ? 'high' : 'medium',
          description: `Subagent '${agentType}' failed ${count} times`,
          evidence: `${count} failures out of ${this.session.subagentLinks.filter(l => l.agentType === agentType).length} spawns`,
          suggestedFix: 'Review subagent configuration or task delegation logic',
        });
      }
    }

    // Check for high overall subagent failure rate
    const totalSubagents = this.session.subagentLinks.length;
    if (totalSubagents >= 3 && subagentFailures.length / totalSubagents > 0.5) {
      this.addInefficiency({
        type: 'subagent_inefficiency',
        severity: 'high',
        description: `High subagent failure rate: ${Math.round((subagentFailures.length / totalSubagents) * 100)}%`,
        evidence: `${subagentFailures.length} of ${totalSubagents} subagents failed`,
        suggestedFix: 'Check task complexity and subagent capabilities',
      });
    }
  }

  /**
   * Detect when approaching context token limit.
   */
  private detectContextLimitWarning(): void {
    // Estimate typical context limits (Claude: 200k, GPT-4: 128k)
    const estimatedLimit = 200000; // Conservative estimate

    // Calculate total tokens used in last iteration
    const lastIteration = this.session.iterations[this.session.iterations.length - 1];
    if (!lastIteration) return;

    // Sum up all input/output tokens to estimate context window usage
    const totalTokens = this.session.metrics.inputTokens;

    if (totalTokens > estimatedLimit * 0.9) {
      this.addInefficiency({
        type: 'context_limit_warning',
        severity: 'critical',
        description: `Context window critically full: ~${Math.round((totalTokens / estimatedLimit) * 100)}% used`,
        evidence: `Estimated ${totalTokens.toLocaleString()} tokens used (limit ~${estimatedLimit.toLocaleString()})`,
        suggestedFix: 'Enable auto-compaction or start a new session',
      });
    } else if (totalTokens > estimatedLimit * 0.7) {
      this.addInefficiency({
        type: 'context_limit_warning',
        severity: 'medium',
        description: `Context window filling up: ~${Math.round((totalTokens / estimatedLimit) * 100)}% used`,
        evidence: `Estimated ${totalTokens.toLocaleString()} tokens used (limit ~${estimatedLimit.toLocaleString()})`,
        suggestedFix: 'Consider enabling auto-compaction',
      });
    }
  }

  /**
   * Detect patterns of tool timeouts.
   */
  private detectToolTimeoutPatterns(): void {
    const toolTimeouts = new Map<string, number[]>();

    for (const iter of this.session.iterations) {
      for (const tool of iter.tools) {
        if (tool.status === 'timeout') {
          const iters = toolTimeouts.get(tool.name) || [];
          iters.push(iter.number);
          toolTimeouts.set(tool.name, iters);
        }
      }
    }

    // Find tools that timeout repeatedly
    for (const [toolName, iterations] of toolTimeouts) {
      if (iterations.length >= 3) {
        this.addInefficiency({
          type: 'tool_timeout_patterns',
          severity: 'high',
          description: `Tool '${toolName}' timed out ${iterations.length} times`,
          evidence: `Timeouts in iterations: ${iterations.join(', ')}`,
          iterations,
          suggestedFix: 'Increase tool timeout or optimize tool implementation',
        });
      } else if (iterations.length >= 2) {
        this.addInefficiency({
          type: 'tool_timeout_patterns',
          severity: 'medium',
          description: `Tool '${toolName}' timed out ${iterations.length} times`,
          evidence: `Timeouts in iterations: ${iterations.join(', ')}`,
          iterations,
          suggestedFix: 'Monitor tool performance and consider increasing timeout',
        });
      }
    }

    // Check for overall timeout rate
    const totalToolCalls = this.session.iterations.reduce((sum, iter) => sum + iter.tools.length, 0);
    const totalTimeouts = Array.from(toolTimeouts.values()).reduce((sum, arr) => sum + arr.length, 0);

    if (totalToolCalls >= 10 && totalTimeouts / totalToolCalls > 0.2) {
      this.addInefficiency({
        type: 'tool_timeout_patterns',
        severity: 'high',
        description: `High tool timeout rate: ${Math.round((totalTimeouts / totalToolCalls) * 100)}%`,
        evidence: `${totalTimeouts} timeouts out of ${totalToolCalls} tool calls`,
        suggestedFix: 'Review global timeout settings and tool performance',
      });
    }
  }

  /**
   * Add an inefficiency to the list.
   */
  private addInefficiency(params: Omit<Inefficiency, 'id' | 'codeLocations'>): void {
    const id = `ineff-${++this.idCounter}`;
    const codeLocations = CODE_LOCATIONS[params.type] || [];

    this.inefficiencies.push({
      ...params,
      id,
      codeLocations,
    });
  }
}

/**
 * Factory function.
 */
export function createInefficiencyDetector(session: ParsedSession): InefficiencyDetector {
  return new InefficiencyDetector(session);
}
