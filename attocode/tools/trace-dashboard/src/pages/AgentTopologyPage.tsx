/**
 * AgentTopologyPage - Agent Topology with Animated Data Flows
 *
 * Route: /topology and /topology/:sessionId
 *
 * Layout:
 * - AgentGraph as main content (flex-1)
 * - Right sidebar: toggleable between AgentInspector, BlackboardPanel, BudgetTreemap
 * - Bottom: FlowTimeline (for replay mode)
 * - Top: FlowLegend
 *
 * Live mode: SSE-driven updates via useSwarmStream
 * Post-mortem mode: session data with replay timeline
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAgentGraph } from '../hooks/useAgentGraph';
import { useSwarmStream } from '../hooks/useSwarmStream';
import { useSessions } from '../hooks/useApi';
import { LoadingSpinner } from '../components/LoadingSpinner';
import {
  AgentGraph,
  AgentInspector,
  BlackboardPanel,
  BudgetTreemap,
  FlowTimeline,
  FlowLegend,
} from '../components/topology';
import type { AgentGraphData } from '../lib/agent-graph-types';
import { formatTokens, relativeTime, truncate } from '../lib/utils';

type SidebarTab = 'inspector' | 'blackboard' | 'budget';

/** Session picker when no sessionId is provided */
function SessionPicker() {
  const { data: sessions, loading, error, refetch } = useSessions();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');

  if (loading) {
    return <LoadingSpinner text="Loading sessions..." />;
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-400 mb-4">
          Failed to load sessions: {error.message}
        </p>
        <button
          onClick={refetch}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!sessions || sessions.length === 0) {
    return (
      <div className="text-center py-12">
        <h3 className="text-lg font-medium text-gray-300 mb-2">No Sessions Found</h3>
        <p className="text-gray-500">Run some agent sessions to view topologies.</p>
      </div>
    );
  }

  const filtered = filter
    ? sessions.filter(
        (s) =>
          s.task.toLowerCase().includes(filter.toLowerCase()) ||
          s.model.toLowerCase().includes(filter.toLowerCase()) ||
          s.id.toLowerCase().includes(filter.toLowerCase())
      )
    : sessions;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white mb-2">Agent Topology</h1>
        <p className="text-gray-400 text-sm">
          Select a session to visualize its agent hierarchy and animated data flows.
        </p>
      </div>

      <div className="mb-4">
        <input
          type="text"
          placeholder="Search by task, model, or ID..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full max-w-md px-4 py-2 bg-gray-800 border border-gray-700 rounded text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((session) => (
          <button
            key={session.id}
            onClick={() =>
              navigate(`/topology/${encodeURIComponent(session.filePath)}`)
            }
            className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-left hover:border-gray-700 hover:bg-gray-900/80 transition-colors"
          >
            <div className="text-sm text-gray-200 font-medium truncate mb-1">
              {truncate(session.task, 60)}
            </div>
            <div className="text-xs text-gray-500 font-mono mb-2">
              {session.id}
            </div>
            <div className="flex items-center gap-3 text-[10px] text-gray-500">
              <span>{relativeTime(session.startTime)}</span>
              <span>{session.model}</span>
              <span>{formatTokens(session.metrics.totalTokens)} tokens</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function TopologyView({ sessionId, swarmDir }: { sessionId?: string; swarmDir?: string }) {
  const { data: graphData, loading, error, refetch } = useAgentGraph(sessionId);

  // SSE stream for live mode
  const { blackboard, budgetPool, connected, recentEvents, state, idle } = useSwarmStream(swarmDir);
  const liveSwarmMode = !sessionId;

  // UI state
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('inspector');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Replay state
  const [playing, setPlaying] = useState(false);
  const [replayTime, setReplayTime] = useState(0);
  const [replaySpeed, setReplaySpeed] = useState(1);

  // Determine mode: live (SSE connected) or post-mortem (session data)
  const isLiveMode = liveSwarmMode || connected;

  // Compute timeline bounds for post-mortem mode
  const timelineBounds = useMemo(() => {
    if (!graphData || graphData.dataFlows.length === 0) {
      return { start: 0, end: 1000 };
    }
    const timestamps = graphData.dataFlows.map((f) => f.timestamp);
    const start = Math.min(...timestamps);
    const end = Math.max(...timestamps);
    // Add 10% padding
    const duration = end - start;
    return {
      start: start - duration * 0.05,
      end: end + duration * 0.05,
    };
  }, [graphData]);

  // Initialize replay time to start
  useEffect(() => {
    if (graphData && !isLiveMode) {
      setReplayTime(timelineBounds.start);
    }
  }, [graphData, isLiveMode, timelineBounds.start]);

  // Flows filtered by replay time (post-mortem mode)
  const replayFlows = useMemo(() => {
    if (!graphData || isLiveMode) return undefined;
    return graphData.dataFlows.filter((f) => f.timestamp <= replayTime);
  }, [graphData, isLiveMode, replayTime]);

  // Live flows for animation
  const liveFlows = useMemo(() => {
    if (!isLiveMode || !graphData) return undefined;
    return graphData.dataFlows;
  }, [isLiveMode, graphData]);

  // Agent selection handler
  const handleSelectAgent = useCallback(
    (id: string | null) => {
      setSelectedAgentId(id);
      if (id) {
        setSidebarTab('inspector');
        setSidebarOpen(true);
      } else {
        setSidebarOpen(false);
      }
    },
    []
  );

  const handlePlayPause = useCallback(() => {
    setPlaying((p) => !p);
  }, []);

  const handleTimeChange = useCallback((time: number) => {
    setReplayTime(time);
  }, []);

  const handleSpeedChange = useCallback((speed: number) => {
    setReplaySpeed(speed);
  }, []);

  // Get selected agent for inspector
  const selectedAgent = useMemo(() => {
    if (!graphData || !selectedAgentId) return null;
    return graphData.agents.find((a) => a.id === selectedAgentId) ?? null;
  }, [graphData, selectedAgentId]);

  const synthesizedSwarmData = useMemo<AgentGraphData | null>(() => {
    if (!liveSwarmMode || !state) return null;
    const rootId = 'swarm-orchestrator';
    const agents: AgentGraphData['agents'] = [
      {
        id: rootId,
        label: 'Swarm Orchestrator',
        model: state.config.hierarchy?.manager?.model ?? state.config.workerModels?.[0] ?? '',
        type: 'orchestrator',
        status: state.active ? 'running' : 'completed',
        tokensUsed: state.status?.orchestrator?.tokens ?? 0,
        costUsed: state.status?.orchestrator?.cost ?? 0,
        filesAccessed: [],
        findingsPosted: 0,
      },
    ];

    const modelSet = new Set<string>();
    for (const model of state.config.workerModels ?? []) modelSet.add(model);
    for (const task of state.tasks ?? []) {
      if (task.assignedModel) modelSet.add(task.assignedModel);
      if (task.result?.model) modelSet.add(task.result.model);
    }

    for (const model of modelSet) {
      const taskStats = (state.tasks ?? []).filter((t) => (t.assignedModel ?? t.result?.model) === model);
      const tokensUsed = taskStats.reduce((sum, t) => sum + (t.result?.tokensUsed ?? 0), 0);
      const costUsed = taskStats.reduce((sum, t) => sum + (t.result?.costUsed ?? 0), 0);
      const running = taskStats.some((t) => t.status === 'dispatched');
      agents.push({
        id: `worker:${model}`,
        label: model,
        model,
        type: 'worker',
        status: running ? 'running' : 'completed',
        parentId: rootId,
        tokensUsed,
        costUsed,
        filesAccessed: [],
        findingsPosted: 0,
      });
    }

    const dataFlows: AgentGraphData['dataFlows'] = [];
    for (const e of recentEvents) {
      const ev = e.event as Record<string, unknown>;
      const type = String(ev.type ?? '');
      const model = String(ev.model ?? '');
      if (!model) continue;
      if (type === 'swarm.task.dispatched') {
        dataFlows.push({
          id: `swarm-flow-${e.seq}`,
          timestamp: new Date(e.ts).getTime(),
          sourceAgentId: rootId,
          targetAgentId: `worker:${model}`,
          type: 'task_assignment',
          payload: { summary: String(ev.description ?? ev.taskId ?? 'Task dispatched') },
        });
      } else if (type === 'swarm.task.completed' || type === 'swarm.task.failed') {
        dataFlows.push({
          id: `swarm-flow-${e.seq}`,
          timestamp: new Date(e.ts).getTime(),
          sourceAgentId: `worker:${model}`,
          targetAgentId: rootId,
          type: 'result_return',
          payload: { summary: String(ev.taskId ?? type) },
        });
      }
    }

    return { agents, dataFlows };
  }, [liveSwarmMode, state, recentEvents]);

  // Loading state
  if (!liveSwarmMode && loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner text="Loading agent topology..." />
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-400 mb-4">
          Failed to load topology: {error.message}
        </p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={refetch}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
          >
            Retry
          </button>
          <Link
            to="/topology"
            className="px-4 py-2 text-gray-300 border border-gray-700 rounded hover:bg-gray-800 transition-colors"
          >
            Back to sessions
          </Link>
        </div>
      </div>
    );
  }

  // No data
  if (!liveSwarmMode && (!graphData || graphData.agents.length === 0)) {
    return (
      <div className="text-center py-12">
        <h3 className="text-lg font-medium text-gray-300 mb-2">No Agent Data</h3>
        <p className="text-gray-500 mb-4">
          This session does not have agent topology data.
          Agent topology requires sessions with subagents or swarm workers.
        </p>
        <Link
          to="/topology"
          className="px-4 py-2 text-gray-300 border border-gray-700 rounded hover:bg-gray-800 transition-colors"
        >
          Back to sessions
        </Link>
      </div>
    );
  }

  if (liveSwarmMode && !synthesizedSwarmData) {
    if (!idle && !state) {
      return (
        <div className="flex items-center justify-center py-20">
          <LoadingSpinner text="Connecting to live swarm topology..." />
        </div>
      );
    }
    return (
      <div className="text-center py-12">
        <h3 className="text-lg font-medium text-gray-300 mb-2">No Active Swarm</h3>
        <p className="text-gray-500 mb-4">Start a swarm run to view live topology.</p>
        <Link
          to={swarmDir ? `/swarm?dir=${encodeURIComponent(swarmDir)}` : '/swarm'}
          className="px-4 py-2 text-gray-300 border border-gray-700 rounded hover:bg-gray-800 transition-colors"
        >
          Back to Swarm
        </Link>
      </div>
    );
  }

  const effectiveData: AgentGraphData = liveSwarmMode ? synthesizedSwarmData! : graphData!;

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to={liveSwarmMode
              ? (swarmDir ? `/swarm?dir=${encodeURIComponent(swarmDir)}` : '/swarm')
              : '/topology'}
            className="text-gray-500 hover:text-gray-300 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <div>
            <h1 className="text-lg font-bold text-white">Agent Topology</h1>
            <div className="text-xs text-gray-500">
              {effectiveData.agents.length} agents &middot; {effectiveData.dataFlows.length} data flows
              {isLiveMode && (
                <span className="ml-2 text-green-400">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400 mr-1 animate-pulse" />
                  Live
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Sidebar tab toggles */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => {
              if (sidebarTab === 'blackboard' && sidebarOpen) {
                setSidebarOpen(false);
              } else {
                setSidebarTab('blackboard');
                setSidebarOpen(true);
              }
            }}
            className={`px-2.5 py-1.5 text-xs rounded transition-colors ${
              sidebarOpen && sidebarTab === 'blackboard'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            Blackboard
          </button>
          <button
            onClick={() => {
              if (sidebarTab === 'budget' && sidebarOpen) {
                setSidebarOpen(false);
              } else {
                setSidebarTab('budget');
                setSidebarOpen(true);
              }
            }}
            className={`px-2.5 py-1.5 text-xs rounded transition-colors ${
              sidebarOpen && sidebarTab === 'budget'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            Budget
          </button>
        </div>
      </div>

      {/* Flow Legend */}
      <FlowLegend />

      {/* Main content area */}
      <div className="flex gap-3">
        {/* Graph (flex-1) */}
        <div className="flex-1 bg-gray-900 border border-gray-800 rounded-lg p-4 min-w-0">
          <AgentGraph
            data={effectiveData}
            selectedAgentId={selectedAgentId}
            onSelectAgent={handleSelectAgent}
            liveFlows={liveFlows}
            replayFlows={replayFlows}
            replayTime={replayTime}
          />
        </div>

        {/* Right sidebar (inline panels, not fixed overlay for non-inspector) */}
        {sidebarOpen && sidebarTab !== 'inspector' && (
          <div className="w-80 shrink-0 space-y-3">
            {sidebarTab === 'blackboard' && (
              <BlackboardPanel blackboard={blackboard} />
            )}
            {sidebarTab === 'budget' && (
              <BudgetTreemap budgetPool={budgetPool} />
            )}
          </div>
        )}
      </div>

      {/* Bottom: Flow Timeline (post-mortem replay mode) */}
      {!isLiveMode && effectiveData.dataFlows.length > 0 && (
        <FlowTimeline
          flows={effectiveData.dataFlows}
          startTime={timelineBounds.start}
          endTime={timelineBounds.end}
          currentTime={replayTime}
          onTimeChange={handleTimeChange}
          playing={playing}
          onPlayPause={handlePlayPause}
          speed={replaySpeed}
          onSpeedChange={handleSpeedChange}
        />
      )}

      {/* Agent Inspector (fixed overlay, slides from right) */}
      <AgentInspector
        agent={selectedAgent}
        dataFlows={effectiveData.dataFlows}
        onClose={() => {
          setSelectedAgentId(null);
          setSidebarOpen(false);
        }}
      />
    </div>
  );
}

export function AgentTopologyPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [searchParams] = useSearchParams();
  const swarmMode = searchParams.get('swarm') === '1';
  const swarmDir = searchParams.get('dir') ?? undefined;

  if (!sessionId && !swarmMode) {
    return <SessionPicker />;
  }

  return <TopologyView sessionId={sessionId} swarmDir={swarmDir} />;
}
