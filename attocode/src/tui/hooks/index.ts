/**
 * TUI Hooks
 *
 * Custom React hooks for TUI functionality.
 */

export {
  useMessagePruning,
  type TUIMessage,
  type MessagePruningConfig,
  type PruneStats,
  type UseMessagePruningResult,
} from './useMessagePruning.js';

export { useThrottledState, useThrottledCallback } from './use-throttled-state.js';

export {
  useAgentEvents,
  type AgentEventSource,
  type UseAgentEventsRefs,
  type UseAgentEventsSetters,
  type UseAgentEventsOptions,
} from './use-agent-events.js';
