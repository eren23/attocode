/**
 * AgentHierarchyTree - Vertical tree of agents with expand/collapse
 *
 * Shows root agent at top with children indented below. Each node displays
 * role icon, name, model, status dot, and token count. Supports
 * expand/collapse for agents with children, and click-to-select.
 */

import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { AgentNode } from '../../lib/agent-graph-types';
import { cn, formatTokens } from '../../lib/utils';

interface AgentHierarchyTreeProps {
  agents: AgentNode[];
  selectedAgentId: string | null;
  onSelectAgent: (id: string | null) => void;
  sessionId?: string;
}

/** Build a tree structure from the flat agent list */
interface TreeItem {
  agent: AgentNode;
  children: TreeItem[];
}

function buildTree(agents: AgentNode[]): TreeItem[] {
  const map = new Map<string, TreeItem>();
  const roots: TreeItem[] = [];

  for (const agent of agents) {
    map.set(agent.id, { agent, children: [] });
  }

  for (const agent of agents) {
    const item = map.get(agent.id)!;
    if (agent.parentId && map.has(agent.parentId)) {
      map.get(agent.parentId)!.children.push(item);
    } else {
      roots.push(item);
    }
  }

  return roots;
}

const STATUS_DOT_COLORS: Record<AgentNode['status'], string> = {
  running: 'bg-yellow-400 animate-pulse',
  completed: 'bg-green-400',
  failed: 'bg-red-400',
};

const ROLE_ICONS: Record<AgentNode['type'], JSX.Element> = {
  root: (
    <svg className="w-4 h-4 text-agent-root" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
    </svg>
  ),
  subagent: (
    <svg className="w-4 h-4 text-agent-worker" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
    </svg>
  ),
  orchestrator: (
    <svg className="w-4 h-4 text-agent-orchestrator" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
    </svg>
  ),
  worker: (
    <svg className="w-4 h-4 text-agent-worker" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  judge: (
    <svg className="w-4 h-4 text-agent-judge" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
    </svg>
  ),
  manager: (
    <svg className="w-4 h-4 text-agent-orchestrator" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
    </svg>
  ),
};

function TreeNodeRow({
  item,
  depth,
  selectedAgentId,
  onSelectAgent,
  expandedIds,
  onToggleExpand,
}: {
  item: TreeItem;
  depth: number;
  selectedAgentId: string | null;
  onSelectAgent: (id: string | null) => void;
  expandedIds: Set<string>;
  onToggleExpand: (id: string) => void;
}) {
  const { agent, children } = item;
  const hasChildren = children.length > 0;
  const isExpanded = expandedIds.has(agent.id);
  const isSelected = selectedAgentId === agent.id;

  return (
    <>
      <button
        onClick={() => onSelectAgent(isSelected ? null : agent.id)}
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 text-left rounded-md transition-colors',
          isSelected
            ? 'bg-blue-900/30 border border-blue-700/50'
            : 'hover:bg-gray-800/30 border border-transparent'
        )}
        style={{ paddingLeft: `${12 + depth * 20}px` }}
      >
        {/* Expand/collapse toggle */}
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand(agent.id);
            }}
            className="w-4 h-4 flex items-center justify-center text-gray-500 hover:text-gray-300 flex-shrink-0"
          >
            <svg
              className={cn('w-3 h-3 transition-transform', isExpanded && 'rotate-90')}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        ) : (
          <span className="w-4 flex-shrink-0" />
        )}

        {/* Connecting line indicator */}
        {depth > 0 && (
          <span className="w-0.5 h-4 bg-gray-700 flex-shrink-0 -ml-1 mr-1" />
        )}

        {/* Role icon */}
        <span className="flex-shrink-0">{ROLE_ICONS[agent.type]}</span>

        {/* Agent name */}
        <span className="text-sm text-gray-200 truncate flex-1 min-w-0">
          {agent.label}
        </span>

        {/* Model badge */}
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 flex-shrink-0 font-mono">
          {agent.model}
        </span>

        {/* Status dot */}
        <span
          className={cn('w-2 h-2 rounded-full flex-shrink-0', STATUS_DOT_COLORS[agent.status])}
          title={agent.status}
        />

        {/* Token count */}
        <span className="text-xs text-gray-500 flex-shrink-0 tabular-nums w-12 text-right">
          {formatTokens(agent.tokensUsed)}
        </span>
      </button>

      {/* Children */}
      {hasChildren && isExpanded && (
        <div className="relative">
          {/* Vertical connector line */}
          <div
            className="absolute top-0 bottom-0 w-px bg-gray-700/50"
            style={{ left: `${24 + depth * 20}px` }}
          />
          {children.map((child) => (
            <TreeNodeRow
              key={child.agent.id}
              item={child}
              depth={depth + 1}
              selectedAgentId={selectedAgentId}
              onSelectAgent={onSelectAgent}
              expandedIds={expandedIds}
              onToggleExpand={onToggleExpand}
            />
          ))}
        </div>
      )}
    </>
  );
}

export function AgentHierarchyTree({
  agents,
  selectedAgentId,
  onSelectAgent,
  sessionId,
}: AgentHierarchyTreeProps) {
  const tree = useMemo(() => buildTree(agents), [agents]);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => {
    // Expand all by default
    return new Set(agents.map((a) => a.id));
  });

  const handleToggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  if (agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
        No agent hierarchy data
      </div>
    );
  }

  return (
    <div className="space-y-0.5">
      {sessionId && (
        <div className="flex justify-end mb-2">
          <Link
            to={`/topology/${encodeURIComponent(sessionId)}`}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            View Topology →
          </Link>
        </div>
      )}
      {tree.map((item) => (
        <TreeNodeRow
          key={item.agent.id}
          item={item}
          depth={0}
          selectedAgentId={selectedAgentId}
          onSelectAgent={onSelectAgent}
          expandedIds={expandedIds}
          onToggleExpand={handleToggleExpand}
        />
      ))}

      {/* Legend */}
      <div className="mt-3 pt-2 border-t border-gray-800 flex flex-wrap gap-3 text-[10px] text-gray-500">
        {(
          [
            ['root', 'Root'],
            ['orchestrator', 'Orchestrator'],
            ['worker', 'Worker'],
            ['judge', 'Judge'],
          ] as const
        ).map(([type, label]) => (
          <span key={type} className="flex items-center gap-1">
            {ROLE_ICONS[type]}
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
