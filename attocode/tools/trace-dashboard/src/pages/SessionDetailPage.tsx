/**
 * Session Detail Page
 *
 * Displays detailed session information with tabs for different views.
 */

import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useSession, useTimeline, useTree, useTokens, useIssues, useSwarmData } from '../hooks/useApi';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { MetricCard } from '../components/MetricCard';
import { StatusBadge } from '../components/StatusBadge';
import { IssueCard } from '../components/IssueCard';
import { TokenFlowChart, CostBreakdownChart } from '../components/TokenFlowChart';
import { Timeline } from '../components/Timeline';
import { TreeView } from '../components/TreeView';
import { SwarmActivityView } from '../components/SwarmActivityView';
import {
  formatTokens,
  formatCost,
  formatDuration,
  formatPercent,
  cn,
} from '../lib/utils';
import { ExportDropdown } from '../components/ExportDropdown';

type TabId = 'summary' | 'timeline' | 'tree' | 'tokens' | 'issues' | 'swarm';

interface Tab {
  id: TabId;
  label: string;
  icon: JSX.Element;
}

const baseTabs: Tab[] = [
  {
    id: 'summary',
    label: 'Summary',
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
  },
  {
    id: 'timeline',
    label: 'Timeline',
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    id: 'tree',
    label: 'Tree',
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
      </svg>
    ),
  },
  {
    id: 'tokens',
    label: 'Tokens',
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
      </svg>
    ),
  },
  {
    id: 'issues',
    label: 'Issues',
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    ),
  },
];

const swarmTab: Tab = {
  id: 'swarm',
  label: 'Swarm',
  icon: (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
    </svg>
  ),
};

export function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<TabId>('summary');

  const { data: session, loading, error } = useSession(id);
  const { data: timeline } = useTimeline(activeTab === 'timeline' ? id : undefined);
  const { data: tree } = useTree(activeTab === 'tree' ? id : undefined);
  const { data: tokens } = useTokens(activeTab === 'tokens' || activeTab === 'summary' ? id : undefined);
  const { data: issues } = useIssues(activeTab === 'issues' || activeTab === 'summary' ? id : undefined);
  const { data: swarmData } = useSwarmData(activeTab === 'swarm' ? id : undefined);

  if (loading) {
    return <LoadingSpinner size="lg" text="Loading session..." />;
  }

  if (error || !session) {
    return (
      <div className="text-center py-12">
        <p className="text-red-400 mb-4">
          {error?.message || 'Session not found'}
        </p>
        <Link
          to="/"
          className="text-blue-400 hover:text-blue-300 hover:underline"
        >
          Back to sessions
        </Link>
      </div>
    );
  }

  const renderSummary = () => (
    <div className="space-y-6">
      {/* Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Iterations"
          value={session.metrics.iterations}
          status={session.metrics.iterations > 10 ? 'warn' : 'neutral'}
        />
        <MetricCard
          label="Total Tokens"
          value={formatTokens(session.metrics.totalTokens)}
          subtext={`${formatTokens(session.metrics.inputTokens)} in / ${formatTokens(session.metrics.outputTokens)} out`}
        />
        <MetricCard
          label="Cache Hit Rate"
          value={formatPercent(session.metrics.cacheHitRate)}
          status={
            session.metrics.cacheHitRate > 0.7
              ? 'good'
              : session.metrics.cacheHitRate > 0.4
              ? 'neutral'
              : 'bad'
          }
        />
        <MetricCard
          label="Total Cost"
          value={formatCost(session.metrics.cost)}
          subtext={`saved ${formatCost(session.metrics.costSaved)}`}
          status={session.metrics.cost > 1 ? 'warn' : 'neutral'}
        />
      </div>

      {/* Two-column layout for tools and tokens */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Tool Usage */}
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Tool Usage</h3>
          <div className="space-y-2">
            {Object.entries(session.toolPatterns.frequency)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 8)
              .map(([tool, count]) => (
                <div key={tool} className="flex items-center justify-between">
                  <span className="text-sm text-gray-400 font-mono">{tool}</span>
                  <span className="text-sm text-gray-300">{count}</span>
                </div>
              ))}
          </div>
        </div>

        {/* Cost Breakdown */}
        {tokens && (
          <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
            <h3 className="text-sm font-medium text-gray-300 mb-3">Cost Breakdown</h3>
            <CostBreakdownChart costBreakdown={tokens.costBreakdown} />
          </div>
        )}
      </div>

      {/* Issues preview */}
      {issues && issues.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Issues ({issues.length})
          </h3>
          <div className="space-y-3">
            {issues.slice(0, 3).map((issue) => (
              <IssueCard key={issue.id} issue={issue} />
            ))}
            {issues.length > 3 && (
              <button
                onClick={() => setActiveTab('issues')}
                className="text-sm text-blue-400 hover:text-blue-300"
              >
                View all {issues.length} issues
              </button>
            )}
          </div>
        </div>
      )}

      {/* Iteration Summaries */}
      <div>
        <h3 className="text-sm font-medium text-gray-300 mb-3">Iterations</h3>
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-700">
            <thead className="bg-gray-800/50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">#</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Action</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Outcome</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Tokens</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {session.iterationSummaries.map((iter) => (
                <tr key={iter.number} className="hover:bg-gray-800/30">
                  <td className="px-4 py-2 text-sm text-gray-300">{iter.number}</td>
                  <td className="px-4 py-2 text-sm text-gray-300 max-w-md truncate">
                    {iter.action}
                  </td>
                  <td className="px-4 py-2">
                    <StatusBadge status={iter.outcome} size="sm" />
                  </td>
                  <td className="px-4 py-2 text-sm text-gray-300">
                    {formatTokens(iter.tokensUsed)}
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex gap-1">
                      {iter.flags.map((flag) => (
                        <span
                          key={flag}
                          className="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-300"
                        >
                          {flag}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );

  const renderTimeline = () => {
    if (!timeline) return <LoadingSpinner text="Loading timeline..." />;
    return <Timeline entries={timeline.entries} startTime={timeline.startTime} />;
  };

  const renderTree = () => {
    if (!tree) return <LoadingSpinner text="Loading tree..." />;
    return <TreeView root={tree.root} />;
  };

  const renderTokens = () => {
    if (!tokens) return <LoadingSpinner text="Loading token data..." />;
    return (
      <div className="space-y-6">
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-4">Token Flow by Iteration</h3>
          <TokenFlowChart data={tokens} mode="per-iteration" />
        </div>
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-4">Cumulative Token Usage</h3>
          <TokenFlowChart data={tokens} mode="cumulative" />
        </div>
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-4">Cost Breakdown</h3>
          <CostBreakdownChart costBreakdown={tokens.costBreakdown} />
        </div>
      </div>
    );
  };

  const renderIssues = () => {
    if (!issues) return <LoadingSpinner text="Loading issues..." />;
    if (issues.length === 0) {
      return (
        <div className="text-center py-12">
          <svg
            className="w-16 h-16 mx-auto text-green-500 mb-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <h3 className="text-lg font-medium text-gray-300 mb-2">No Issues Detected</h3>
          <p className="text-gray-500">This session looks healthy!</p>
        </div>
      );
    }
    return (
      <div className="space-y-4">
        {issues.map((issue) => (
          <IssueCard key={issue.id} issue={issue} />
        ))}
      </div>
    );
  };

  const renderSwarm = () => {
    if (!swarmData) return <LoadingSpinner text="Loading swarm data..." />;
    return <SwarmActivityView data={swarmData} />;
  };

  const tabContent: Record<TabId, () => JSX.Element> = {
    summary: renderSummary,
    timeline: renderTimeline,
    tree: renderTree,
    tokens: renderTokens,
    issues: renderIssues,
    swarm: renderSwarm,
  };

  // Conditionally include swarm tab when session has swarm data
  const isSwarm = (session as unknown as Record<string, unknown>).isSwarm === true;
  const tabs: Tab[] = isSwarm ? [...baseTabs, swarmTab] : baseTabs;

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <Link
          to="/"
          className="text-sm text-gray-400 hover:text-white transition-colors mb-2 inline-flex items-center gap-1"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back to sessions
        </Link>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white mb-1">{session.meta.task}</h1>
            <div className="flex items-center gap-4 text-sm text-gray-400">
              <span>{session.meta.model}</span>
              <span>•</span>
              <span>{formatDuration(session.meta.duration)}</span>
              <span>•</span>
              <StatusBadge status={session.meta.status} />
            </div>
          </div>
          <ExportDropdown
            options={[
              {
                label: 'Download JSON',
                onClick: () => window.open(`/api/sessions/${encodeURIComponent(id!)}/raw`, '_blank'),
              },
              {
                label: 'Download CSV',
                onClick: () => window.open(`/api/sessions/${encodeURIComponent(id!)}/export/csv`, '_blank'),
              },
              {
                label: 'Download HTML Report',
                onClick: () => window.open(`/api/sessions/${encodeURIComponent(id!)}/export/html`, '_blank'),
              },
            ]}
          />
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-700 mb-6">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors',
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-400 hover:text-white hover:border-gray-600'
              )}
            >
              {tab.icon}
              {tab.label}
              {tab.id === 'issues' && issues && issues.length > 0 && (
                <span className="ml-1 px-1.5 py-0.5 text-xs rounded-full bg-red-500/20 text-red-400">
                  {issues.length}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {tabContent[activeTab]()}
    </div>
  );
}
