/**
 * AgentNode - Agent node card component for the topology graph.
 *
 * Rendered as an absolute-positioned div (like TaskNode) showing:
 * - Role icon and agent label
 * - Model name
 * - Status indicator
 * - Token count and cost
 */

import { cn } from '../../lib/utils';
import { formatTokens, formatCost } from '../../lib/utils';
import type { AgentNode as AgentNodeType } from '../../lib/agent-graph-types';

interface AgentNodeProps {
  agent: AgentNodeType;
  onClick?: (id: string) => void;
  selected?: boolean;
}

/** Role-based ring/border colors */
const ROLE_STYLES: Record<AgentNodeType['type'], string> = {
  root: 'border-purple-500/60 ring-purple-500/30',
  worker: 'border-blue-500/60 ring-blue-500/30',
  orchestrator: 'border-amber-500/60 ring-amber-500/30',
  subagent: 'border-cyan-500/60 ring-cyan-500/30',
  judge: 'border-violet-500/60 ring-violet-500/30',
  manager: 'border-amber-500/60 ring-amber-500/30',
};

/** Status indicator colors */
const STATUS_COLORS: Record<AgentNodeType['status'], string> = {
  running: '#f59e0b',
  completed: '#22c55e',
  failed: '#ef4444',
};

/** Status background classes */
const STATUS_BG: Record<AgentNodeType['status'], string> = {
  running: 'bg-amber-900/20',
  completed: 'bg-emerald-900/20',
  failed: 'bg-red-900/20',
};

/** Role icon SVG paths */
function RoleIcon({ type }: { type: AgentNodeType['type'] }) {
  const iconClass = 'w-4 h-4 shrink-0';

  switch (type) {
    case 'root':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m8.66-13.66l-.71.71M4.05 19.95l-.71.71M21 12h-1M4 12H3m16.95 7.95l-.71-.71M4.05 4.05l-.71-.71" />
          <circle cx="12" cy="12" r="4" />
        </svg>
      );
    case 'orchestrator':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
        </svg>
      );
    case 'worker':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      );
    case 'judge':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
        </svg>
      );
    case 'manager':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
        </svg>
      );
    case 'subagent':
    default:
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      );
  }
}

function shortModelName(model: string): string {
  if (!model) return '';
  const parts = model.split('/');
  const name = parts[parts.length - 1];
  return name.length > 14 ? name.slice(0, 12) + '..' : name;
}

export function AgentNode({ agent, onClick, selected }: AgentNodeProps) {
  const label = agent.label.length > 20 ? agent.label.slice(0, 18) + '..' : agent.label;

  return (
    <div
      className={cn(
        'w-48 rounded-lg border-2 px-3 py-2.5 cursor-pointer transition-all',
        'hover:ring-1 hover:ring-white/20',
        STATUS_BG[agent.status],
        ROLE_STYLES[agent.type],
        selected && 'ring-2 ring-blue-400 border-blue-500'
      )}
      onClick={() => onClick?.(agent.id)}
    >
      {/* Header: role icon + label */}
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-gray-300">
          <RoleIcon type={agent.type} />
        </span>
        <span className="text-xs font-medium text-white truncate">{label}</span>
      </div>

      {/* Model + Status */}
      <div className="flex items-center justify-between mb-1.5">
        {agent.model && (
          <span className="text-[10px] text-gray-500 font-mono truncate">
            {shortModelName(agent.model)}
          </span>
        )}
        <div className="flex items-center gap-1 ml-auto">
          <span
            className="h-2 w-2 rounded-full shrink-0"
            style={{ backgroundColor: STATUS_COLORS[agent.status] }}
          />
          <span className="text-[10px] text-gray-400 capitalize">{agent.status}</span>
        </div>
      </div>

      {/* Token count + cost */}
      <div className="flex items-center justify-between text-[10px] text-gray-500 border-t border-gray-700/50 pt-1.5 mt-1">
        <span>{formatTokens(agent.tokensUsed)} tokens</span>
        <span>{formatCost(agent.costUsed)}</span>
      </div>

      {/* Active indicator */}
      {agent.status === 'running' && (
        <div className="mt-1.5 h-0.5 bg-amber-500/30 rounded overflow-hidden">
          <div className="h-full w-1/3 bg-amber-500 rounded animate-pulse" />
        </div>
      )}
    </div>
  );
}

// Export layout constants used by AgentGraph
export const AGENT_NODE_WIDTH = 192; // w-48 = 12rem = 192px
export const AGENT_NODE_HEIGHT = 88;
