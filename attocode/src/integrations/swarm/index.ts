/**
 * Swarm Mode - Public Exports
 *
 * Opt-in swarm experiment mode where one orchestrator model
 * coordinates multiple small specialist worker models.
 */

// Types
export type {
  SwarmConfig,
  SwarmWorkerSpec,
  WorkerCapability,
  WorkerRole,
  SwarmTask,
  SwarmTaskStatus,
  SwarmTaskResult,
  SwarmExecutionResult,
  SwarmExecutionStats,
  SwarmError,
  SwarmStatus,
  SwarmWorkerStatus,
  // V2 types
  TaskAcceptanceCriteria,
  VerificationStep,
  IntegrationTestPlan,
  SwarmPlan,
  VerificationResult,
  WaveReviewResult,
  FixupTask,
  ModelHealthRecord,
  SwarmCheckpoint,
  OrchestratorDecision,
  WorkerConversationEntry,
} from './types.js';
export { DEFAULT_SWARM_CONFIG, subtaskToSwarmTask, taskResultToAgentOutput, SUBTASK_TO_CAPABILITY } from './types.js';

// Events
export type { SwarmEvent } from './swarm-events.js';
export { isSwarmEvent, formatSwarmEvent } from './swarm-events.js';

// Task Queue
export { SwarmTaskQueue, createSwarmTaskQueue } from './task-queue.js';

// Budget
export type { SwarmBudgetPool } from './swarm-budget.js';
export { createSwarmBudgetPool } from './swarm-budget.js';

// Model Selector
export { autoDetectWorkerModels, selectWorkerForCapability, ModelHealthTracker, selectAlternativeModel } from './model-selector.js';
export type { ModelSelectorOptions } from './model-selector.js';

// Worker Pool
export { SwarmWorkerPool, createSwarmWorkerPool } from './worker-pool.js';
export type { SpawnAgentFn } from './worker-pool.js';

// Quality Gate
export { evaluateWorkerOutput } from './swarm-quality-gate.js';
export type { QualityGateResult } from './swarm-quality-gate.js';

// Request Throttle
export { SwarmThrottle, ThrottledProvider, createThrottledProvider } from './request-throttle.js';
export type { ThrottleConfig, ThrottleStats } from './request-throttle.js';
export { FREE_TIER_THROTTLE, PAID_TIER_THROTTLE } from './request-throttle.js';

// Orchestrator
export { SwarmOrchestrator, createSwarmOrchestrator } from './swarm-orchestrator.js';
export type { SwarmEventListener } from './swarm-orchestrator.js';

// Event Bridge (file-based dashboard integration)
export { SwarmEventBridge } from './swarm-event-bridge.js';
export type { SwarmLiveState, TimestampedSwarmEvent, SwarmEventBridgeOptions } from './swarm-event-bridge.js';

// State Store (V2: persistence/resume)
export { SwarmStateStore } from './swarm-state-store.js';

// Config Loader (V3: YAML support)
export { loadSwarmYamlConfig, mergeSwarmConfigs, parseSwarmYaml, yamlToSwarmConfig } from './swarm-config-loader.js';
