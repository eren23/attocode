/**
 * Swarm Activity View
 *
 * Displays swarm execution data within the Session Detail page.
 * Shows overview cards, wave progress, task table, budget timeline, and quality rejections.
 */

import type { SwarmActivityData } from '../lib/types';
import { formatTokens, formatCost } from '../lib/utils';

interface SwarmActivityViewProps {
  data: SwarmActivityData;
}

export function SwarmActivityView({ data }: SwarmActivityViewProps) {
  return (
    <div className="space-y-6">
      {/* Overview Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <OverviewCard
          label="Tasks"
          value={data.stats ? `${data.stats.completedTasks}/${data.stats.totalTasks}` : `${data.tasks.length}`}
          subtext={data.stats?.failedTasks ? `${data.stats.failedTasks} failed` : undefined}
          status={data.stats?.failedTasks ? 'warn' : 'good'}
        />
        <OverviewCard
          label="Total Tokens"
          value={data.stats ? formatTokens(data.stats.totalTokens) : '-'}
        />
        <OverviewCard
          label="Total Cost"
          value={data.stats ? formatCost(data.stats.totalCost) : '-'}
        />
        <OverviewCard
          label="Verification"
          value={
            data.verification
              ? data.verification.passed ? 'PASSED' : 'FAILED'
              : 'N/A'
          }
          subtext={data.verification ? `${data.verification.steps.length} steps` : undefined}
          status={
            data.verification
              ? data.verification.passed ? 'good' : 'bad'
              : 'neutral'
          }
        />
      </div>

      {/* Orchestrator Breakdown */}
      {data.orchestrator && (
        <div className="bg-gray-900/50 border border-purple-500/30 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Orchestrator Usage</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">Model</p>
              <p className="text-sm font-medium text-white mt-1 font-mono">
                {data.orchestrator.model.split('/').pop()}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">Tokens</p>
              <p className="text-sm font-medium text-white mt-1">
                {formatTokens(data.orchestrator.tokens)}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">Cost</p>
              <p className="text-sm font-medium text-white mt-1">
                {formatCost(data.orchestrator.cost)}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">LLM Calls</p>
              <p className="text-sm font-medium text-white mt-1">
                {data.orchestrator.calls}
              </p>
            </div>
          </div>
          {data.stats && (
            <div className="mt-3 pt-3 border-t border-gray-700 flex gap-6 text-xs text-gray-400">
              <span>
                Orchestrator: {data.stats.totalCost > 0
                  ? `${((data.orchestrator.cost / data.stats.totalCost) * 100).toFixed(1)}% of total cost`
                  : formatCost(data.orchestrator.cost)}
              </span>
              <span>
                Workers: {formatCost(data.stats.totalCost - data.orchestrator.cost)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Wave Progress */}
      {data.waves.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Wave Progress</h3>
          <div className="flex gap-2 flex-wrap">
            {Array.from({ length: data.totalWaves }, (_, i) => i + 1).map(waveNum => {
              const completeEvent = data.waves.find(w => w.wave === waveNum && w.phase === 'complete');
              const startEvent = data.waves.find(w => w.wave === waveNum && w.phase === 'start');
              const isComplete = !!completeEvent;
              const hasFailed = (completeEvent?.failed ?? 0) > 0;

              return (
                <div
                  key={waveNum}
                  className={`flex flex-col items-center p-3 rounded-lg border ${
                    isComplete
                      ? hasFailed
                        ? 'border-yellow-500/30 bg-yellow-500/10'
                        : 'border-green-500/30 bg-green-500/10'
                      : 'border-gray-600 bg-gray-800/50'
                  }`}
                >
                  <span className="text-xs text-gray-400">Wave {waveNum}</span>
                  <span className="text-lg font-bold text-white">
                    {startEvent?.taskCount ?? '?'}
                  </span>
                  <span className="text-xs text-gray-500">tasks</span>
                  {isComplete && (
                    <span className={`text-xs mt-1 ${hasFailed ? 'text-yellow-400' : 'text-green-400'}`}>
                      {completeEvent.completed} ok{hasFailed ? ` / ${completeEvent.failed} fail` : ''}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Task Table */}
      {data.tasks.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-700">
            <h3 className="text-sm font-medium text-gray-300">Tasks ({data.tasks.length})</h3>
          </div>
          <table className="min-w-full divide-y divide-gray-700">
            <thead className="bg-gray-800/50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">ID</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Description</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Wave</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Status</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Model</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Quality</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-400">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.tasks.map(task => (
                <tr key={task.id} className="hover:bg-gray-800/30">
                  <td className="px-4 py-2 text-sm text-gray-400 font-mono">{task.id}</td>
                  <td className="px-4 py-2 text-sm text-gray-300 max-w-xs truncate">{task.description}</td>
                  <td className="px-4 py-2">
                    <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">{task.type}</span>
                  </td>
                  <td className="px-4 py-2 text-sm text-gray-300">{task.wave + 1}</td>
                  <td className="px-4 py-2">
                    <TaskStatusBadge status={task.status} />
                  </td>
                  <td className="px-4 py-2 text-sm text-gray-400 font-mono text-xs">
                    {task.model ? task.model.split('/').pop() : '-'}
                  </td>
                  <td className="px-4 py-2 text-sm">
                    {task.qualityScore !== undefined ? (
                      <span className={task.qualityScore >= 3 ? 'text-green-400' : 'text-red-400'}>
                        {task.qualityScore}/5
                      </span>
                    ) : '-'}
                  </td>
                  <td className="px-4 py-2 text-sm text-gray-300">
                    {task.costUsed !== undefined ? formatCost(task.costUsed) : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Budget Timeline */}
      {data.budgetSnapshots.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Budget Usage Over Time</h3>
          <div className="space-y-2">
            {data.budgetSnapshots.map((snap, i) => {
              const tokenPct = snap.tokensTotal > 0 ? (snap.tokensUsed / snap.tokensTotal) * 100 : 0;
              const costPct = snap.costTotal > 0 ? (snap.costUsed / snap.costTotal) * 100 : 0;
              return (
                <div key={i} className="flex items-center gap-4 text-xs">
                  <span className="text-gray-500 w-16 flex-shrink-0">#{i + 1}</span>
                  <div className="flex-1">
                    <div className="flex justify-between text-gray-400 mb-0.5">
                      <span>Tokens: {formatTokens(snap.tokensUsed)}</span>
                      <span>{tokenPct.toFixed(0)}%</span>
                    </div>
                    <div className="w-full bg-gray-700 rounded-full h-1.5">
                      <div
                        className={`h-1.5 rounded-full ${tokenPct > 80 ? 'bg-red-500' : tokenPct > 50 ? 'bg-yellow-500' : 'bg-blue-500'}`}
                        style={{ width: `${Math.min(tokenPct, 100)}%` }}
                      />
                    </div>
                  </div>
                  <div className="w-24 text-right text-gray-400">
                    {formatCost(snap.costUsed)} ({costPct.toFixed(0)}%)
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Quality Rejections */}
      {data.qualityRejections.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Quality Rejections ({data.qualityRejections.length})
          </h3>
          <div className="space-y-3">
            {data.qualityRejections.map((rejection, i) => (
              <div key={i} className="border border-red-500/20 bg-red-500/5 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-red-400">
                    Task {rejection.taskId}
                  </span>
                  <span className="text-xs text-red-400">Score: {rejection.score}/5</span>
                </div>
                <p className="text-sm text-gray-400">{rejection.feedback}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Verification Steps */}
      {data.verification && data.verification.steps.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Verification Steps
          </h3>
          <div className="space-y-2">
            {data.verification.steps.map((step, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className={`flex-shrink-0 w-5 h-5 flex items-center justify-center rounded-full text-xs ${
                  step.passed ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                }`}>
                  {step.passed ? '\u2713' : '\u2717'}
                </span>
                <span className="text-sm text-gray-300">{step.description}</span>
              </div>
            ))}
          </div>
          <div className={`mt-3 text-sm font-medium ${data.verification.passed ? 'text-green-400' : 'text-red-400'}`}>
            {data.verification.summary}
          </div>
        </div>
      )}
    </div>
  );
}

// Helper components

function OverviewCard({
  label,
  value,
  subtext,
  status = 'neutral',
}: {
  label: string;
  value: string;
  subtext?: string;
  status?: 'good' | 'warn' | 'bad' | 'neutral';
}) {
  const borderColor = {
    good: 'border-green-500/30',
    warn: 'border-yellow-500/30',
    bad: 'border-red-500/30',
    neutral: 'border-gray-700',
  }[status];

  return (
    <div className={`bg-gray-900/50 border ${borderColor} rounded-lg p-4`}>
      <p className="text-xs text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-xl font-bold text-white mt-1">{value}</p>
      {subtext && <p className="text-xs text-gray-500 mt-1">{subtext}</p>}
    </div>
  );
}

function TaskStatusBadge({ status }: { status?: string }) {
  if (!status) return <span className="text-xs text-gray-500">-</span>;

  const styles: Record<string, string> = {
    completed: 'bg-green-500/20 text-green-400',
    dispatched: 'bg-blue-500/20 text-blue-400',
    failed: 'bg-red-500/20 text-red-400',
    skipped: 'bg-gray-500/20 text-gray-400',
  };

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${styles[status] || 'bg-gray-500/20 text-gray-400'}`}>
      {status}
    </span>
  );
}
