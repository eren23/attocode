/**
 * AgentInspector - Detail panel for a selected agent.
 *
 * Slides out from the right, showing agent metadata, token usage,
 * files accessed, findings posted, and data flows sent/received.
 */

import type { AgentNode, DataFlow } from '../../lib/agent-graph-types';
import { FLOW_TYPE_STYLES } from '../../lib/agent-graph-types';
import { formatTokens, formatCost } from '../../lib/utils';

interface AgentInspectorProps {
  agent: AgentNode | null;
  dataFlows: DataFlow[];
  onClose: () => void;
}

const STATUS_COLORS: Record<AgentNode['status'], string> = {
  running: '#f59e0b',
  completed: '#22c55e',
  failed: '#ef4444',
};

const TYPE_LABELS: Record<AgentNode['type'], string> = {
  root: 'Root Agent',
  subagent: 'Sub-Agent',
  orchestrator: 'Orchestrator',
  worker: 'Worker',
  judge: 'Judge',
  manager: 'Manager',
};

export function AgentInspector({ agent, dataFlows, onClose }: AgentInspectorProps) {
  if (!agent) return null;

  const sentFlows = dataFlows.filter((f) => f.sourceAgentId === agent.id);
  const receivedFlows = dataFlows.filter((f) => f.targetAgentId === agent.id);

  return (
    <div className="fixed right-0 top-0 bottom-0 w-96 bg-gray-900 border-l border-gray-800 z-50 shadow-2xl overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <span
            className="h-3 w-3 rounded-full"
            style={{ backgroundColor: STATUS_COLORS[agent.status] }}
          />
          <span className="text-sm font-medium text-white">{agent.label}</span>
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
        {/* Agent metadata */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Type</h4>
            <span className="text-sm text-white">{TYPE_LABELS[agent.type]}</span>
          </div>
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Status</h4>
            <span className="text-sm text-white capitalize">{agent.status}</span>
          </div>
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">Model</h4>
            <span className="text-xs text-white font-mono">{agent.model || 'N/A'}</span>
          </div>
          <div>
            <h4 className="text-xs font-medium text-gray-400 mb-1">ID</h4>
            <span className="text-xs text-gray-300 font-mono">{agent.id}</span>
          </div>
        </div>

        {/* Token usage */}
        <div className="border-t border-gray-800 pt-3">
          <h4 className="text-xs font-medium text-gray-400 mb-2">Resource Usage</h4>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <span className="text-xs text-gray-500">Tokens</span>
              <div className="text-sm text-white">{formatTokens(agent.tokensUsed)}</div>
            </div>
            <div>
              <span className="text-xs text-gray-500">Cost</span>
              <div className="text-sm text-white">{formatCost(agent.costUsed)}</div>
            </div>
          </div>
        </div>

        {/* Findings posted */}
        <div className="border-t border-gray-800 pt-3">
          <h4 className="text-xs font-medium text-gray-400 mb-1">Findings Posted</h4>
          <span className="text-sm text-white">{agent.findingsPosted}</span>
        </div>

        {/* Files accessed */}
        {agent.filesAccessed.length > 0 && (
          <div className="border-t border-gray-800 pt-3">
            <h4 className="text-xs font-medium text-gray-400 mb-2">
              Files Accessed ({agent.filesAccessed.length})
            </h4>
            <ul className="space-y-0.5 max-h-32 overflow-y-auto">
              {agent.filesAccessed.map((f) => (
                <li key={f} className="text-xs text-gray-300 font-mono truncate" title={f}>
                  {f}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Data flows sent */}
        {sentFlows.length > 0 && (
          <div className="border-t border-gray-800 pt-3">
            <h4 className="text-xs font-medium text-gray-400 mb-2">
              Data Flows Sent ({sentFlows.length})
            </h4>
            <div className="space-y-1.5 max-h-40 overflow-y-auto">
              {sentFlows.map((flow) => {
                const style = FLOW_TYPE_STYLES[flow.type];
                return (
                  <div
                    key={flow.id}
                    className="flex items-start gap-2 bg-gray-800/50 rounded p-1.5"
                  >
                    <span
                      className="h-2 w-2 rounded-full mt-1 shrink-0"
                      style={{ backgroundColor: style.color }}
                    />
                    <div className="min-w-0">
                      <div className="text-[10px] text-gray-400">
                        <span style={{ color: style.color }}>{style.label}</span>
                        {' -> '}
                        {flow.targetAgentId}
                      </div>
                      <div className="text-xs text-gray-300 truncate">
                        {flow.payload.summary}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Data flows received */}
        {receivedFlows.length > 0 && (
          <div className="border-t border-gray-800 pt-3">
            <h4 className="text-xs font-medium text-gray-400 mb-2">
              Data Flows Received ({receivedFlows.length})
            </h4>
            <div className="space-y-1.5 max-h-40 overflow-y-auto">
              {receivedFlows.map((flow) => {
                const style = FLOW_TYPE_STYLES[flow.type];
                return (
                  <div
                    key={flow.id}
                    className="flex items-start gap-2 bg-gray-800/50 rounded p-1.5"
                  >
                    <span
                      className="h-2 w-2 rounded-full mt-1 shrink-0"
                      style={{ backgroundColor: style.color }}
                    />
                    <div className="min-w-0">
                      <div className="text-[10px] text-gray-400">
                        {flow.sourceAgentId}
                        {' -> '}
                        <span style={{ color: style.color }}>{style.label}</span>
                      </div>
                      <div className="text-xs text-gray-300 truncate">
                        {flow.payload.summary}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Parent ID */}
        {agent.parentId && (
          <div className="border-t border-gray-800 pt-3">
            <h4 className="text-xs font-medium text-gray-400 mb-1">Parent Agent</h4>
            <span className="text-xs text-gray-300 font-mono">{agent.parentId}</span>
          </div>
        )}
      </div>
    </div>
  );
}
