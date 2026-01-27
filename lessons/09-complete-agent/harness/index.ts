/**
 * Agent Harness Module
 *
 * Exports for session management, subagent spawning, and event communication.
 */

export {
  AgentHarness,
  createAgentHarness,
  type HarnessConfig,
} from './agent-harness.js';

export {
  Session,
  createSession,
  type SessionConfig,
  type SessionState,
  type SessionStats,
} from './session.js';

export {
  SubagentSpawner,
  createSubagentSpawner,
  type SubagentConfig,
  type SubagentResult,
  type ParallelTask,
} from './subagent.js';

export {
  EventBus,
  globalEventBus,
  sessionStartEvent,
  sessionEndEvent,
  taskStartEvent,
  taskCompleteEvent,
  toolCallEvent,
  toolResultEvent,
  cacheHitEvent,
  type AgentEvent,
  type AgentEventType,
  type BaseAgentEvent,
  type SessionStartEvent,
  type SessionEndEvent,
  type TaskStartEvent,
  type TaskCompleteEvent,
  type TaskErrorEvent,
  type ToolCallEvent,
  type ToolResultEvent,
  type SubagentSpawnEvent,
  type SubagentCompleteEvent,
  type ThinkingEvent,
  type ResponseEvent,
  type CacheHitEvent,
  type ContextCompactEvent,
  type EventHandler,
  type EventFilter,
} from './communication.js';
