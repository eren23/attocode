/**
 * TaskInspector - Slide-out detail panel for a selected task
 */

import type { SwarmTask } from '../../lib/swarm-types';
import { SWARM_STATUS_COLORS } from '../../lib/swarm-types';
import { formatTokens, formatCost, formatDuration } from '../../lib/utils';

interface TaskInspectorProps {
  task: SwarmTask | null;
  onClose: () => void;
}

export function TaskInspector({ task, onClose }: TaskInspectorProps) {
  if (!task) return null;

  return (
    <div className="fixed right-0 top-0 bottom-0 w-80 bg-gray-900 border-l border-gray-800 z-50 shadow-2xl overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <span
            className="h-3 w-3 rounded-full"
            style={{ backgroundColor: SWARM_STATUS_COLORS[task.status] }}
          />
          <span className="text-sm font-medium text-white">{task.id}</span>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Description */}
        <div>
          <h4 className="text-xs font-medium text-gray-400 mb-1">Description</h4>
          <p className="text-sm text-gray-300">{task.description}</p>
        </div>

        {/* Status & Meta */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Status</h4>
            <span className="text-sm text-white capitalize">{task.status}</span>
          </div>
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Wave</h4>
            <span className="text-sm text-white">{task.wave}</span>
          </div>
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Type</h4>
            <span className="text-sm text-white capitalize">{task.type}</span>
          </div>
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Complexity</h4>
            <span className="text-sm text-white">{task.complexity}/10</span>
          </div>
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Attempts</h4>
            <span className="text-sm text-white">{task.attempts}</span>
          </div>
          {task.assignedModel && (
            <div>
              <h4 className="text-xs font-medium text-gray-400 mb-1">Model</h4>
              <span className="text-xs text-white font-mono">{task.assignedModel.split('/').pop()}</span>
            </div>
          )}
        </div>

        {/* Dependencies */}
        {task.dependencies.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Dependencies</h4>
            <div className="flex flex-wrap gap-1">
              {task.dependencies.map((dep) => (
                <span key={dep} className="px-1.5 py-0.5 text-xs bg-gray-800 rounded text-gray-400">
                  {dep}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Target Files */}
        {task.targetFiles && task.targetFiles.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Target Files</h4>
            <ul className="space-y-0.5">
              {task.targetFiles.map((f) => (
                <li key={f} className="text-xs text-gray-300 font-mono truncate">{f}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Result Details */}
        {task.result && (
          <>
            <div className="border-t border-gray-800 pt-3">
              <h4 className="text-xs font-medium text-gray-400 mb-2">Result</h4>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="text-xs text-gray-500">Tokens</span>
                  <div className="text-sm text-white">{formatTokens(task.result.tokensUsed)}</div>
                </div>
                <div>
                  <span className="text-xs text-gray-500">Cost</span>
                  <div className="text-sm text-white">{formatCost(task.result.costUsed)}</div>
                </div>
                <div>
                  <span className="text-xs text-gray-500">Duration</span>
                  <div className="text-sm text-white">{formatDuration(task.result.durationMs)}</div>
                </div>
                {task.result.qualityScore !== undefined && (
                  <div>
                    <span className="text-xs text-gray-500">Quality</span>
                    <div className="text-sm text-yellow-400">{task.result.qualityScore}/5</div>
                  </div>
                )}
              </div>
            </div>

            {task.result.qualityFeedback && (
              <div>
                <h4 className="text-xs font-medium text-gray-400 mb-1">Quality Feedback</h4>
                <p className="text-xs text-gray-300">{task.result.qualityFeedback}</p>
              </div>
            )}

            {task.result.filesModified && task.result.filesModified.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-gray-400 mb-1">Files Modified</h4>
                <ul className="space-y-0.5">
                  {task.result.filesModified.map((f) => (
                    <li key={f} className="text-xs text-green-400 font-mono truncate">{f}</li>
                  ))}
                </ul>
              </div>
            )}

            {task.result.findings && task.result.findings.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-gray-400 mb-1">Findings</h4>
                <ul className="space-y-1">
                  {task.result.findings.map((f, i) => (
                    <li key={i} className="text-xs text-gray-300">{f}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
