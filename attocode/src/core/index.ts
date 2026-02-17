/**
 * Core Module
 *
 * Unified exports for the core infrastructure layer including:
 * - Op/Event Protocol: Typed message passing between UI and agent
 * - Process handlers for graceful shutdown
 *
 * @example
 * ```typescript
 * import {
 *   // Protocol types
 *   type Operation,
 *   type AgentEvent,
 *   type Submission,
 *   type EventEnvelope,
 *   // Validation
 *   OperationSchema,
 *   AgentEventSchema,
 *   // Type guards
 *   isUserTurn,
 *   isAgentMessage,
 * } from './core/index.js';
 * ```
 */

// Protocol types and validation
export * from './protocol/index.js';

// Process handlers and cleanup
export * from './process-handlers.js';

// Core agent context types (Phase 2.1: God class decomposition)
export type {
  AgentContext,
  AgentContextMutators,
  SubAgentInstance,
  SubAgentFactory,
} from './types.js';

// Extracted modules (Phase 2.1)
export {
  executeToolCalls,
  executeSingleToolCall,
  summarizeToolResult,
  formatToolArgsForPlan,
  extractChangeReasoning,
  PARALLELIZABLE_TOOLS,
  CONDITIONALLY_PARALLEL_TOOLS,
  extractToolFilePath,
  groupToolCallsIntoBatches,
} from './tool-executor.js';
export { callLLM } from './response-handler.js';
export { executeDirectly } from './execution-loop.js';
export {
  spawnAgent,
  spawnAgentsParallel,
  getSubagentBudget,
  parseStructuredClosureReport,
} from './subagent-spawner.js';

// Phase 2.2: Agent State Machine
export {
  AgentStateMachine,
  createAgentStateMachine,
  type AgentPhase,
  type PhaseMetrics,
  type PhaseTransition,
  type PhaseSnapshot,
  type StateMachineEvent,
  type StateMachineEventListener,
} from './agent-state-machine.js';

// Phase 2.3: Base Manager Pattern
export {
  BaseManager,
  type ManagerState,
  type BaseEvent,
  type ManagerLifecycleEvent,
} from './base-manager.js';

// Note: The queues/ directory was removed as unused dead code.
// The queue-based communication pattern was an over-engineered design
// that was never integrated. The codebase uses direct event subscriptions instead.
