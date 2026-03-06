/**
 * Timeline View
 *
 * Generates a chronological view of all events in a trace session.
 */

import type { ParsedSession, TimelineEntry } from '../types.js';

/**
 * Timeline view data.
 */
export interface TimelineViewData {
  /** Session start time */
  startTime: Date;
  /** Total duration in ms */
  totalDuration: number;
  /** All timeline entries */
  entries: TimelineEntry[];
}

/**
 * Generates timeline view data.
 */
export class TimelineView {
  private session: ParsedSession;

  constructor(session: ParsedSession) {
    this.session = session;
  }

  /**
   * Generate timeline view data.
   */
  generate(): TimelineViewData {
    const entries: TimelineEntry[] = [];
    const startTime = this.session.startTime;

    // Session start
    entries.push({
      timestamp: startTime,
      relativeMs: 0,
      type: 'session.start',
      description: `Session started: ${this.session.task.slice(0, 50)}...`,
      importance: 'high',
      details: {
        model: this.session.model,
        task: this.session.task,
      },
    });

    // Add iteration events
    for (const iter of this.session.iterations) {
      const iterStartMs = iter.startTime.getTime() - startTime.getTime();

      // Iteration start
      entries.push({
        timestamp: iter.startTime,
        relativeMs: iterStartMs,
        type: 'iteration.start',
        description: `Iteration ${iter.number} started`,
        importance: 'normal',
        iteration: iter.number,
      });

      // LLM call
      if (iter.llm) {
        entries.push({
          timestamp: new Date(iter.startTime.getTime() + 10), // Approximate
          relativeMs: iterStartMs + 10,
          type: 'llm.call',
          description: `LLM call (${iter.llm.inputTokens} in, ${iter.llm.outputTokens} out)`,
          durationMs: iter.llm.durationMs,
          importance: 'normal',
          iteration: iter.number,
          details: {
            model: iter.llm.model,
            cacheHitRate: iter.llm.cacheHitRate,
            toolCalls: iter.llm.toolCalls.length,
          },
        });
      }

      // Thinking
      if (iter.thinking) {
        entries.push({
          timestamp: new Date(iter.startTime.getTime() + 20),
          relativeMs: iterStartMs + 20,
          type: 'llm.thinking',
          description: `Thinking (${iter.thinking.estimatedTokens} tokens)`,
          importance: 'normal',
          iteration: iter.number,
          details: {
            summarized: iter.thinking.summarized,
          },
        });
      }

      // Tool executions
      let toolOffset = 100;
      for (const tool of iter.tools) {
        const isError = tool.status !== 'success';
        entries.push({
          timestamp: new Date(iter.startTime.getTime() + toolOffset),
          relativeMs: iterStartMs + toolOffset,
          type: 'tool.execution',
          description: `${tool.name} (${tool.status})`,
          durationMs: tool.durationMs,
          importance: isError ? 'high' : 'normal',
          iteration: iter.number,
          details: {
            executionId: tool.executionId,
            status: tool.status,
            resultSize: tool.resultSize,
            input: tool.input,
            outputPreview: tool.outputPreview,
            errorMessage: tool.errorMessage,
          },
        });
        toolOffset += tool.durationMs + 10;
      }

      // Decisions
      for (const decision of iter.decisions) {
        entries.push({
          timestamp: new Date(iter.startTime.getTime() + 50),
          relativeMs: iterStartMs + 50,
          type: 'decision',
          description: `${decision.type}: ${decision.decision.slice(0, 40)}`,
          importance: decision.outcome === 'blocked' ? 'high' : 'low',
          iteration: iter.number,
          details: {
            outcome: decision.outcome,
            reasoning: decision.reasoning,
          },
        });
      }

      // Iteration end
      if (iter.endTime) {
        const iterEndMs = iter.endTime.getTime() - startTime.getTime();
        entries.push({
          timestamp: iter.endTime,
          relativeMs: iterEndMs,
          type: 'iteration.end',
          description: `Iteration ${iter.number} ended`,
          durationMs: iter.durationMs,
          importance: 'normal',
          iteration: iter.number,
          details: {
            tokens: iter.metrics.inputTokens + iter.metrics.outputTokens,
            cost: iter.metrics.cost,
          },
        });
      }
    }

    // Subagent events
    for (const link of this.session.subagentLinks) {
      entries.push({
        timestamp: startTime, // Would need actual timestamp
        relativeMs: 0,
        type: 'subagent.spawn',
        description: `Spawned ${link.agentType}: ${link.task.slice(0, 40)}`,
        durationMs: link.durationMs,
        importance: 'high',
        details: {
          success: link.success,
          tokensUsed: link.tokensUsed,
        },
      });
    }

    // Errors
    for (const error of this.session.errors) {
      entries.push({
        timestamp: error.timestamp,
        relativeMs: error.timestamp.getTime() - startTime.getTime(),
        type: 'error',
        description: `Error: ${error.message.slice(0, 50)}`,
        importance: 'high',
        details: {
          code: error.code,
          context: error.context,
          recoverable: error.recoverable,
        },
      });
    }

    // Swarm events
    if (this.session.swarmData) {
      const swarm = this.session.swarmData;

      // Swarm start
      if (swarm.config) {
        entries.push({
          timestamp: startTime,
          relativeMs: 0,
          type: 'swarm.start',
          description: `Swarm started: ${swarm.tasks.length} tasks, max ${swarm.config.maxConcurrency} concurrent`,
          importance: 'high',
          details: { config: swarm.config },
        });
      }

      // Wave events
      for (const wave of swarm.waves) {
        const relativeMs = wave.timestamp.getTime() - startTime.getTime();
        if (wave.phase === 'start') {
          entries.push({
            timestamp: wave.timestamp,
            relativeMs,
            type: 'swarm.wave.start',
            description: `Wave ${wave.wave}: dispatching ${wave.taskCount} tasks`,
            importance: 'normal',
            details: { wave: wave.wave, taskCount: wave.taskCount },
          });
        } else {
          entries.push({
            timestamp: wave.timestamp,
            relativeMs,
            type: 'swarm.wave.complete',
            description: `Wave ${wave.wave} complete: ${wave.completed ?? 0} done, ${wave.failed ?? 0} failed`,
            importance: wave.failed ? 'high' : 'normal',
            details: { wave: wave.wave, completed: wave.completed, failed: wave.failed },
          });
        }
      }

      // Quality rejections
      for (const rejection of swarm.qualityRejections) {
        const relativeMs = rejection.timestamp.getTime() - startTime.getTime();
        entries.push({
          timestamp: rejection.timestamp,
          relativeMs,
          type: 'swarm.quality',
          description: `Task ${rejection.taskId} rejected (score ${rejection.score}/5)`,
          importance: 'high',
          details: { taskId: rejection.taskId, score: rejection.score, feedback: rejection.feedback },
        });
      }

      // Verification
      if (swarm.verification) {
        entries.push({
          timestamp: this.session.endTime || startTime,
          relativeMs: this.session.durationMs || 0,
          type: 'swarm.verification',
          description: `Verification ${swarm.verification.passed ? 'PASSED' : 'FAILED'}: ${swarm.verification.summary}`,
          importance: 'high',
          details: {
            passed: swarm.verification.passed,
            steps: swarm.verification.steps.length,
          },
        });
      }

      // Swarm complete
      if (swarm.stats) {
        entries.push({
          timestamp: this.session.endTime || startTime,
          relativeMs: this.session.durationMs || 0,
          type: 'swarm.complete',
          description: `Swarm complete: ${swarm.stats.completedTasks}/${swarm.stats.totalTasks} tasks, ${(swarm.stats.totalTokens / 1000).toFixed(0)}k tokens`,
          importance: 'high',
          details: { stats: swarm.stats },
        });
      }
    }

    // Session end
    if (this.session.endTime) {
      entries.push({
        timestamp: this.session.endTime,
        relativeMs: this.session.durationMs || 0,
        type: 'session.end',
        description: `Session ${this.session.status}`,
        importance: 'high',
        details: {
          status: this.session.status,
          iterations: this.session.metrics.iterations,
          totalTokens: this.session.metrics.inputTokens + this.session.metrics.outputTokens,
        },
      });
    }

    // Sort by timestamp
    entries.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());

    return {
      startTime,
      totalDuration: this.session.durationMs || 0,
      entries,
    };
  }
}

/**
 * Factory function.
 */
export function createTimelineView(session: ParsedSession): TimelineView {
  return new TimelineView(session);
}
