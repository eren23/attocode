/**
 * BlackboardPanel - Side panel showing real-time blackboard findings.
 *
 * Displays findings with topic, type, agent, and confidence badges,
 * plus a claims section below.
 */

import type { BlackboardSnapshot } from '../../lib/agent-graph-types';
import { cn } from '../../lib/utils';

interface BlackboardPanelProps {
  blackboard: BlackboardSnapshot | null;
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return 'bg-green-500/20 text-green-400 border-green-500/30';
  if (confidence >= 0.4) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
  return 'bg-red-500/20 text-red-400 border-red-500/30';
}

function confidenceLabel(confidence: number): string {
  if (confidence >= 0.7) return 'High';
  if (confidence >= 0.4) return 'Medium';
  return 'Low';
}

export function BlackboardPanel({ blackboard }: BlackboardPanelProps) {
  if (!blackboard) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Blackboard</h3>
        <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
          No blackboard data
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-400">Blackboard</h3>
        <span className="text-[10px] text-gray-500">
          {blackboard.findings.length} findings, {blackboard.claims.length} claims
        </span>
      </div>

      {/* Findings list */}
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {blackboard.findings.length === 0 && (
          <div className="text-xs text-gray-500 py-2">No findings yet</div>
        )}
        {blackboard.findings.map((finding) => (
          <div
            key={finding.id}
            className="bg-gray-800/50 rounded p-2 border border-gray-700/50"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] font-medium text-blue-400 uppercase tracking-wider">
                {finding.topic}
              </span>
              <span className="text-[10px] text-gray-500">{finding.type}</span>
              <span
                className={cn(
                  'ml-auto text-[10px] px-1.5 py-0.5 rounded border',
                  confidenceColor(finding.confidence)
                )}
              >
                {confidenceLabel(finding.confidence)} ({(finding.confidence * 100).toFixed(0)}%)
              </span>
            </div>
            <p className="text-xs text-gray-300 leading-relaxed line-clamp-2">
              {finding.content}
            </p>
            <div className="mt-1 text-[10px] text-gray-500">
              by {finding.agentId}
            </div>
          </div>
        ))}
      </div>

      {/* Claims section */}
      {blackboard.claims.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-800">
          <h4 className="text-xs font-medium text-gray-500 mb-2">Active Claims</h4>
          <div className="space-y-1">
            {blackboard.claims.map((claim, i) => (
              <div
                key={`${claim.resource}-${i}`}
                className="flex items-center gap-2 text-[10px]"
              >
                <span className="text-amber-400 font-mono truncate max-w-[120px]" title={claim.resource}>
                  {claim.resource}
                </span>
                <span className="text-gray-600">by</span>
                <span className="text-gray-400">{claim.agentId}</span>
                <span className="text-gray-600 ml-auto">{claim.type}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Updated timestamp */}
      {blackboard.updatedAt && (
        <div className="mt-2 text-[10px] text-gray-600 text-right">
          Updated: {new Date(blackboard.updatedAt).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
