/**
 * Compare Page
 *
 * Side-by-side comparison of two sessions.
 */

import { useState } from 'react';
import { useSessions, useCompare } from '../hooks/useApi';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { MetricCard } from '../components/MetricCard';
import {
  formatTokens,
  formatCost,
  formatDuration,
  formatPercent,
  cn,
} from '../lib/utils';

export function ComparePage() {
  const { data: sessions, loading: loadingSessions } = useSessions();
  const [sessionA, setSessionA] = useState<string>('');
  const [sessionB, setSessionB] = useState<string>('');

  const { data: comparison, loading: loadingComparison } = useCompare(
    sessionA || undefined,
    sessionB || undefined
  );

  if (loadingSessions) {
    return <LoadingSpinner size="lg" text="Loading sessions..." />;
  }

  if (!sessions || sessions.length < 2) {
    return (
      <div className="text-center py-12">
        <h3 className="text-lg font-medium text-gray-300 mb-2">Need More Sessions</h3>
        <p className="text-gray-500">
          At least 2 sessions are required for comparison.
        </p>
      </div>
    );
  }

  const assessmentColors = {
    improved: 'text-green-400',
    regressed: 'text-red-400',
    mixed: 'text-yellow-400',
    similar: 'text-gray-400',
  };

  const assessmentLabels = {
    improved: 'Improved',
    regressed: 'Regressed',
    mixed: 'Mixed Results',
    similar: 'Similar',
  };

  const renderDiff = (value: number, inverse = false) => {
    const isPositive = inverse ? value < 0 : value > 0;
    const isNegative = inverse ? value > 0 : value < 0;
    const formatted = value > 0 ? `+${value.toFixed(2)}` : value.toFixed(2);

    return (
      <span
        className={cn(
          'font-mono',
          isPositive && 'text-green-400',
          isNegative && 'text-red-400',
          !isPositive && !isNegative && 'text-gray-400'
        )}
      >
        {formatted}
      </span>
    );
  };

  const renderPercentChange = (value: number, inverse = false) => {
    const isPositive = inverse ? value < 0 : value > 0;
    const isNegative = inverse ? value > 0 : value < 0;
    const formatted = value > 0 ? `+${value.toFixed(1)}%` : `${value.toFixed(1)}%`;

    return (
      <span
        className={cn(
          'text-sm',
          isPositive && 'text-green-400',
          isNegative && 'text-red-400',
          !isPositive && !isNegative && 'text-gray-400'
        )}
      >
        ({formatted})
      </span>
    );
  };

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Compare Sessions</h1>

      {/* Session Selection */}
      <div className="grid md:grid-cols-2 gap-4 mb-8">
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-2">
            Baseline Session (A)
          </label>
          <select
            value={sessionA}
            onChange={(e) => setSessionA(e.target.value)}
            className="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none focus:border-blue-500 transition-colors"
          >
            <option value="">Select session...</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.filePath}>
                {s.task.slice(0, 60)} - {s.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-2">
            Comparison Session (B)
          </label>
          <select
            value={sessionB}
            onChange={(e) => setSessionB(e.target.value)}
            className="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none focus:border-blue-500 transition-colors"
          >
            <option value="">Select session...</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.filePath}>
                {s.task.slice(0, 60)} - {s.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Loading state */}
      {sessionA && sessionB && loadingComparison && (
        <LoadingSpinner text="Comparing sessions..." />
      )}

      {/* Comparison Results */}
      {comparison && (
        <div className="space-y-6">
          {/* Overall Assessment */}
          <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-6 text-center">
            <h2 className="text-sm font-medium text-gray-400 mb-2">Overall Assessment</h2>
            <p className={cn('text-3xl font-bold', assessmentColors[comparison.assessment])}>
              {assessmentLabels[comparison.assessment]}
            </p>
            <div className="mt-4 flex justify-center gap-8">
              {comparison.improvements.length > 0 && (
                <div>
                  <span className="text-green-400 font-medium">{comparison.improvements.length}</span>
                  <span className="text-gray-400 ml-1">improvements</span>
                </div>
              )}
              {comparison.regressions.length > 0 && (
                <div>
                  <span className="text-red-400 font-medium">{comparison.regressions.length}</span>
                  <span className="text-gray-400 ml-1">regressions</span>
                </div>
              )}
            </div>
          </div>

          {/* Metrics Comparison Grid */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <MetricCard
              label="Iterations"
              value={
                <div className="flex items-baseline gap-2">
                  <span>{comparison.baseline.metrics.iterations}</span>
                  <span className="text-gray-500">→</span>
                  <span>{comparison.comparison.metrics.iterations}</span>
                  {renderDiff(comparison.metricDiffs.iterations, true)}
                </div>
              }
              status={comparison.metricDiffs.iterations > 2 ? 'bad' : comparison.metricDiffs.iterations < -2 ? 'good' : 'neutral'}
            />
            <MetricCard
              label="Tokens"
              value={
                <div className="flex items-baseline gap-2">
                  <span>{formatTokens(comparison.baseline.metrics.totalTokens)}</span>
                  <span className="text-gray-500">→</span>
                  <span>{formatTokens(comparison.comparison.metrics.totalTokens)}</span>
                </div>
              }
              subtext={renderPercentChange(comparison.percentChanges.tokens, true)}
              status={comparison.percentChanges.tokens > 20 ? 'bad' : comparison.percentChanges.tokens < -20 ? 'good' : 'neutral'}
            />
            <MetricCard
              label="Cost"
              value={
                <div className="flex items-baseline gap-2">
                  <span>{formatCost(comparison.baseline.metrics.cost)}</span>
                  <span className="text-gray-500">→</span>
                  <span>{formatCost(comparison.comparison.metrics.cost)}</span>
                </div>
              }
              subtext={renderPercentChange(comparison.percentChanges.cost, true)}
              status={comparison.metricDiffs.cost > 0.01 ? 'bad' : comparison.metricDiffs.cost < -0.01 ? 'good' : 'neutral'}
            />
            <MetricCard
              label="Cache Hit Rate"
              value={
                <div className="flex items-baseline gap-2">
                  <span>{formatPercent(comparison.baseline.metrics.cacheHitRate)}</span>
                  <span className="text-gray-500">→</span>
                  <span>{formatPercent(comparison.comparison.metrics.cacheHitRate)}</span>
                </div>
              }
              status={comparison.metricDiffs.cacheHitRate > 0.1 ? 'good' : comparison.metricDiffs.cacheHitRate < -0.1 ? 'bad' : 'neutral'}
            />
            <MetricCard
              label="Errors"
              value={
                <div className="flex items-baseline gap-2">
                  <span>{comparison.baseline.metrics.errors}</span>
                  <span className="text-gray-500">→</span>
                  <span>{comparison.comparison.metrics.errors}</span>
                  {renderDiff(comparison.metricDiffs.errors, true)}
                </div>
              }
              status={comparison.metricDiffs.errors > 0 ? 'bad' : comparison.metricDiffs.errors < 0 ? 'good' : 'neutral'}
            />
          </div>

          {/* Changes List */}
          <div className="grid md:grid-cols-2 gap-6">
            {/* Improvements */}
            <div className="bg-green-900/20 border border-green-700/50 rounded-lg p-4">
              <h3 className="text-sm font-medium text-green-400 mb-3 flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                </svg>
                Improvements
              </h3>
              {comparison.improvements.length > 0 ? (
                <ul className="space-y-2">
                  {comparison.improvements.map((item, i) => (
                    <li key={i} className="text-sm text-green-200">{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-500">No improvements detected</p>
              )}
            </div>

            {/* Regressions */}
            <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4">
              <h3 className="text-sm font-medium text-red-400 mb-3 flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                </svg>
                Regressions
              </h3>
              {comparison.regressions.length > 0 ? (
                <ul className="space-y-2">
                  {comparison.regressions.map((item, i) => (
                    <li key={i} className="text-sm text-red-200">{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-500">No regressions detected</p>
              )}
            </div>
          </div>

          {/* Side-by-side summaries */}
          <div className="grid md:grid-cols-2 gap-6">
            <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Session A (Baseline)</h3>
              <div className="space-y-2 text-sm">
                <p><span className="text-gray-500">Task:</span> {comparison.baseline.meta.task}</p>
                <p><span className="text-gray-500">Model:</span> {comparison.baseline.meta.model}</p>
                <p><span className="text-gray-500">Duration:</span> {formatDuration(comparison.baseline.meta.duration)}</p>
                <p><span className="text-gray-500">Tool Calls:</span> {comparison.baseline.metrics.toolCalls}</p>
                <p><span className="text-gray-500">Unique Tools:</span> {comparison.baseline.metrics.uniqueTools}</p>
              </div>
            </div>
            <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Session B (Comparison)</h3>
              <div className="space-y-2 text-sm">
                <p><span className="text-gray-500">Task:</span> {comparison.comparison.meta.task}</p>
                <p><span className="text-gray-500">Model:</span> {comparison.comparison.meta.model}</p>
                <p><span className="text-gray-500">Duration:</span> {formatDuration(comparison.comparison.meta.duration)}</p>
                <p><span className="text-gray-500">Tool Calls:</span> {comparison.comparison.metrics.toolCalls}</p>
                <p><span className="text-gray-500">Unique Tools:</span> {comparison.comparison.metrics.uniqueTools}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!sessionA || !sessionB ? (
        <div className="text-center py-12 text-gray-500">
          Select two sessions above to compare them
        </div>
      ) : null}
    </div>
  );
}
