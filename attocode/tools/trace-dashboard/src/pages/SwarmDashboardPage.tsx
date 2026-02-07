/**
 * SwarmDashboardPage - Main layout for live swarm visualization
 */

import { useSwarmStream } from '../hooks/useSwarmStream';
import { LoadingSpinner } from '../components/LoadingSpinner';
import {
  SwarmHeader,
  MetricsStrip,
  TaskDAGPanel,
  WorkerTimelinePanel,
  BudgetPanel,
  ModelDistributionPanel,
  QualityHeatmapPanel,
  EventFeedPanel,
  WaveProgressStrip,
  ExpandablePanel,
} from '../components/swarm';

export function SwarmDashboardPage() {
  const { connected, idle, state, recentEvents, error, reconnect } = useSwarmStream();

  // Still loading initial state
  if (!state && !error && !idle) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <LoadingSpinner text="Connecting to swarm..." />
      </div>
    );
  }

  // No active swarm (idle or error without state)
  if (!state) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        {error && <div className="text-red-400 text-sm mb-4">{error.message}</div>}
        <div className="text-gray-400 text-lg mb-2">No active swarm</div>
        <p className="text-xs text-gray-500 max-w-md text-center mb-4">
          Start a swarm task with <code className="text-gray-400">--swarm</code> flag
          to see live visualization. The dashboard will auto-connect when a swarm starts.
        </p>
        <button
          onClick={reconnect}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-500 transition-colors"
        >
          Refresh
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <SwarmHeader state={state} connected={connected} />

      {/* Metrics Strip */}
      <MetricsStrip state={state} />

      {/* Error banner */}
      {error && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg px-4 py-2 text-sm text-red-400 flex items-center justify-between">
          <span>{error.message}</span>
          <button onClick={reconnect} className="text-xs text-red-300 hover:text-white">
            Reconnect
          </button>
        </div>
      )}

      {/* Main 2-column grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Row 1: DAG + Timeline */}
        <ExpandablePanel title="Task DAG">
          <TaskDAGPanel
            tasks={state?.tasks ?? []}
            edges={state?.edges ?? []}
          />
        </ExpandablePanel>
        <ExpandablePanel title="Worker Timeline">
          <WorkerTimelinePanel tasks={state?.tasks ?? []} />
        </ExpandablePanel>

        {/* Row 2: Budget + Model Distribution */}
        <ExpandablePanel title="Budget">
          <BudgetPanel state={state} />
        </ExpandablePanel>
        <ExpandablePanel title="Model Distribution">
          <ModelDistributionPanel state={state} />
        </ExpandablePanel>

        {/* Row 3: Quality + Events */}
        <ExpandablePanel title="Quality Heatmap">
          <QualityHeatmapPanel tasks={state?.tasks ?? []} />
        </ExpandablePanel>
        <ExpandablePanel title="Event Feed">
          <EventFeedPanel events={recentEvents} />
        </ExpandablePanel>
      </div>

      {/* Wave Progress Strip */}
      <WaveProgressStrip state={state} />
    </div>
  );
}
