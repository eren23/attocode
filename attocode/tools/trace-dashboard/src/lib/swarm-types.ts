/**
 * Swarm Dashboard Types
 *
 * Dashboard-side type definitions for the swarm visualization.
 * These mirror the agent-side types but are independent to avoid cross-project imports.
 */

// ─── Task Status ──────────────────────────────────────────────────────────────

export type SwarmTaskStatus = 'pending' | 'ready' | 'dispatched' | 'completed' | 'failed' | 'skipped';

export type SwarmPhase = 'decomposing' | 'scheduling' | 'planning' | 'executing' | 'verifying' | 'synthesizing' | 'completed' | 'failed';

// ─── Worker Roles (V3 Hierarchy) ─────────────────────────────────────────────

export type SwarmWorkerRole = 'executor' | 'manager' | 'judge';

export interface RoleInfo {
  label: string;
  icon: string;
  color: string;
  description: string;
}

export const ROLE_INFO: Record<SwarmWorkerRole, RoleInfo> = {
  executor: { label: 'Executor', icon: '⚡', color: '#3b82f6', description: 'Cheap models that do the actual coding work' },
  manager: { label: 'Manager', icon: '👁', color: '#f59e0b', description: 'Premium model that reviews wave outputs and plans' },
  judge: { label: 'Judge', icon: '⚖', color: '#8b5cf6', description: 'Premium flash model that runs quality gates' },
};

// ─── Core Types ───────────────────────────────────────────────────────────────

export interface SwarmWorkerStatus {
  taskId: string;
  taskDescription: string;
  model: string;
  workerName: string;
  elapsedMs: number;
  startedAt: number;
}

export interface SwarmTaskResult {
  success: boolean;
  output: string;
  tokensUsed: number;
  costUsed: number;
  durationMs: number;
  qualityScore?: number;
  qualityFeedback?: string;
  filesModified?: string[];
  findings?: string[];
  model: string;
}

export interface SwarmTask {
  id: string;
  description: string;
  type: string;
  dependencies: string[];
  status: SwarmTaskStatus;
  complexity: number;
  wave: number;
  targetFiles?: string[];
  readFiles?: string[];
  assignedModel?: string;
  result?: SwarmTaskResult;
  attempts: number;
}

export interface SwarmStatus {
  phase: SwarmPhase;
  currentWave: number;
  totalWaves: number;
  activeWorkers: SwarmWorkerStatus[];
  queue: {
    ready: number;
    running: number;
    completed: number;
    failed: number;
    skipped: number;
    total: number;
  };
  budget: {
    tokensUsed: number;
    tokensTotal: number;
    costUsed: number;
    costTotal: number;
  };
}

// ─── Event Types ──────────────────────────────────────────────────────────────

export type SwarmEventType =
  | 'swarm.start'
  | 'swarm.wave.start'
  | 'swarm.wave.complete'
  | 'swarm.task.dispatched'
  | 'swarm.task.completed'
  | 'swarm.task.failed'
  | 'swarm.task.skipped'
  | 'swarm.quality.rejected'
  | 'swarm.budget.update'
  | 'swarm.status'
  | 'swarm.complete'
  | 'swarm.error'
  // V2: Planning, review, verification
  | 'swarm.plan.complete'
  | 'swarm.review.start'
  | 'swarm.review.complete'
  | 'swarm.verify.start'
  | 'swarm.verify.step'
  | 'swarm.verify.complete'
  | 'swarm.model.failover'
  | 'swarm.model.health'
  | 'swarm.orchestrator.decision'
  | 'swarm.fixup.spawned'
  | 'swarm.circuit.open'
  | 'swarm.circuit.closed'
  // V3: Hierarchy role events
  | 'swarm.role.action';

export interface TimestampedSwarmEvent {
  ts: string;
  seq: number;
  event: {
    type: SwarmEventType;
    [key: string]: unknown;
  };
}

// ─── Live State ───────────────────────────────────────────────────────────────

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
  timeline: TimelineEntry[];
  errors: SwarmError[];
  // V2/V3 extended state
  decisions?: Array<{ timestamp: number; phase: string; decision: string; reasoning: string }>;
  modelHealth?: Array<{ model: string; healthy: boolean; successes: number; failures: number; rateLimits: number }>;
  verification?: { passed: boolean; summary: string };
}

export interface TimelineEntry {
  ts: string;
  seq: number;
  type: string;
  tokensUsed: number;
  costUsed: number;
  completedCount: number;
  failedCount: number;
}

export interface SwarmError {
  ts: string;
  taskId?: string;
  phase: string;
  message: string;
}

// ─── DAG Types ────────────────────────────────────────────────────────────────

export interface DAGNode {
  id: string;
  label: string;
  status: SwarmTaskStatus;
  wave: number;
  model?: string;
  complexity: number;
  type: string;
}

export interface DAGEdge {
  source: string;
  target: string;
}

// ─── Model Usage ──────────────────────────────────────────────────────────────

export interface ModelUsageEntry {
  model: string;
  tasks: number;
  tokensUsed: number;
  costUsed: number;
  avgQualityScore: number | null;
}

// ─── Status Colors ────────────────────────────────────────────────────────────

export const SWARM_STATUS_COLORS: Record<SwarmTaskStatus, string> = {
  pending: '#6b7280',
  ready: '#3b82f6',
  dispatched: '#f59e0b',
  completed: '#10b981',
  failed: '#ef4444',
  skipped: '#9ca3af',
};

export const SWARM_PHASE_COLORS: Record<SwarmPhase, string> = {
  decomposing: '#8b5cf6',
  scheduling: '#3b82f6',
  planning: '#a855f7',
  executing: '#f59e0b',
  verifying: '#06b6d4',
  synthesizing: '#14b8a6',
  completed: '#10b981',
  failed: '#ef4444',
};

// ─── Helper Functions ─────────────────────────────────────────────────────────

export function getEventMessage(event: TimestampedSwarmEvent): string {
  const e = event.event;
  switch (e.type) {
    case 'swarm.start':
      return `Swarm started: ${e.taskCount} tasks in ${e.waveCount} waves`;
    case 'swarm.wave.start':
      return `Wave ${e.wave}/${e.totalWaves}: dispatching ${e.taskCount} tasks`;
    case 'swarm.wave.complete':
      return `Wave ${e.wave}/${e.totalWaves} complete: ${e.completed} done, ${e.failed} failed`;
    case 'swarm.task.dispatched':
      return `Task → ${e.workerName} (${shortModel(e.model as string)}): ${truncateText(e.description as string, 60)}`;
    case 'swarm.task.completed':
      return `Task ${e.taskId} ${e.success ? 'completed' : 'failed'} (${formatK(e.tokensUsed as number)} tokens)`;
    case 'swarm.task.failed':
      return `Task ${e.taskId} failed (attempt ${e.attempt}/${e.maxAttempts}): ${truncateText(e.error as string, 60)}`;
    case 'swarm.task.skipped':
      return `Task ${e.taskId} skipped: ${e.reason}`;
    case 'swarm.quality.rejected':
      return `Quality rejected ${e.taskId} (${e.score}/5): ${truncateText(e.feedback as string, 60)}`;
    case 'swarm.budget.update':
      return `Budget: ${formatK(e.tokensUsed as number)}/${formatK(e.tokensTotal as number)} tokens`;
    case 'swarm.complete':
      return `Swarm complete`;
    case 'swarm.error':
      return `Error in ${e.phase}: ${truncateText(e.error as string, 60)}`;
    case 'swarm.role.action': {
      const role = String(e.role);
      const roleLabel = role.charAt(0).toUpperCase() + role.slice(1);
      return `${roleLabel} ${e.action}: ${shortModel(e.model as string)}${e.taskId ? ` (task ${e.taskId})` : ''}`;
    }
    case 'swarm.plan.complete':
      return `Plan created: ${e.criteriaCount} criteria`;
    case 'swarm.review.complete':
      return `Wave ${e.wave} review: ${e.assessment}${(e.fixupCount as number) > 0 ? ` (${e.fixupCount} fixups)` : ''}`;
    case 'swarm.verify.complete':
      return `Verification ${(e.result as { passed: boolean })?.passed ? 'PASSED' : 'FAILED'}`;
    case 'swarm.model.failover':
      return `Failover: ${shortModel(e.fromModel as string)} → ${shortModel(e.toModel as string)}`;
    case 'swarm.circuit.open':
      return `Circuit breaker OPEN: pausing ${(e.pauseMs as number) / 1000}s`;
    case 'swarm.circuit.closed':
      return `Circuit breaker closed: dispatch resumed`;
    default:
      return `${e.type}`;
  }
}

function formatK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
}

function truncateText(s: string, max: number): string {
  if (!s) return '';
  return s.length > max ? s.slice(0, max - 3) + '...' : s;
}

function shortModel(model: string): string {
  if (!model) return '';
  // Extract last part after /
  const parts = model.split('/');
  const name = parts[parts.length - 1];
  return name.length > 20 ? name.slice(0, 17) + '...' : name;
}
