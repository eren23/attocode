/**
 * HTML Generator
 *
 * Generates interactive HTML reports for trace visualization.
 */

import type { ParsedSession } from '../types.js';
import { createSummaryView } from '../views/summary-view.js';
import { createTimelineView } from '../views/timeline-view.js';
import { createTokenFlowView } from '../views/token-flow-view.js';

/**
 * Generates HTML reports from trace data.
 */
export class HTMLGenerator {
  private session: ParsedSession;

  constructor(session: ParsedSession) {
    this.session = session;
  }

  /**
   * Generate complete HTML report.
   */
  generate(): string {
    const summaryView = createSummaryView(this.session);
    const timelineView = createTimelineView(this.session);
    const tokenFlowView = createTokenFlowView(this.session);

    const summaryData = summaryView.generate(true);
    const timelineData = timelineView.generate();
    const tokenFlowData = tokenFlowView.generate();

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Trace Analysis: ${this.escapeHtml(this.session.sessionId)}</title>
  <style>
    :root {
      --bg: #1a1a2e;
      --bg-card: #16213e;
      --text: #eee;
      --text-dim: #888;
      --accent: #0f3460;
      --success: #4ecca3;
      --warning: #ffc107;
      --error: #e94560;
      --blue: #00adb5;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 2rem;
    }

    .container { max-width: 1200px; margin: 0 auto; }

    h1, h2, h3 { color: var(--blue); margin-bottom: 1rem; }
    h1 { font-size: 1.5rem; border-bottom: 2px solid var(--accent); padding-bottom: 0.5rem; }
    h2 { font-size: 1.2rem; margin-top: 2rem; }

    .card {
      background: var(--bg-card);
      border-radius: 8px;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
    }

    .header-card {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 1rem;
    }

    .status {
      display: inline-block;
      padding: 0.25rem 0.75rem;
      border-radius: 4px;
      font-size: 0.875rem;
    }
    .status-completed { background: var(--success); color: #000; }
    .status-failed { background: var(--error); }
    .status-running { background: var(--warning); color: #000; }

    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
    }

    .metric-card {
      background: var(--accent);
      padding: 1rem;
      border-radius: 6px;
    }

    .metric-value {
      font-size: 1.5rem;
      font-weight: bold;
      color: var(--blue);
    }

    .metric-label {
      color: var(--text-dim);
      font-size: 0.875rem;
    }

    .timeline {
      border-left: 2px solid var(--accent);
      padding-left: 1.5rem;
      margin-left: 0.5rem;
    }

    .timeline-item {
      position: relative;
      padding-bottom: 1rem;
    }

    .timeline-item::before {
      content: '';
      position: absolute;
      left: -1.75rem;
      top: 0.25rem;
      width: 0.5rem;
      height: 0.5rem;
      border-radius: 50%;
      background: var(--blue);
    }

    .timeline-item.error::before { background: var(--error); }
    .timeline-item.high::before { background: var(--warning); }

    .timeline-time {
      color: var(--text-dim);
      font-size: 0.75rem;
    }

    .issue {
      padding: 0.75rem;
      border-radius: 4px;
      margin-bottom: 0.5rem;
    }
    .issue-critical { background: rgba(233, 69, 96, 0.2); border-left: 3px solid var(--error); }
    .issue-high { background: rgba(233, 69, 96, 0.15); border-left: 3px solid var(--error); }
    .issue-medium { background: rgba(255, 193, 7, 0.15); border-left: 3px solid var(--warning); }
    .issue-low { background: rgba(136, 136, 136, 0.15); border-left: 3px solid var(--text-dim); }

    .chart-container { margin: 1rem 0; }

    .bar-chart {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
    }

    .bar-row {
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .bar-label { width: 60px; color: var(--text-dim); font-size: 0.75rem; }
    .bar-container { flex: 1; height: 16px; background: var(--accent); border-radius: 3px; overflow: hidden; }
    .bar { height: 100%; transition: width 0.3s; }
    .bar-cached { background: var(--success); }
    .bar-fresh { background: var(--blue); }
    .bar-output { background: var(--text-dim); }
    .bar-value { width: 60px; text-align: right; font-size: 0.75rem; }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 1rem;
    }

    th, td {
      text-align: left;
      padding: 0.5rem;
      border-bottom: 1px solid var(--accent);
    }

    th { color: var(--blue); }

    .footer {
      margin-top: 3rem;
      padding-top: 1rem;
      border-top: 1px solid var(--accent);
      color: var(--text-dim);
      font-size: 0.75rem;
      text-align: center;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>🔍 Trace Analysis Report</h1>

    <!-- Header -->
    <div class="card header-card">
      <div>
        <div style="color: var(--text-dim); font-size: 0.875rem;">Session</div>
        <div style="font-size: 1.25rem; margin-bottom: 0.5rem;">${this.escapeHtml(this.session.sessionId)}</div>
        <div style="color: var(--text-dim);">Task: ${this.escapeHtml(this.session.task.slice(0, 100))}</div>
        <div style="color: var(--text-dim);">Model: ${this.escapeHtml(this.session.model)}</div>
      </div>
      <div style="text-align: right;">
        <span class="status status-${summaryData.header.statusColor === 'green' ? 'completed' : summaryData.header.statusColor === 'red' ? 'failed' : 'running'}">
          ${this.escapeHtml(summaryData.header.status)}
        </span>
        <div style="margin-top: 0.5rem; color: var(--text-dim);">Duration: ${summaryData.header.duration}</div>
        <div style="color: var(--text-dim);">Efficiency: ${summaryView.getEfficiencyScore()}/100</div>
      </div>
    </div>

    <!-- Metrics -->
    <h2>📊 Metrics</h2>
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-value">${this.session.metrics.iterations}</div>
        <div class="metric-label">Iterations</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${this.formatTokens(this.session.metrics.inputTokens + this.session.metrics.outputTokens)}</div>
        <div class="metric-label">Total Tokens</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${Math.round(this.session.metrics.avgCacheHitRate * 100)}%</div>
        <div class="metric-label">Cache Hit Rate</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">$${this.session.metrics.totalCost.toFixed(4)}</div>
        <div class="metric-label">Total Cost</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${this.session.metrics.toolCalls}</div>
        <div class="metric-label">Tool Calls</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${this.session.metrics.errors}</div>
        <div class="metric-label">Errors</div>
      </div>
    </div>

    <!-- Token Flow -->
    <h2>📈 Token Flow</h2>
    <div class="card">
      <div class="chart-container">
        <div class="bar-chart">
          ${tokenFlowData.perIteration.map(iter => `
            <div class="bar-row">
              <div class="bar-label">Iter ${iter.iteration}</div>
              <div class="bar-container">
                ${this.generateBarSegments(iter, tokenFlowData)}
              </div>
              <div class="bar-value">${this.formatTokens(iter.input + iter.output)}</div>
            </div>
          `).join('')}
        </div>
        <div style="margin-top: 1rem; font-size: 0.75rem; color: var(--text-dim);">
          <span style="color: var(--success);">■</span> Cached
          <span style="color: var(--blue); margin-left: 1rem;">■</span> Fresh Input
          <span style="color: var(--text-dim); margin-left: 1rem;">■</span> Output
        </div>
      </div>
    </div>

    ${summaryData.inefficiencies && summaryData.inefficiencies.length > 0 ? `
    <!-- Issues -->
    <h2>⚠️ Detected Issues</h2>
    <div class="card">
      ${summaryData.inefficiencies.map(issue => `
        <div class="issue issue-${issue.severity}">
          <strong>[${issue.severity.toUpperCase()}]</strong> ${this.escapeHtml(issue.description)}
          <div style="color: var(--text-dim); font-size: 0.875rem; margin-top: 0.25rem;">
            ${this.escapeHtml(issue.evidence)}
          </div>
        </div>
      `).join('')}
    </div>
    ` : ''}

    <!-- Timeline -->
    <h2>📅 Timeline</h2>
    <div class="card">
      <div class="timeline">
        ${timelineData.entries.slice(0, 20).map(entry => `
          <div class="timeline-item ${entry.importance}">
            <div class="timeline-time">${this.formatTime(entry.relativeMs)}</div>
            <div>${this.getEventEmoji(entry.type)} ${this.escapeHtml(entry.description)}</div>
            ${entry.durationMs ? `<div style="color: var(--text-dim); font-size: 0.75rem;">${entry.durationMs}ms</div>` : ''}
          </div>
        `).join('')}
        ${timelineData.entries.length > 20 ? `<div style="color: var(--text-dim);">... and ${timelineData.entries.length - 20} more events</div>` : ''}
      </div>
    </div>

    <!-- Tool Usage -->
    <h2>🔧 Tool Usage</h2>
    <div class="card">
      <table>
        <thead>
          <tr>
            <th>Tool</th>
            <th>Calls</th>
            <th>Avg Duration</th>
          </tr>
        </thead>
        <tbody>
          ${summaryData.toolStats.map(tool => `
            <tr>
              <td>${this.escapeHtml(tool.tool)}</td>
              <td>${tool.count}</td>
              <td>${tool.avgDuration}ms</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>

    <div class="footer">
      Generated by trace-viewer • ${new Date().toISOString()}
    </div>
  </div>
</body>
</html>`;
  }

  // Helper methods
  private escapeHtml(str: string): string {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  private formatTokens(n: number): string {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return n.toString();
  }

  private formatTime(ms: number): string {
    if (ms < 1000) return `+${ms}ms`;
    if (ms < 60000) return `+${(ms / 1000).toFixed(1)}s`;
    return `+${Math.round(ms / 60000)}m`;
  }

  private getEventEmoji(type: string): string {
    const emojis: Record<string, string> = {
      'session.start': '🚀',
      'session.end': '🏁',
      'iteration.start': '▶️',
      'iteration.end': '⏹️',
      'llm.call': '🤖',
      'tool.execution': '🔧',
      'decision': '⚖️',
      'error': '❌',
    };
    return emojis[type] || '•';
  }

  private generateBarSegments(iter: { input: number; output: number; cached: number }, data: { perIteration: Array<{ input: number; output: number }> }): string {
    const maxTokens = Math.max(...data.perIteration.map(i => i.input + i.output));
    if (maxTokens === 0) return '';

    const total = iter.input + iter.output;
    const cachedPercent = (iter.cached / maxTokens) * 100;
    const freshPercent = ((iter.input - iter.cached) / maxTokens) * 100;
    const outputPercent = (iter.output / maxTokens) * 100;
    const totalPercent = (total / maxTokens) * 100;

    return `
      <div class="bar bar-cached" style="width: ${cachedPercent}%; display: inline-block;"></div>
      <div class="bar bar-fresh" style="width: ${freshPercent}%; display: inline-block;"></div>
      <div class="bar bar-output" style="width: ${outputPercent}%; display: inline-block;"></div>
      <div style="width: ${100 - totalPercent}%; display: inline-block;"></div>
    `;
  }
}

/**
 * Factory function.
 */
export function createHTMLGenerator(session: ParsedSession): HTMLGenerator {
  return new HTMLGenerator(session);
}
