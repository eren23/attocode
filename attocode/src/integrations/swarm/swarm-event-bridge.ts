/**
 * Swarm Event Bridge
 *
 * Bridges swarm events to the filesystem for the trace dashboard to consume.
 * Writes events to .agent/swarm-live/events.jsonl (append-only)
 * and state snapshots to .agent/swarm-live/state.json (overwritten).
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { SwarmOrchestrator } from './swarm-orchestrator.js';
import type { SwarmEvent } from './swarm-events.js';
import type { SwarmStatus, SwarmTask, OrchestratorDecision, ModelHealthRecord, VerificationResult, SwarmPlan } from './types.js';

// ─── Types ────────────────────────────────────────────────────────────────────

/** Timestamped event written to events.jsonl */
export interface TimestampedSwarmEvent {
  ts: string;
  seq: number;
  event: SwarmEvent;
}

/** Full live state snapshot written to state.json */
export interface SwarmLiveState {
  active: boolean;
  updatedAt: string;
  lastSeq: number;
  status: SwarmStatus | null;
  tasks: SwarmTask[];
  edges: [string, string][];
  config: {
    maxConcurrency: number;
    totalBudget: number;
    maxCost: number;
    workerModels: string[];
    hierarchy?: {
      manager?: { model?: string };
      judge?: { model?: string };
    };
  };
  timeline: Array<{
    ts: string;
    seq: number;
    type: string;
    tokensUsed: number;
    costUsed: number;
    completedCount: number;
    failedCount: number;
  }>;
  errors: Array<{
    ts: string;
    taskId?: string;
    phase: string;
    message: string;
  }>;
  // V2: Extended state
  decisions: OrchestratorDecision[];
  plan?: { acceptanceCriteria: SwarmPlan['acceptanceCriteria']; integrationTestPlan?: SwarmPlan['integrationTestPlan'] };
  verification?: VerificationResult;
  modelHealth: ModelHealthRecord[];
  workerLogFiles: string[];
}

export interface SwarmEventBridgeOptions {
  /** Output directory for live files (default: '.agent/swarm-live') */
  outputDir?: string;
  /** Max lines before rotating events.jsonl (default: 5000) */
  maxLines?: number;
  /** Max state writes per second (default: 5) */
  maxStateWritesPerSec?: number;
}

// ─── Implementation ───────────────────────────────────────────────────────────

export class SwarmEventBridge {
  private outputDir: string;
  private maxLines: number;
  private minStateIntervalMs: number;

  private seq = 0;
  private lineCount = 0;
  private eventsStream: fs.WriteStream | null = null;
  private lastStateWrite = 0;
  private stateWriteTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingState: SwarmLiveState | null = null;
  private closed = false;

  // Accumulated state for building snapshots
  private tasks: Map<string, SwarmTask> = new Map();
  private edges: [string, string][] = [];
  private config = { maxConcurrency: 0, totalBudget: 0, maxCost: 0, workerModels: [] as string[] };
  private timeline: SwarmLiveState['timeline'] = [];
  private errors: SwarmLiveState['errors'] = [];
  private lastStatus: SwarmStatus | null = null;
  // V2
  private decisions: OrchestratorDecision[] = [];
  private plan?: SwarmLiveState['plan'];
  private verification?: VerificationResult;
  private modelHealth: ModelHealthRecord[] = [];
  private workerLogFiles: string[] = [];

  constructor(options: SwarmEventBridgeOptions = {}) {
    this.outputDir = options.outputDir ?? '.agent/swarm-live';
    this.maxLines = options.maxLines ?? 5000;
    this.minStateIntervalMs = 1000 / (options.maxStateWritesPerSec ?? 5);
  }

  /**
   * Attach to an orchestrator and subscribe to its events.
   * Returns an unsubscribe function.
   */
  attach(orchestrator: SwarmOrchestrator): () => void {
    return orchestrator.subscribe((event) => {
      this.handleEvent(event);
    });
  }

  /**
   * Handle a single swarm event.
   */
  private handleEvent(event: SwarmEvent): void {
    if (this.closed) return;

    const ts = new Date().toISOString();
    this.seq++;

    // Initialize on swarm.start
    if (event.type === 'swarm.start') {
      this.initOutputDir();
      this.config = {
        maxConcurrency: event.config.maxConcurrency,
        totalBudget: event.config.totalBudget,
        maxCost: event.config.maxCost,
        workerModels: [],
      };
      this.tasks.clear();
      this.edges = [];
      this.timeline = [];
      this.errors = [];
      this.lastStatus = null;
      this.seq = 1;
      this.lineCount = 0;
    }

    // Append to events.jsonl
    this.appendEvent({ ts, seq: this.seq, event });

    // Update accumulated state based on event type
    this.updateAccumulatedState(event, ts);

    // Write state snapshot (debounced for status/task events, immediate for milestones)
    const immediateTriggers = ['swarm.complete', 'swarm.plan.complete', 'swarm.review.complete', 'swarm.verify.complete', 'swarm.state.checkpoint'];
    const debouncedTriggers = [
      'swarm.task.dispatched', 'swarm.task.completed', 'swarm.task.failed', 'swarm.task.skipped',
      'swarm.quality.rejected',
      'swarm.budget.update', 'swarm.wave.start', 'swarm.wave.complete', 'swarm.phase.progress',
    ];
    if (immediateTriggers.includes(event.type)) {
      this.writeStateDebouncedOrImmediate(true);
    } else if (event.type === 'swarm.status' || debouncedTriggers.includes(event.type)) {
      this.writeStateDebouncedOrImmediate(false);
    }
  }

  /**
   * Update accumulated state from an event.
   */
  private updateAccumulatedState(event: SwarmEvent, ts: string): void {
    switch (event.type) {
      case 'swarm.status':
        this.lastStatus = event.status;
        // Extract tasks from status if we have them via the queue
        break;

      case 'swarm.tasks.loaded':
        this.setTasks(event.tasks);
        // Write state immediately so dashboard picks up the DAG
        this.writeStateDebouncedOrImmediate(true);
        break;

      case 'swarm.task.dispatched':
        this.updateTask(event.taskId, {
          status: 'dispatched',
          assignedModel: event.model,
          description: event.description,
          toolCount: event.toolCount,
          tools: event.tools,
          retryContext: event.retryContext,
        });
        if (!this.config.workerModels.includes(event.model)) {
          this.config.workerModels.push(event.model);
        }
        this.timeline.push({
          ts,
          seq: this.seq,
          type: 'task.dispatched',
          tokensUsed: this.lastStatus?.budget.tokensUsed ?? 0,
          costUsed: this.lastStatus?.budget.costUsed ?? 0,
          completedCount: this.lastStatus?.queue.completed ?? 0,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        break;

      case 'swarm.task.completed': {
        const existingTask = this.tasks.get(event.taskId);
        this.updateTask(event.taskId, {
          status: 'completed',
          result: {
            success: event.success,
            output: event.output ?? '',
            tokensUsed: event.tokensUsed,
            costUsed: event.costUsed,
            durationMs: event.durationMs,
            qualityScore: event.qualityScore,
            qualityFeedback: event.qualityFeedback,
            model: existingTask?.assignedModel ?? '',
          },
        });
        this.timeline.push({
          ts,
          seq: this.seq,
          type: 'task.completed',
          tokensUsed: event.tokensUsed,
          costUsed: event.costUsed,
          completedCount: (this.lastStatus?.queue.completed ?? 0) + 1,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        // V5: Write per-task detail file for drill-down in dashboard
        // Always write — even if output is empty, we still have quality/closure data
        this.writeTaskDetail(event.taskId, {
          taskId: event.taskId,
          output: event.output ?? '',
          qualityFeedback: event.qualityFeedback,
          closureReport: event.closureReport,
          toolCalls: event.toolCalls,
        });
        break;
      }

      case 'swarm.task.failed':
        this.updateTask(event.taskId, { status: event.willRetry ? 'ready' : 'failed' });
        // Write detail file for failed tasks too
        this.writeTaskDetail(event.taskId, {
          taskId: event.taskId,
          output: `FAILED (attempt ${event.attempt}/${event.maxAttempts}): ${event.error}`,
          toolCalls: event.toolCalls ?? -1,
          failoverModel: event.failoverModel,
        });
        this.errors.push({
          ts,
          taskId: event.taskId,
          phase: 'execution',
          message: event.error,
        });
        break;

      case 'swarm.task.skipped':
        this.updateTask(event.taskId, { status: 'skipped' });
        break;

      case 'swarm.quality.rejected':
        this.updateTask(event.taskId, { status: 'failed' });
        this.errors.push({
          ts,
          taskId: event.taskId,
          phase: 'quality-gate',
          message: `Score ${event.score}/5: ${event.feedback} [artifacts: ${event.artifactCount}, output: ${event.outputLength} chars${event.preFlightReject ? ', pre-flight reject' : ''}]`,
        });
        break;

      case 'swarm.budget.update':
        this.timeline.push({
          ts,
          seq: this.seq,
          type: 'budget.update',
          tokensUsed: event.tokensUsed,
          costUsed: event.costUsed,
          completedCount: this.lastStatus?.queue.completed ?? 0,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        break;

      case 'swarm.error':
        this.errors.push({
          ts,
          taskId: event.taskId,
          phase: event.phase,
          message: event.error,
        });
        break;

      case 'swarm.complete':
        // Update phase to completed in the last status so state.json reflects final state
        if (this.lastStatus) {
          this.lastStatus = { ...this.lastStatus, phase: 'completed' };
        }
        break;

      // V2 events
      case 'swarm.plan.complete':
        this.timeline.push({
          ts, seq: this.seq, type: 'plan.complete',
          tokensUsed: this.lastStatus?.budget.tokensUsed ?? 0,
          costUsed: this.lastStatus?.budget.costUsed ?? 0,
          completedCount: this.lastStatus?.queue.completed ?? 0,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        break;

      case 'swarm.review.start':
      case 'swarm.review.complete':
        this.timeline.push({
          ts, seq: this.seq, type: event.type.replace('swarm.', ''),
          tokensUsed: this.lastStatus?.budget.tokensUsed ?? 0,
          costUsed: this.lastStatus?.budget.costUsed ?? 0,
          completedCount: this.lastStatus?.queue.completed ?? 0,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        break;

      case 'swarm.verify.start':
      case 'swarm.verify.step':
        this.timeline.push({
          ts, seq: this.seq, type: event.type.replace('swarm.', ''),
          tokensUsed: this.lastStatus?.budget.tokensUsed ?? 0,
          costUsed: this.lastStatus?.budget.costUsed ?? 0,
          completedCount: this.lastStatus?.queue.completed ?? 0,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        break;

      case 'swarm.verify.complete':
        this.verification = event.result;
        break;

      case 'swarm.model.health':
        // Update or add model health record
        this.modelHealth = this.modelHealth.filter(r => r.model !== event.record.model);
        this.modelHealth.push(event.record);
        break;

      case 'swarm.model.failover':
        this.timeline.push({
          ts, seq: this.seq, type: 'model.failover',
          tokensUsed: this.lastStatus?.budget.tokensUsed ?? 0,
          costUsed: this.lastStatus?.budget.costUsed ?? 0,
          completedCount: this.lastStatus?.queue.completed ?? 0,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        break;

      case 'swarm.orchestrator.decision':
        this.decisions.push(event.decision);
        break;

      case 'swarm.role.action':
        // V3: Record hierarchy role actions in timeline
        this.timeline.push({
          ts, seq: this.seq, type: `role.${event.role}.${event.action}`,
          tokensUsed: this.lastStatus?.budget.tokensUsed ?? 0,
          costUsed: this.lastStatus?.budget.costUsed ?? 0,
          completedCount: this.lastStatus?.queue.completed ?? 0,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        break;

      case 'swarm.phase.progress':
      case 'swarm.fixup.spawned':
      case 'swarm.worker.stuck':
      case 'swarm.state.checkpoint':
      case 'swarm.state.resume':
        // Record in timeline
        this.timeline.push({
          ts, seq: this.seq, type: event.type.replace('swarm.', ''),
          tokensUsed: this.lastStatus?.budget.tokensUsed ?? 0,
          costUsed: this.lastStatus?.budget.costUsed ?? 0,
          completedCount: this.lastStatus?.queue.completed ?? 0,
          failedCount: this.lastStatus?.queue.failed ?? 0,
        });
        break;
    }
  }

  /**
   * Update a task in the accumulated map (partial update).
   */
  private updateTask(taskId: string, update: Partial<SwarmTask>): void {
    const existing = this.tasks.get(taskId);
    if (existing) {
      Object.assign(existing, update);
    } else {
      this.tasks.set(taskId, {
        id: taskId,
        description: update.description ?? '',
        type: 'implement',
        dependencies: [],
        status: update.status ?? 'pending',
        complexity: 5,
        wave: 0,
        attempts: 0,
        ...update,
      } as SwarmTask);
    }
  }

  /**
   * Write a per-task detail JSON file for dashboard drill-down.
   */
  private writeTaskDetail(taskId: string, detail: Record<string, unknown>): void {
    try {
      const tasksDir = path.join(this.outputDir, 'tasks');
      fs.mkdirSync(tasksDir, { recursive: true });
      const taskFile = path.join(tasksDir, `${taskId}.json`);
      fs.writeFileSync(taskFile, JSON.stringify(detail));
    } catch {
      // Best effort — don't crash the bridge
    }
  }

  /**
   * Build the current SwarmLiveState snapshot.
   */
  private buildState(): SwarmLiveState {
    return {
      active: this.lastStatus?.phase !== 'completed' && this.lastStatus?.phase !== 'failed',
      updatedAt: new Date().toISOString(),
      lastSeq: this.seq,
      status: this.lastStatus,
      tasks: Array.from(this.tasks.values()),
      edges: this.edges,
      config: { ...this.config },
      timeline: this.timeline.slice(-200), // Keep last 200 entries
      errors: this.errors.slice(-100),
      // V2
      decisions: this.decisions.slice(-100),
      plan: this.plan,
      verification: this.verification,
      modelHealth: this.modelHealth,
      workerLogFiles: this.workerLogFiles,
    };
  }

  // ─── File I/O ─────────────────────────────────────────────────────────────

  /**
   * Initialize output directory and reset files.
   */
  private initOutputDir(): void {
    fs.mkdirSync(this.outputDir, { recursive: true });

    // Archive old events file if it exists
    const eventsPath = path.join(this.outputDir, 'events.jsonl');
    if (fs.existsSync(eventsPath)) {
      const archivePath = path.join(this.outputDir, `events-${Date.now()}.jsonl`);
      try {
        fs.renameSync(eventsPath, archivePath);
      } catch {
        // Best effort
      }
    }

    // Close existing stream
    if (this.eventsStream) {
      this.eventsStream.end();
    }

    this.eventsStream = fs.createWriteStream(eventsPath, { flags: 'a' });
    this.lineCount = 0;
  }

  /**
   * Append a timestamped event to events.jsonl.
   */
  private appendEvent(entry: TimestampedSwarmEvent): void {
    if (!this.eventsStream) {
      // Lazy init if swarm.start wasn't the first event
      this.initOutputDir();
    }

    const line = JSON.stringify(entry) + '\n';
    this.eventsStream!.write(line);
    this.lineCount++;

    // Rotate if over limit
    if (this.lineCount >= this.maxLines) {
      this.rotateEvents();
    }
  }

  /**
   * Rotate events.jsonl by archiving and starting fresh.
   */
  private rotateEvents(): void {
    const eventsPath = path.join(this.outputDir, 'events.jsonl');
    const archivePath = path.join(this.outputDir, `events-${Date.now()}.jsonl`);

    // Close current stream
    this.eventsStream?.end();

    try {
      fs.renameSync(eventsPath, archivePath);
    } catch {
      // Best effort
    }

    this.eventsStream = fs.createWriteStream(eventsPath, { flags: 'a' });
    this.lineCount = 0;
  }

  /**
   * Write state.json, debounced to max N writes/sec.
   */
  private writeStateDebouncedOrImmediate(immediate: boolean): void {
    const state = this.buildState();

    if (immediate) {
      // Cancel any pending debounced write — the immediate write supersedes it
      if (this.stateWriteTimer) {
        clearTimeout(this.stateWriteTimer);
        this.stateWriteTimer = null;
        this.pendingState = null;
      }
      this.writeStateSync(state);
      return;
    }

    const now = Date.now();
    const elapsed = now - this.lastStateWrite;

    if (elapsed >= this.minStateIntervalMs) {
      this.writeStateSync(state);
    } else {
      // Debounce: schedule write for later
      this.pendingState = state;
      if (!this.stateWriteTimer) {
        this.stateWriteTimer = setTimeout(() => {
          this.stateWriteTimer = null;
          if (this.pendingState) {
            this.writeStateSync(this.pendingState);
            this.pendingState = null;
          }
        }, this.minStateIntervalMs - elapsed);
      }
    }
  }

  /**
   * Synchronously write state.json.
   */
  private writeStateSync(state: SwarmLiveState): void {
    const statePath = path.join(this.outputDir, 'state.json');
    try {
      fs.writeFileSync(statePath, JSON.stringify(state, null, 2));
      this.lastStateWrite = Date.now();
    } catch {
      // Best effort - don't crash the agent
    }
  }

  /**
   * Close the bridge, flush pending writes.
   */
  close(): void {
    this.closed = true;

    if (this.stateWriteTimer) {
      clearTimeout(this.stateWriteTimer);
      this.stateWriteTimer = null;
    }

    // Write final state
    if (this.pendingState) {
      this.writeStateSync(this.pendingState);
      this.pendingState = null;
    }

    // Close events stream
    if (this.eventsStream) {
      this.eventsStream.end();
      this.eventsStream = null;
    }
  }

  /**
   * Set task list and dependency edges from the orchestrator's task queue.
   * Call this after decomposition to populate the DAG.
   */
  setTasks(tasks: SwarmTask[]): void {
    this.tasks.clear();
    this.edges = [];
    for (const task of tasks) {
      this.tasks.set(task.id, { ...task });
      for (const dep of task.dependencies) {
        this.edges.push([dep, task.id]);
      }
    }
  }
}
