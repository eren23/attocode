/**
 * TaskInspector - Slide-out detail panel for a selected task
 *
 * V5: Added on-demand worker output loading, retry history,
 * closure report display, and quality feedback from rejected attempts.
 * V9: Added tool call count display, auto-load for failed tasks.
 */

import { useState, useCallback, useEffect } from 'react';
import type { SwarmTask, TaskDetail } from '../../lib/swarm-types';
import { SWARM_STATUS_COLORS } from '../../lib/swarm-types';
import { formatTokens, formatCost, formatDuration } from '../../lib/utils';

interface TaskInspectorProps {
  task: SwarmTask | null;
  onClose: () => void;
  dir?: string;
}

export function TaskInspector({ task, onClose, dir }: TaskInspectorProps) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [outputExpanded, setOutputExpanded] = useState(false);

  const loadDetail = useCallback(async () => {
    if (!task) return;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const params = new URLSearchParams();
      if (dir) params.set('dir', dir);
      const url = `/api/swarm/task/${task.id}${params.toString() ? `?${params}` : ''}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.success && data.data) {
        setDetail(data.data);
      } else {
        setDetailError('No detail available for this task');
      }
    } catch {
      setDetailError('Failed to load task details');
    } finally {
      setDetailLoading(false);
    }
  }, [task, dir]);

  // Reset detail when task changes
  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    setOutputExpanded(false);
  }, [task?.id]);

  // V9: Auto-load detail for failed tasks (so users can see what went wrong)
  useEffect(() => {
    if (task && task.status === 'failed' && !detail && !detailLoading) {
      loadDetail();
    }
  }, [task, task?.status, detail, detailLoading, loadDetail]);

  if (!task) return null;

  return (
    <div className="fixed right-0 top-0 bottom-0 w-96 bg-gray-900 border-l border-gray-800 z-50 shadow-2xl overflow-y-auto">
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

        {/* Retry Context / Quality Rejection History */}
        {task.retryContext && (
          <div className="border-t border-gray-800 pt-3">
            <h4 className="text-xs font-medium text-red-400 mb-2">
              Retry Context (Attempt {task.retryContext.attempt})
            </h4>
            <div className="bg-gray-800/50 rounded p-2">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs text-gray-400">Score:</span>
                <span className={`text-xs font-medium ${task.retryContext.previousScore === 0 ? 'text-red-400' : 'text-yellow-400'}`}>
                  {task.retryContext.previousScore === 0 ? 'FAILED' : `${task.retryContext.previousScore}/5`}
                </span>
              </div>
              <p className="text-xs text-gray-300 whitespace-pre-wrap">
                {task.retryContext.previousFeedback}
              </p>
            </div>
          </div>
        )}

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

        {/* Load Details Button — on-demand fetch of full worker output */}
        {(task.status === 'completed' || task.status === 'failed') && !detail && (
          <div className="border-t border-gray-800 pt-3">
            <button
              onClick={loadDetail}
              disabled={detailLoading}
              className="w-full px-3 py-2 text-xs font-medium bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded transition-colors"
            >
              {detailLoading ? 'Loading...' : 'Load Worker Output'}
            </button>
            {detailError && (
              <p className="text-xs text-gray-500 mt-1">{detailError}</p>
            )}
          </div>
        )}

        {/* Worker Output (loaded on demand) */}
        {detail && (
          <div className="border-t border-gray-800 pt-3 space-y-3">
            {/* V9: Tool call count */}
            {detail.toolCalls !== undefined && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">Tool Calls:</span>
                <span className={`text-xs font-medium ${detail.toolCalls === 0 ? 'text-red-400' : 'text-green-400'}`}>
                  {detail.toolCalls === -1 ? 'Timeout' : detail.toolCalls}
                </span>
              </div>
            )}

            {/* Worker Output */}
            {detail.output && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <h4 className="text-xs font-medium text-gray-400">Worker Output</h4>
                  <button
                    onClick={() => setOutputExpanded(!outputExpanded)}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    {outputExpanded ? 'Collapse' : 'Expand'}
                  </button>
                </div>
                <pre className={`text-xs text-gray-300 bg-gray-800/50 rounded p-2 overflow-x-auto whitespace-pre-wrap ${outputExpanded ? '' : 'max-h-40 overflow-y-auto'}`}>
                  {detail.output}
                </pre>
              </div>
            )}

            {/* Quality Feedback from detail */}
            {detail.qualityFeedback && (
              <div>
                <h4 className="text-xs font-medium text-gray-400 mb-1">Judge Feedback</h4>
                <p className="text-xs text-gray-300 bg-gray-800/50 rounded p-2">{detail.qualityFeedback}</p>
              </div>
            )}

            {/* Closure Report */}
            {detail.closureReport && (
              <div>
                <h4 className="text-xs font-medium text-gray-400 mb-2">Closure Report</h4>
                <div className="space-y-2">
                  {detail.closureReport.findings && detail.closureReport.findings.length > 0 && (
                    <div>
                      <span className="text-xs text-blue-400">Findings</span>
                      <ul className="space-y-0.5 mt-0.5">
                        {detail.closureReport.findings.map((f, i) => (
                          <li key={i} className="text-xs text-gray-300">- {f}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {detail.closureReport.actionsTaken && detail.closureReport.actionsTaken.length > 0 && (
                    <div>
                      <span className="text-xs text-green-400">Actions Taken</span>
                      <ul className="space-y-0.5 mt-0.5">
                        {detail.closureReport.actionsTaken.map((a, i) => (
                          <li key={i} className="text-xs text-gray-300">- {a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {detail.closureReport.failures && detail.closureReport.failures.length > 0 && (
                    <div>
                      <span className="text-xs text-red-400">Failures</span>
                      <ul className="space-y-0.5 mt-0.5">
                        {detail.closureReport.failures.map((f, i) => (
                          <li key={i} className="text-xs text-gray-300">- {f}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {detail.closureReport.remainingWork && detail.closureReport.remainingWork.length > 0 && (
                    <div>
                      <span className="text-xs text-yellow-400">Remaining Work</span>
                      <ul className="space-y-0.5 mt-0.5">
                        {detail.closureReport.remainingWork.map((r, i) => (
                          <li key={i} className="text-xs text-gray-300">- {r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
