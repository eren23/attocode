/**
 * Tree View
 *
 * Generates a hierarchical view of a trace session.
 */

import type { ParsedSession, ParsedIteration, TreeNode } from '../types.js';

/**
 * Truncate a string to a max length with ellipsis.
 */
function truncate(s: string | undefined, len: number): string {
  if (!s) return '';
  return s.length > len ? s.slice(0, len) + '...' : s;
}

/**
 * Build an informative tool label from tool name and input.
 */
function getToolSummary(tool: ParsedIteration['tools'][0]): string {
  const input = tool.input ?? tool.arguments;
  if (!input) return tool.name;

  switch (tool.name) {
    case 'bash':
      return `bash - "${truncate(input.command as string, 50)}"`;
    case 'read_file':
    case 'edit_file':
    case 'write_file':
      return `${tool.name} - ${truncate(input.path as string, 50)}`;
    case 'grep':
      return `grep - "${truncate(input.pattern as string, 30)}"`;
    case 'list_files':
      return `list_files - ${truncate((input.path || '.') as string, 40)}`;
    case 'glob':
      return `glob - ${truncate(input.pattern as string, 40)}`;
    case 'search':
      return `search - "${truncate(input.query as string, 40)}"`;
    default:
      return tool.name;
  }
}

/**
 * Tree view data.
 */
export interface TreeViewData {
  /** Root node (session) */
  root: TreeNode;
}

/**
 * Generates tree view data.
 */
export class TreeView {
  private session: ParsedSession;

  constructor(session: ParsedSession) {
    this.session = session;
  }

  /**
   * Generate tree view data.
   */
  generate(): TreeViewData {
    const root: TreeNode = {
      id: this.session.sessionId,
      type: 'session',
      label: `Session: ${this.session.task.slice(0, 40)}${this.session.task.length > 40 ? '...' : ''}`,
      durationMs: this.session.durationMs,
      status: this.session.status === 'completed' ? 'success' : this.session.status === 'failed' ? 'error' : 'pending',
      children: [],
      metrics: {
        iterations: this.session.metrics.iterations,
        tokens: this.session.metrics.inputTokens + this.session.metrics.outputTokens,
        cost: this.session.metrics.totalCost,
      },
    };

    // Add iteration children
    for (const iter of this.session.iterations) {
      const iterNode: TreeNode = {
        id: `iter-${iter.number}`,
        type: 'iteration',
        label: `Iteration ${iter.number}`,
        durationMs: iter.durationMs,
        status: this.getIterationStatus(iter),
        children: [],
        metrics: {
          tokens: iter.metrics.inputTokens + iter.metrics.outputTokens,
          tools: iter.tools.length,
          cacheHitRate: Math.round(iter.metrics.cacheHitRate * 100),
        },
      };

      // Add LLM call
      if (iter.llm) {
        iterNode.children.push({
          id: `llm-${iter.llm.requestId}`,
          type: 'llm',
          label: `LLM Call (${iter.llm.model})`,
          durationMs: iter.llm.durationMs,
          status: 'success',
          children: [],
          metrics: {
            inputTokens: iter.llm.inputTokens,
            outputTokens: iter.llm.outputTokens,
            cacheHitRate: Math.round(iter.llm.cacheHitRate * 100),
          },
        });
      }

      // Interleave decisions and tools chronologically
      // Each decision (policy check) typically precedes its corresponding tool execution
      const maxLen = Math.max(iter.decisions.length, iter.tools.length);
      for (let i = 0; i < maxLen; i++) {
        // Add decision first (policy check happens before tool execution)
        if (i < iter.decisions.length) {
          const decision = iter.decisions[i];
          iterNode.children.push({
            id: `dec-${decision.type}-${iter.number}-${i}`,
            type: 'decision',
            label: `Decision: ${decision.type}`,
            status: decision.outcome === 'blocked' ? 'error' : 'success',
            children: [],
            metrics: {},
          });
        }

        // Then add the corresponding tool execution
        if (i < iter.tools.length) {
          const tool = iter.tools[i];
          iterNode.children.push({
            id: `tool-${tool.executionId}`,
            type: 'tool',
            label: `Tool: ${getToolSummary(tool)}`,
            durationMs: tool.durationMs,
            status: tool.status === 'success' ? 'success' : 'error',
            children: [],
            metrics: tool.resultSize ? { resultSize: tool.resultSize } : {},
          });
        }
      }

      root.children.push(iterNode);
    }

    // Add subagent links
    for (const link of this.session.subagentLinks) {
      root.children.push({
        id: `subagent-${link.childSessionId}`,
        type: 'subagent',
        label: `Subagent: ${link.agentType}`,
        durationMs: link.durationMs,
        status: link.success ? 'success' : link.success === false ? 'error' : 'pending',
        children: [],
        metrics: {
          tokensUsed: link.tokensUsed ?? 0,
        },
      });
    }

    // Add errors at session level
    for (const error of this.session.errors) {
      root.children.push({
        id: `error-${error.timestamp.getTime()}`,
        type: 'error',
        label: `Error: ${error.code}`,
        status: 'error',
        children: [],
        metrics: {},
      });
    }

    return { root };
  }

  /**
   * Get iteration status based on tool outcomes.
   */
  private getIterationStatus(iter: ParsedSession['iterations'][0]): 'success' | 'error' | 'pending' {
    const hasError = iter.tools.some(t => t.status === 'error');
    const hasBlocked = iter.decisions.some(d => d.outcome === 'blocked');

    if (hasError || hasBlocked) return 'error';
    if (!iter.endTime) return 'pending';
    return 'success';
  }

  /**
   * Get flat list of all nodes for searching/filtering.
   */
  getFlatNodes(): TreeNode[] {
    const nodes: TreeNode[] = [];
    const { root } = this.generate();

    const collect = (node: TreeNode) => {
      nodes.push(node);
      for (const child of node.children) {
        collect(child);
      }
    };

    collect(root);
    return nodes;
  }

  /**
   * Get maximum depth of tree.
   */
  getDepth(): number {
    const { root } = this.generate();

    const measureDepth = (node: TreeNode, depth: number): number => {
      if (node.children.length === 0) return depth;
      return Math.max(...node.children.map(c => measureDepth(c, depth + 1)));
    };

    return measureDepth(root, 1);
  }
}

/**
 * Factory function.
 */
export function createTreeView(session: ParsedSession): TreeView {
  return new TreeView(session);
}
