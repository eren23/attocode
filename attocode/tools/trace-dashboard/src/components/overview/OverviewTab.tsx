/**
 * OverviewTab - Unified "see everything at a glance" tab
 *
 * Grid layout showing:
 * - Agent hierarchy tree (left column, 1/3 width)
 * - Mini code map (right column, 2/3 width)
 * - Interaction timeline (full width below)
 * - Shared resource bar (full width bottom)
 *
 * Data is lazy-loaded only when the tab becomes active.
 */

import { useState, useMemo } from 'react';
import { useAgentGraph } from '../../hooks/useAgentGraph';
import { useCodeMap } from '../../hooks/useCodeMap';
import { LoadingSpinner } from '../LoadingSpinner';
import { AgentHierarchyTree } from './AgentHierarchyTree';
import { MiniCodeMap } from './MiniCodeMap';
import { InteractionTimeline } from './InteractionTimeline';
import { SharedResourceBar } from './SharedResourceBar';

interface OverviewTabProps {
  sessionId: string;
}

export function OverviewTab({ sessionId }: OverviewTabProps) {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const {
    data: agentData,
    loading: agentLoading,
    error: agentError,
  } = useAgentGraph(sessionId);

  const {
    data: codeMapData,
    loading: codeMapLoading,
    error: codeMapError,
  } = useCodeMap(sessionId);

  // Compute shared resource metrics from agent data
  const sharedResources = useMemo(() => {
    if (!agentData) {
      return { blackboardFindings: 0, cacheEntries: 0, budgetUsedPercent: 0 };
    }

    const totalFindings = agentData.agents.reduce((sum, a) => sum + a.findingsPosted, 0);
    const totalFiles = new Set(agentData.agents.flatMap((a) => a.filesAccessed)).size;

    // Estimate budget usage from agent costs
    const totalCost = agentData.agents.reduce((sum, a) => sum + a.costUsed, 0);
    // Assume a reasonable max budget; if root agent exists, use 2x its cost as rough estimate
    const rootAgent = agentData.agents.find((a) => a.type === 'root');
    const estimatedBudget = rootAgent ? Math.max(totalCost * 1.2, rootAgent.costUsed * 3) : totalCost * 1.5;
    const budgetPercent = estimatedBudget > 0 ? (totalCost / estimatedBudget) * 100 : 0;

    return {
      blackboardFindings: totalFindings,
      cacheEntries: totalFiles,
      budgetUsedPercent: Math.min(100, budgetPercent),
    };
  }, [agentData]);

  const isLoading = agentLoading || codeMapLoading;

  if (isLoading) {
    return <LoadingSpinner text="Loading overview data..." />;
  }

  const hasAgentData = agentData && agentData.agents.length > 0;
  const hasCodeMapData = codeMapData && codeMapData.files.length > 0;

  // If neither data source returned anything useful
  if (!hasAgentData && !hasCodeMapData) {
    return (
      <div className="text-center py-12">
        <svg
          className="w-16 h-16 mx-auto text-gray-600 mb-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
          />
        </svg>
        <h3 className="text-lg font-medium text-gray-300 mb-2">No Overview Data</h3>
        <p className="text-gray-500 text-sm max-w-md mx-auto">
          This session does not have agent hierarchy or code map data.
          Overview is available for sessions with subagent or swarm activity.
        </p>
        {agentError && (
          <p className="text-red-400 text-xs mt-2">{agentError.message}</p>
        )}
        {codeMapError && (
          <p className="text-red-400 text-xs mt-2">{codeMapError.message}</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Top row: Agent Hierarchy + Mini Code Map */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Agent Hierarchy (1/3 width) */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
            <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            Agent Hierarchy
          </h3>
          {hasAgentData ? (
            <AgentHierarchyTree
              agents={agentData.agents}
              selectedAgentId={selectedAgentId}
              onSelectAgent={setSelectedAgentId}
              sessionId={sessionId}
            />
          ) : (
            <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
              No agent data available
            </div>
          )}
        </div>

        {/* Mini Code Map (2/3 width) */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
            <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
            Code Map
            {hasCodeMapData && (
              <span className="text-[10px] text-gray-500 font-normal ml-auto">
                {codeMapData.totalFiles} files / {codeMapData.totalTokens.toLocaleString()} tokens
              </span>
            )}
          </h3>
          {hasCodeMapData ? (
            <div className="max-h-[500px] overflow-y-auto">
              <MiniCodeMap data={codeMapData} sessionId={sessionId} />
            </div>
          ) : (
            <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
              No code map data available
            </div>
          )}
        </div>
      </div>

      {/* Interaction Timeline (full width) */}
      {hasAgentData && agentData.dataFlows.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
            <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
            </svg>
            Interaction Timeline
            <span className="text-[10px] text-gray-500 font-normal ml-auto">
              {agentData.dataFlows.length} events
            </span>
          </h3>
          <InteractionTimeline
            agents={agentData.agents}
            dataFlows={agentData.dataFlows}
          />
        </div>
      )}

      {/* Shared Resource Bar (full width) */}
      {hasAgentData && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
            <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
            </svg>
            Shared Resources
          </h3>
          <SharedResourceBar
            blackboardFindings={sharedResources.blackboardFindings}
            cacheEntries={sharedResources.cacheEntries}
            budgetUsedPercent={sharedResources.budgetUsedPercent}
          />
        </div>
      )}
    </div>
  );
}
