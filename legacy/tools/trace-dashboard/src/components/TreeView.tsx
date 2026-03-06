/**
 * Tree View Component
 *
 * Displays session hierarchy as a collapsible tree.
 */

import { useState } from 'react';
import { cn, formatDuration, getNodeTypeColor } from '../lib/utils';
import type { TreeNode } from '../lib/types';

interface TreeViewProps {
  root: TreeNode;
}

interface TreeNodeItemProps {
  node: TreeNode;
  depth: number;
  defaultExpanded?: boolean;
}

function TreeNodeItem({ node, depth, defaultExpanded = true }: TreeNodeItemProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded && depth < 2);
  const hasChildren = node.children && node.children.length > 0;

  const statusColors = {
    success: 'text-green-400',
    error: 'text-red-400',
    pending: 'text-yellow-400',
  };

  const typeEmojis: Record<string, string> = {
    session: '📊',
    iteration: '🔄',
    llm: '🤖',
    tool: '🔧',
    decision: '🎯',
    subagent: '👤',
    error: '❌',
  };

  return (
    <div className="select-none">
      <div
        className={cn(
          'flex items-center py-1.5 px-2 rounded hover:bg-gray-800/50 transition-colors',
          hasChildren && 'cursor-pointer'
        )}
        style={{ paddingLeft: `${depth * 1.5}rem` }}
        onClick={() => hasChildren && setIsExpanded(!isExpanded)}
      >
        {/* Expand/collapse indicator */}
        <div className="w-5 h-5 flex items-center justify-center text-gray-500">
          {hasChildren ? (
            <svg
              className={cn('w-4 h-4 transition-transform', isExpanded && 'rotate-90')}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          ) : (
            <span className="w-4" />
          )}
        </div>

        {/* Type emoji */}
        <span className="mr-2">{typeEmojis[node.type] || '📄'}</span>

        {/* Type badge */}
        <span
          className={cn(
            'text-xs font-medium px-1.5 py-0.5 rounded mr-2',
            getNodeTypeColor(node.type)
          )}
        >
          {node.type}
        </span>

        {/* Label */}
        <span className="text-gray-200 flex-1 truncate">{node.label}</span>

        {/* Status */}
        {node.status && (
          <span className={cn('text-xs ml-2', statusColors[node.status])}>
            {node.status}
          </span>
        )}

        {/* Duration */}
        {node.durationMs !== undefined && (
          <span className="text-xs text-gray-500 ml-2">
            {formatDuration(node.durationMs)}
          </span>
        )}

        {/* Metrics */}
        {node.metrics && Object.keys(node.metrics).length > 0 && (
          <div className="flex items-center gap-2 ml-2">
            {Object.entries(node.metrics).slice(0, 3).map(([key, value]) => (
              <span key={key} className="text-xs text-gray-500">
                {key}: {typeof value === 'number' && value > 1000
                  ? `${(value / 1000).toFixed(1)}K`
                  : value}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Children */}
      {isExpanded && hasChildren && (
        <div>
          {node.children.map((child, index) => (
            <TreeNodeItem
              key={child.id || index}
              node={child}
              depth={depth + 1}
              defaultExpanded={depth < 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function TreeView({ root }: TreeViewProps) {
  const [expandAll, setExpandAll] = useState(false);

  const toggleAllExpanded = () => {
    setExpandAll(!expandAll);
    // Force re-render by changing key
  };

  return (
    <div className="bg-gray-900/50 border border-gray-700 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800/50 border-b border-gray-700">
        <span className="text-sm font-medium text-gray-300">Session Tree</span>
        <button
          onClick={toggleAllExpanded}
          className="text-xs text-gray-400 hover:text-white transition-colors"
        >
          {expandAll ? 'Collapse All' : 'Expand All'}
        </button>
      </div>

      {/* Tree content */}
      <div className="p-2 font-mono text-sm overflow-x-auto" key={String(expandAll)}>
        <TreeNodeItem node={root} depth={0} defaultExpanded={expandAll} />
      </div>
    </div>
  );
}
