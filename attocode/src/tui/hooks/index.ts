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

export {
  useAgentEvents,
  type AgentEventSource,
  type UseAgentEventsRefs,
  type UseAgentEventsSetters,
  type UseAgentEventsOptions,
} from './use-agent-events.js';

export {
  useDashboardState,
  type DashboardTab,
  type DetailSubTab,
  type DashboardState,
} from './use-dashboard-state.js';

export {
  useLiveTrace,
  type LiveIterationData,
  type LiveIssue,
  type LiveDashboardData,
} from './use-live-trace.js';

export {
  useSessionBrowser,
  type SessionSummary,
  type SessionSortField,
  type SessionSortDir,
} from './use-session-browser.js';

export {
  useSessionDetail,
  type SessionDetailData,
} from './use-session-detail.js';
