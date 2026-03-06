/**
 * Issue Card Component
 *
 * Displays a detected inefficiency/issue with severity coloring.
 */

import { getSeverityColor } from '../lib/utils';

interface Issue {
  id: string;
  type: string;
  severity: string;
  description: string;
  evidence: string;
  suggestedFix?: string;
  iterations?: number[];
}

interface IssueCardProps {
  issue: Issue;
}

export function IssueCard({ issue }: IssueCardProps) {
  const severityIcons = {
    critical: (
      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
        <path
          fillRule="evenodd"
          d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
          clipRule="evenodd"
        />
      </svg>
    ),
    high: (
      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
        <path
          fillRule="evenodd"
          d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
          clipRule="evenodd"
        />
      </svg>
    ),
    medium: (
      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
        <path
          fillRule="evenodd"
          d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
          clipRule="evenodd"
        />
      </svg>
    ),
    low: (
      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
        <path
          fillRule="evenodd"
          d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
          clipRule="evenodd"
        />
      </svg>
    ),
  };

  const typeLabels: Record<string, string> = {
    excessive_iterations: 'Excessive Iterations',
    cache_inefficiency: 'Cache Inefficiency',
    redundant_tool_calls: 'Redundant Tool Calls',
    error_loop: 'Error Loop',
    plan_thrashing: 'Plan Thrashing',
    memory_miss: 'Memory Miss',
    slow_tool: 'Slow Tool',
    token_spike: 'Token Spike',
    thinking_overhead: 'Thinking Overhead',
  };

  return (
    <div
      className={`rounded-lg border p-4 ${getSeverityColor(issue.severity)}`}
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0">
          {severityIcons[issue.severity as keyof typeof severityIcons] || severityIcons.low}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h4 className="font-medium">
              {typeLabels[issue.type] || issue.type}
            </h4>
            <span className="text-xs uppercase font-semibold opacity-70">
              {issue.severity}
            </span>
          </div>
          <p className="text-sm opacity-90">{issue.description}</p>
          <p className="text-sm opacity-70 mt-1">{issue.evidence}</p>
          {issue.suggestedFix && (
            <p className="text-sm mt-2 opacity-80">
              <span className="font-medium">Fix:</span> {issue.suggestedFix}
            </p>
          )}
          {issue.iterations && issue.iterations.length > 0 && (
            <p className="text-xs mt-2 opacity-60">
              Iterations: {issue.iterations.join(', ')}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
