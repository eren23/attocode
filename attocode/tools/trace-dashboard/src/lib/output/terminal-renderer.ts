/**
 * Terminal Renderer
 *
 * Renders trace views to the terminal with colors and formatting.
 */

import chalk from 'chalk';
import type { SummaryViewData } from '../views/summary-view.js';
import type { TimelineViewData } from '../views/timeline-view.js';
import type { TreeViewData } from '../views/tree-view.js';
import type { TokenFlowViewData } from '../views/token-flow-view.js';
import type { SummarySection, Inefficiency, TreeNode } from '../types.js';

/**
 * Terminal renderer for trace views.
 */
export class TerminalRenderer {
  /**
   * Render summary view.
   */
  renderSummary(data: SummaryViewData): string {
    const lines: string[] = [];

    // Header box
    lines.push(this.box([
      `Trace Analysis: ${chalk.cyan(data.header.sessionId)}`,
      '',
      `Task: ${data.header.task.slice(0, 60)}${data.header.task.length > 60 ? '...' : ''}`,
      `Model: ${chalk.blue(data.header.model)} | Status: ${this.colorStatus(data.header.status, data.header.statusColor)} | Duration: ${data.header.duration}`,
    ]));

    lines.push('');

    // Sections
    for (const section of data.sections) {
      lines.push(this.renderSection(section));
      lines.push('');
    }

    // Inefficiencies
    if (data.inefficiencies && data.inefficiencies.length > 0) {
      lines.push(chalk.yellow('⚠️  Inefficiencies Detected:'));
      lines.push('');
      for (const ineff of data.inefficiencies.slice(0, 5)) {
        lines.push(this.renderInefficiency(ineff));
      }
      if (data.inefficiencies.length > 5) {
        lines.push(chalk.dim(`  ... and ${data.inefficiencies.length - 5} more`));
      }
      lines.push('');
    }

    // Tool stats
    if (data.toolStats.length > 0) {
      lines.push(chalk.cyan('🔧 Tool Usage:'));
      for (const stat of data.toolStats.slice(0, 5)) {
        lines.push(`  ${stat.tool}: ${stat.count}x (avg ${stat.avgDuration}ms)`);
      }
      lines.push('');
    }

    return lines.join('\n');
  }

  /**
   * Render timeline view.
   */
  renderTimeline(data: TimelineViewData): string {
    const lines: string[] = [];

    lines.push(chalk.cyan('📅 Timeline:'));
    lines.push('');

    for (const entry of data.entries) {
      const time = this.formatRelativeTime(entry.relativeMs);
      const icon = this.getEventIcon(entry.type);
      const color = entry.importance === 'high' ? chalk.yellow : entry.importance === 'low' ? chalk.dim : chalk;

      let line = `  ${chalk.gray(time)} ${icon} ${color(entry.description)}`;
      if (entry.durationMs) {
        line += chalk.dim(` (${entry.durationMs}ms)`);
      }
      lines.push(line);
    }

    return lines.join('\n');
  }

  /**
   * Render tree view.
   */
  renderTree(data: TreeViewData): string {
    const lines: string[] = [];
    lines.push(chalk.cyan('🌳 Session Tree:'));
    lines.push('');
    this.renderTreeNode(data.root, '', true, lines);
    return lines.join('\n');
  }

  /**
   * Recursively render tree node.
   */
  private renderTreeNode(node: TreeNode, prefix: string, isLast: boolean, lines: string[]): void {
    const connector = isLast ? '└── ' : '├── ';
    const icon = this.getNodeIcon(node.type);
    const status = this.getStatusIndicator(node.status);
    const metrics = this.formatNodeMetrics(node.metrics);

    let line = `${prefix}${connector}${icon} ${node.label}`;
    if (status) line += ` ${status}`;
    if (node.durationMs) line += chalk.dim(` (${node.durationMs}ms)`);
    if (metrics) line += chalk.gray(` [${metrics}]`);

    lines.push(line);

    const childPrefix = prefix + (isLast ? '    ' : '│   ');
    for (let i = 0; i < node.children.length; i++) {
      this.renderTreeNode(node.children[i], childPrefix, i === node.children.length - 1, lines);
    }
  }

  /**
   * Render token flow view.
   */
  renderTokenFlow(data: TokenFlowViewData): string {
    const lines: string[] = [];

    lines.push(chalk.cyan('📊 Token Flow:'));
    lines.push('');

    // ASCII chart
    lines.push(this.generateTokenChart(data));
    lines.push('');

    // Summary stats
    lines.push(chalk.cyan('Summary:'));
    lines.push(`  Trend: ${this.colorTrend(data.trend)}`);
    lines.push(`  Peak: Iteration ${data.peak.iteration} (${this.formatTokens(data.peak.tokens)})`);
    lines.push(`  Total Cost: $${data.costBreakdown.totalCost.toFixed(4)}`);
    lines.push(`  Savings: ${chalk.green(`$${data.costBreakdown.savings.toFixed(4)}`)}`);

    return lines.join('\n');
  }

  /**
   * Generate ASCII token chart.
   */
  private generateTokenChart(data: TokenFlowViewData): string {
    const maxWidth = 50;
    const maxTokens = Math.max(...data.perIteration.map(i => i.input + i.output));
    if (maxTokens === 0) return '  No token data';

    const lines: string[] = [];
    for (const iter of data.perIteration) {
      const total = iter.input + iter.output;
      const barLength = Math.round((total / maxTokens) * maxWidth);
      const cachedLength = Math.round((iter.cached / maxTokens) * maxWidth);
      const inputLength = Math.round((iter.input / maxTokens) * maxWidth);

      const bar =
        chalk.green('█'.repeat(Math.min(cachedLength, inputLength))) +
        chalk.blue('▓'.repeat(Math.max(0, inputLength - cachedLength))) +
        chalk.gray('░'.repeat(Math.max(0, barLength - inputLength)));

      const label = `Iter ${iter.iteration.toString().padStart(2)}`;
      const tokens = this.formatTokens(total).padStart(6);

      lines.push(`  ${label} │${bar} ${tokens}`);
    }

    lines.push('');
    lines.push(`  Legend: ${chalk.green('█')} Cached  ${chalk.blue('▓')} Fresh  ${chalk.gray('░')} Output`);

    return lines.join('\n');
  }

  // ==========================================================================
  // HELPER METHODS
  // ==========================================================================

  private box(lines: string[]): string {
    const width = Math.max(...lines.map(l => this.stripAnsi(l).length)) + 4;
    const top = '┌' + '─'.repeat(width - 2) + '┐';
    const bottom = '└' + '─'.repeat(width - 2) + '┘';

    const boxed = lines.map(l => {
      const padding = width - 4 - this.stripAnsi(l).length;
      return '│ ' + l + ' '.repeat(padding) + ' │';
    });

    return [top, ...boxed, bottom].join('\n');
  }

  private stripAnsi(str: string): string {
    return str.replace(/\x1B\[[0-9;]*[mK]/g, '');
  }

  private renderSection(section: SummarySection): string {
    const lines = [chalk.cyan(`📌 ${section.title}`)];
    for (const item of section.items) {
      const value = typeof item.value === 'number' ? item.value.toString() : item.value;
      const coloredValue = item.status
        ? item.status === 'good' ? chalk.green(value)
          : item.status === 'warn' ? chalk.yellow(value)
          : chalk.red(value)
        : value;
      lines.push(`  ${item.label}: ${coloredValue}`);
    }
    return lines.join('\n');
  }

  private renderInefficiency(ineff: Inefficiency): string {
    const severity = {
      critical: chalk.red.bold('[CRITICAL]'),
      high: chalk.red('[HIGH]'),
      medium: chalk.yellow('[WARN]'),
      low: chalk.dim('[INFO]'),
    }[ineff.severity];

    return `  ${severity} ${ineff.description}\n    ${chalk.dim(ineff.evidence)}`;
  }

  private colorStatus(status: string, color: 'green' | 'yellow' | 'red'): string {
    const colorFn = { green: chalk.green, yellow: chalk.yellow, red: chalk.red }[color];
    return colorFn(status);
  }

  private colorTrend(trend: string): string {
    switch (trend) {
      case 'increasing': return chalk.red('↑ Increasing');
      case 'decreasing': return chalk.green('↓ Decreasing');
      default: return chalk.blue('→ Stable');
    }
  }

  private formatRelativeTime(ms: number): string {
    if (ms < 1000) return `+${ms}ms`.padStart(8);
    if (ms < 60000) return `+${(ms / 1000).toFixed(1)}s`.padStart(8);
    return `+${Math.round(ms / 60000)}m`.padStart(8);
  }

  private formatTokens(n: number): string {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return n.toString();
  }

  private getEventIcon(type: string): string {
    const icons: Record<string, string> = {
      'session.start': '🚀',
      'session.end': '🏁',
      'iteration.start': '▶️',
      'iteration.end': '⏹️',
      'llm.call': '🤖',
      'llm.thinking': '💭',
      'tool.execution': '🔧',
      'decision': '⚖️',
      'subagent.spawn': '👥',
      'error': '❌',
    };
    return icons[type] || '•';
  }

  private getNodeIcon(type: string): string {
    const icons: Record<string, string> = {
      session: '📦',
      iteration: '🔄',
      llm: '🤖',
      tool: '🔧',
      decision: '⚖️',
      subagent: '👥',
      error: '❌',
    };
    return icons[type] || '•';
  }

  private getStatusIndicator(status?: string): string {
    if (!status) return '';
    switch (status) {
      case 'success': return chalk.green('✓');
      case 'error': return chalk.red('✗');
      case 'pending': return chalk.yellow('○');
      default: return '';
    }
  }

  private formatNodeMetrics(metrics?: Record<string, number>): string {
    if (!metrics || Object.keys(metrics).length === 0) return '';
    return Object.entries(metrics)
      .map(([k, v]) => `${k}: ${typeof v === 'number' && v > 1000 ? this.formatTokens(v) : v}`)
      .join(', ');
  }
}

/**
 * Factory function.
 */
export function createTerminalRenderer(): TerminalRenderer {
  return new TerminalRenderer();
}
