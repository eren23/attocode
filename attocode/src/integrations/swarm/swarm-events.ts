/**
 * Swarm Event Types
 *
 * Event definitions for swarm mode observability and TUI integration.
 * These events are emitted through the existing agent event system.
 */

import type { SwarmStatus, SwarmExecutionStats, SwarmError, SwarmTask, OrchestratorDecision, ModelHealthRecord, VerificationResult, WaveReviewResult, WorkerRole, ArtifactInventory } from './types.js';

// ─── Swarm Events ──────────────────────────────────────────────────────────

export type SwarmEvent =
  | { type: 'swarm.start'; taskCount: number; waveCount: number; config: { maxConcurrency: number; totalBudget: number; maxCost: number } }
  | { type: 'swarm.tasks.loaded'; tasks: SwarmTask[] }
  | { type: 'swarm.wave.start'; wave: number; totalWaves: number; taskCount: number }
  | { type: 'swarm.wave.complete'; wave: number; totalWaves: number; completed: number; failed: number; skipped: number }
  | { type: 'swarm.task.dispatched'; taskId: string; description: string; model: string; workerName: string; toolCount: number; tools?: string[]; retryContext?: { previousScore: number; previousFeedback: string; attempt: number }; fromModel?: string; attempts?: number }
  | { type: 'swarm.task.completed'; taskId: string; success: boolean; tokensUsed: number; costUsed: number; durationMs: number; qualityScore?: number; qualityFeedback?: string; output?: string; closureReport?: import('../agent-registry.js').StructuredClosureReport; toolCalls?: number }
  | { type: 'swarm.task.failed'; taskId: string; error: string; attempt: number; maxAttempts: number; willRetry: boolean; toolCalls?: number; failoverModel?: string; failureMode?: string }
  | { type: 'swarm.task.skipped'; taskId: string; reason: string }
  | { type: 'swarm.quality.rejected'; taskId: string; score: number; feedback: string; artifactCount: number; outputLength: number; preFlightReject?: boolean; filesOnDisk?: number }
  | { type: 'swarm.budget.update'; tokensUsed: number; tokensTotal: number; costUsed: number; costTotal: number }
  | { type: 'swarm.status'; status: SwarmStatus }
  | { type: 'swarm.complete'; stats: SwarmExecutionStats; errors: SwarmError[]; artifactInventory?: ArtifactInventory }
  | { type: 'swarm.error'; error: string; phase: string; taskId?: string }
  // V2: Planning, review, verification events
  | { type: 'swarm.plan.complete'; criteriaCount: number; hasIntegrationPlan: boolean }
  | { type: 'swarm.review.start'; wave: number }
  | { type: 'swarm.review.complete'; wave: number; assessment: WaveReviewResult['assessment']; fixupCount: number }
  | { type: 'swarm.verify.start'; stepCount: number }
  | { type: 'swarm.verify.step'; stepIndex: number; description: string; passed: boolean }
  | { type: 'swarm.verify.complete'; result: VerificationResult }
  | { type: 'swarm.worker.stuck'; taskId: string; repeatedTool: string; count: number }
  | { type: 'swarm.model.failover'; taskId: string; fromModel: string; toModel: string; reason: string }
  | { type: 'swarm.model.health'; record: ModelHealthRecord }
  | { type: 'swarm.state.checkpoint'; sessionId: string; wave: number }
  | { type: 'swarm.state.resume'; sessionId: string; fromWave: number }
  | { type: 'swarm.orchestrator.decision'; decision: OrchestratorDecision }
  | { type: 'swarm.fixup.spawned'; taskId: string; fixesTaskId: string; description: string }
  | { type: 'swarm.circuit.open'; recentCount: number; pauseMs: number }
  | { type: 'swarm.circuit.closed' }
  // V3: Hierarchy role events
  | { type: 'swarm.role.action'; role: WorkerRole; action: 'review' | 'quality-gate' | 'verify' | 'plan'; model: string; taskId?: string; wave?: number }
  // V8: Wave failure recovery
  | { type: 'swarm.wave.allFailed'; wave: number }
  // V9: Phase progress for dashboard visibility during decomposition/planning
  | { type: 'swarm.phase.progress'; phase: 'decomposing' | 'planning' | 'scheduling'; message: string }
  // V8: Orchestrator LLM call tracking
  | { type: 'swarm.orchestrator.llm'; model: string; purpose: string; tokens: number; cost: number }
  // V10: Per-attempt record for full decision traceability
  | { type: 'swarm.task.attempt'; taskId: string; attempt: number; model: string;
      success: boolean; durationMs: number; toolCalls: number;
      failureMode?: string; qualityScore?: number; output?: string }
  // V10: Resilience recovery attempt record
  | { type: 'swarm.task.resilience'; taskId: string;
      strategy: 'micro-decompose' | 'degraded-acceptance' | 'auto-split' | 'none';
      succeeded: boolean; reason: string; artifactsFound: number; toolCalls: number }
  // F15: All-probe-failure abort
  | { type: 'swarm.abort'; reason: string }
  // Mid-swarm re-planning and stall detection
  | { type: 'swarm.replan'; stuckCount: number; newTaskCount: number }
  | { type: 'swarm.stall'; progressRatio: number; attempted: number; completed: number };

/**
 * Type guard for swarm events.
 */
export function isSwarmEvent(event: { type: string }): event is SwarmEvent {
  return event.type.startsWith('swarm.');
}

/**
 * Format a swarm event for log display.
 */
export function formatSwarmEvent(event: SwarmEvent): string {
  switch (event.type) {
    case 'swarm.start':
      return `Swarm started: ${event.taskCount} tasks in ${event.waveCount} waves (max ${event.config.maxConcurrency} concurrent)`;
    case 'swarm.tasks.loaded':
      return `Tasks loaded: ${event.tasks.length} tasks with dependency graph`;
    case 'swarm.wave.start':
      return `Wave ${event.wave}/${event.totalWaves}: dispatching ${event.taskCount} tasks`;
    case 'swarm.wave.complete':
      return `Wave ${event.wave}/${event.totalWaves} complete: ${event.completed} done, ${event.failed} failed, ${event.skipped} skipped`;
    case 'swarm.task.dispatched':
      return `Task ${event.taskId} → ${event.workerName} (${event.model}${event.fromModel ? `, was ${event.fromModel}` : ''}): ${event.description.slice(0, 80)}${event.toolCount >= 0 ? ` [${event.toolCount} tools]` : ''}`;
    case 'swarm.task.completed':
      return `Task ${event.taskId} ${event.success ? 'completed' : 'failed'} (${event.tokensUsed} tokens, $${event.costUsed.toFixed(4)}, ${(event.durationMs / 1000).toFixed(1)}s)`;
    case 'swarm.task.failed':
      return `Task ${event.taskId} failed (attempt ${event.attempt}/${event.maxAttempts}): ${event.error}${event.willRetry ? ' — will retry' : ''}${event.toolCalls !== undefined ? ` [${event.toolCalls === -1 ? 'timeout' : event.toolCalls + ' tools'}]` : ''}`;
    case 'swarm.task.skipped':
      return `Task ${event.taskId} skipped: ${event.reason}`;
    case 'swarm.quality.rejected':
      return `Task ${event.taskId} rejected (score ${event.score}/5): ${event.feedback} [artifacts: ${event.artifactCount}, output: ${event.outputLength} chars${event.preFlightReject ? ', pre-flight' : ''}]`;
    case 'swarm.budget.update':
      return `Budget: ${(event.tokensUsed / 1000).toFixed(0)}k/${(event.tokensTotal / 1000).toFixed(0)}k tokens, $${event.costUsed.toFixed(4)}/$${event.costTotal.toFixed(2)}`;
    case 'swarm.complete': {
      const base = `Swarm complete: ${event.stats.completedTasks}/${event.stats.totalTasks} tasks, ${(event.stats.totalTokens / 1000).toFixed(0)}k tokens, $${event.stats.totalCost.toFixed(4)}`;
      const artifacts = event.artifactInventory?.totalFiles
        ? `, ${event.artifactInventory.totalFiles} files on disk (${(event.artifactInventory.totalBytes / 1024).toFixed(1)}KB)`
        : '';
      return base + artifacts;
    }
    case 'swarm.status':
      return `Swarm: wave ${event.status.currentWave}/${event.status.totalWaves}, ${event.status.activeWorkers.length} workers active`;
    case 'swarm.error':
      return `Swarm error in ${event.phase}: ${event.error}`;
    // V2 events
    case 'swarm.plan.complete':
      return `Plan created: ${event.criteriaCount} acceptance criteria${event.hasIntegrationPlan ? ', integration test plan ready' : ''}`;
    case 'swarm.review.start':
      return `Reviewing wave ${event.wave} outputs...`;
    case 'swarm.review.complete':
      return `Wave ${event.wave} review: ${event.assessment}${event.fixupCount > 0 ? ` (${event.fixupCount} fix-up tasks spawned)` : ''}`;
    case 'swarm.verify.start':
      return `Running ${event.stepCount} verification steps...`;
    case 'swarm.verify.step':
      return `Verify step ${event.stepIndex + 1}: ${event.description} — ${event.passed ? 'PASS' : 'FAIL'}`;
    case 'swarm.verify.complete':
      return `Verification ${event.result.passed ? 'PASSED' : 'FAILED'}: ${event.result.summary}`;
    case 'swarm.worker.stuck':
      return `Worker stuck: task ${event.taskId} repeated ${event.repeatedTool} ${event.count}x`;
    case 'swarm.model.failover':
      return `Model failover: task ${event.taskId} ${event.fromModel} → ${event.toModel} (${event.reason})`;
    case 'swarm.model.health':
      return `Model health: ${event.record.model} — ${event.record.healthy ? 'healthy' : 'unhealthy'} (${event.record.successes}ok/${event.record.failures}fail/${event.record.rateLimits}rl)`;
    case 'swarm.state.checkpoint':
      return `Checkpoint saved: session ${event.sessionId}, wave ${event.wave}`;
    case 'swarm.state.resume':
      return `Resuming session ${event.sessionId} from wave ${event.fromWave}`;
    case 'swarm.orchestrator.decision':
      return `Decision [${event.decision.phase}]: ${event.decision.decision}`;
    case 'swarm.fixup.spawned':
      return `Fix-up task ${event.taskId} → fixes ${event.fixesTaskId}: ${event.description.slice(0, 80)}`;
    case 'swarm.circuit.open':
      return `Circuit breaker OPEN: ${event.recentCount} rate limits in 30s, pausing dispatch for ${(event.pauseMs / 1000).toFixed(0)}s`;
    case 'swarm.circuit.closed':
      return `Circuit breaker CLOSED: dispatch resumed`;
    case 'swarm.role.action': {
      const roleLabel = event.role.charAt(0).toUpperCase() + event.role.slice(1);
      return `${roleLabel} ${event.action}: ${event.model.split('/').pop() ?? event.model}${event.taskId ? ` (task ${event.taskId})` : ''}`;
    }
    case 'swarm.wave.allFailed':
      return `Wave ${event.wave}: ALL tasks failed — attempting recovery`;
    case 'swarm.phase.progress':
      return `[${event.phase}] ${event.message}`;
    case 'swarm.orchestrator.llm':
      return `Orchestrator LLM (${event.purpose}): ${event.model.split('/').pop() ?? event.model}, ${event.tokens} tokens, $${event.cost.toFixed(4)}`;
    case 'swarm.task.attempt':
      return `Task ${event.taskId} attempt ${event.attempt}: ${event.success ? 'success' : 'failed'} (${event.model.split('/').pop() ?? event.model}, ${(event.durationMs / 1000).toFixed(1)}s, ${event.toolCalls === -1 ? 'timeout' : event.toolCalls + ' tools'}${event.failureMode ? `, ${event.failureMode}` : ''})`;
    case 'swarm.task.resilience':
      return `Task ${event.taskId} resilience: ${event.strategy} — ${event.succeeded ? 'recovered' : 'failed'} (${event.reason}, ${event.artifactsFound} artifacts, ${event.toolCalls} tools)`;
    case 'swarm.abort':
      return `Swarm ABORTED: ${event.reason}`;
    case 'swarm.replan':
      return `Swarm re-planned: ${event.stuckCount} stuck tasks → ${event.newTaskCount} new tasks`;
    case 'swarm.stall':
      return `Swarm stalled: ${event.completed}/${event.attempted} tasks succeeded (${(event.progressRatio * 100).toFixed(0)}%)`;
  }
}
