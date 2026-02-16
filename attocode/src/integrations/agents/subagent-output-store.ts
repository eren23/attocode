/**
 * Subagent Output Store
 *
 * Saves subagent outputs to the filesystem so the parent coordinator
 * doesn't need to carry full outputs in memory. This addresses the
 * "Game of Telephone" problem from Anthropic's multi-agent research.
 *
 * Subagent writes full output to .agent/subagent-outputs/{id}.json + .md
 * Parent receives summary + file reference (not full output)
 * ResultSynthesizer reads from store for full fidelity
 */

import { writeFileSync, readFileSync, mkdirSync, unlinkSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import type { StructuredClosureReport } from './agent-registry.js';

// =============================================================================
// TYPES
// =============================================================================

export interface SubagentOutput {
  /** Unique output ID */
  id: string;
  /** Agent that produced this */
  agentId: string;
  /** Agent name/type */
  agentName: string;
  /** Task description */
  task: string;
  /** Full output content (not truncated) */
  fullOutput: string;
  /** Structured closure report */
  structured?: StructuredClosureReport;
  /** Files modified by this agent */
  filesModified: string[];
  /** Files created by this agent */
  filesCreated: string[];
  /** Timestamp */
  timestamp: Date;
  /** Token usage */
  tokensUsed: number;
  /** Duration in ms */
  durationMs: number;
  /** Quality score (if quality-gated) */
  qualityScore?: number;
  /** Parent task context */
  parentContext?: string;
}

export interface SubagentOutputStoreConfig {
  /** Storage directory (default: '.agent/subagent-outputs') */
  outputDir: string;
  /** Max outputs to keep (default: 100) */
  maxOutputs: number;
  /** Whether to write to filesystem (default: true) */
  persistToFile: boolean;
}

// =============================================================================
// STORE
// =============================================================================

export class SubagentOutputStore {
  private config: SubagentOutputStoreConfig;
  private memoryStore: Map<string, SubagentOutput> = new Map();

  constructor(config?: Partial<SubagentOutputStoreConfig>) {
    this.config = {
      outputDir: config?.outputDir ?? '.agent/subagent-outputs',
      maxOutputs: config?.maxOutputs ?? 100,
      persistToFile: config?.persistToFile ?? true,
    };

    if (this.config.persistToFile) {
      try {
        mkdirSync(this.config.outputDir, { recursive: true });
      } catch {
        // Directory might already exist or be unwritable
      }
    }
  }

  /**
   * Save a subagent's output. Returns the output ID.
   */
  save(output: SubagentOutput): string {
    const id = output.id || `output-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const outputWithId = { ...output, id };

    // Store in memory
    this.memoryStore.set(id, outputWithId);

    // Persist to filesystem
    if (this.config.persistToFile) {
      this.writeToFile(id, outputWithId);
    }

    // Cleanup old outputs if over limit
    if (this.memoryStore.size > this.config.maxOutputs) {
      this.cleanup();
    }

    return id;
  }

  /**
   * Load a subagent's output by ID.
   */
  load(outputId: string): SubagentOutput | null {
    // Check memory first
    const memResult = this.memoryStore.get(outputId);
    if (memResult) return memResult;

    // Try filesystem
    if (this.config.persistToFile) {
      return this.readFromFile(outputId);
    }

    return null;
  }

  /**
   * List all outputs, optionally filtered.
   */
  list(filter?: {
    agentName?: string;
    since?: Date;
    limit?: number;
  }): SubagentOutput[] {
    let outputs = [...this.memoryStore.values()];

    if (filter?.agentName) {
      outputs = outputs.filter(o => o.agentName === filter.agentName);
    }
    if (filter?.since) {
      outputs = outputs.filter(o => o.timestamp >= filter.since!);
    }

    // Sort by timestamp descending
    outputs.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

    if (filter?.limit) {
      outputs = outputs.slice(0, filter.limit);
    }

    return outputs;
  }

  /**
   * Get a summary of an output (for passing to coordinator).
   */
  getSummary(outputId: string): string {
    const output = this.load(outputId);
    if (!output) return `[Output ${outputId} not found]`;

    const lines: string[] = [
      `Agent: ${output.agentName}`,
      `Task: ${output.task.slice(0, 200)}`,
      `Duration: ${(output.durationMs / 1000).toFixed(1)}s`,
      `Tokens: ${output.tokensUsed}`,
    ];

    if (output.structured) {
      if (output.structured.findings && output.structured.findings.length > 0) {
        lines.push(`Findings: ${output.structured.findings.length}`);
      }
      if (output.structured.actionsTaken && output.structured.actionsTaken.length > 0) {
        lines.push(`Actions: ${output.structured.actionsTaken.join(', ')}`);
      }
      if (output.structured.remainingWork && output.structured.remainingWork.length > 0) {
        lines.push(`Remaining: ${output.structured.remainingWork.join(', ')}`);
      }
    }

    // Include first 500 chars of output
    if (output.fullOutput) {
      lines.push('');
      lines.push('Output preview:');
      lines.push(output.fullOutput.slice(0, 500));
      if (output.fullOutput.length > 500) {
        lines.push('...(truncated, read full output from file)');
      }
    }

    return lines.join('\n');
  }

  /**
   * Get a file reference that the coordinator can include in context.
   * The LLM can use read_file to access the full output if needed.
   */
  getReference(outputId: string): string {
    if (this.config.persistToFile) {
      return join(this.config.outputDir, `${outputId}.md`);
    }
    return `[memory:${outputId}]`;
  }

  /**
   * Cleanup old outputs, keeping only the most recent up to maxOutputs.
   */
  cleanup(maxAge?: number): number {
    const now = Date.now();
    let cleaned = 0;

    // Sort by timestamp
    const entries = [...this.memoryStore.entries()]
      .sort((a, b) => new Date(b[1].timestamp).getTime() - new Date(a[1].timestamp).getTime());

    for (let i = this.config.maxOutputs; i < entries.length; i++) {
      const [id, output] = entries[i];

      // Also respect maxAge if provided
      if (maxAge && now - new Date(output.timestamp).getTime() < maxAge) {
        continue;
      }

      this.memoryStore.delete(id);
      this.deleteFile(id);
      cleaned++;
    }

    return cleaned;
  }

  // ===========================================================================
  // FILE I/O
  // ===========================================================================

  private writeToFile(id: string, output: SubagentOutput): void {
    try {
      const jsonPath = join(this.config.outputDir, `${id}.json`);
      const mdPath = join(this.config.outputDir, `${id}.md`);

      // Ensure directory exists
      mkdirSync(dirname(jsonPath), { recursive: true });

      // Write JSON (full structured output)
      writeFileSync(jsonPath, JSON.stringify(output, null, 2), 'utf-8');

      // Write Markdown (human-readable summary + full text)
      const mdContent = this.formatAsMarkdown(output);
      writeFileSync(mdPath, mdContent, 'utf-8');
    } catch {
      // File write failure is not critical
    }
  }

  private readFromFile(id: string): SubagentOutput | null {
    try {
      const jsonPath = join(this.config.outputDir, `${id}.json`);
      const content = readFileSync(jsonPath, 'utf-8');
      const parsed = JSON.parse(content) as SubagentOutput;
      parsed.timestamp = new Date(parsed.timestamp);
      return parsed;
    } catch {
      return null;
    }
  }

  private deleteFile(id: string): void {
    try {
      const jsonPath = join(this.config.outputDir, `${id}.json`);
      const mdPath = join(this.config.outputDir, `${id}.md`);
      if (existsSync(jsonPath)) unlinkSync(jsonPath);
      if (existsSync(mdPath)) unlinkSync(mdPath);
    } catch {
      // Deletion failure is not critical
    }
  }

  private formatAsMarkdown(output: SubagentOutput): string {
    const lines: string[] = [
      `# Subagent Output: ${output.agentName}`,
      '',
      `**Task:** ${output.task}`,
      `**Agent ID:** ${output.agentId}`,
      `**Timestamp:** ${new Date(output.timestamp).toISOString()}`,
      `**Duration:** ${(output.durationMs / 1000).toFixed(1)}s`,
      `**Tokens Used:** ${output.tokensUsed}`,
    ];

    if (output.qualityScore !== undefined) {
      lines.push(`**Quality Score:** ${output.qualityScore}`);
    }

    if (output.filesModified.length > 0) {
      lines.push('', '## Files Modified');
      for (const f of output.filesModified) {
        lines.push(`- ${f}`);
      }
    }

    if (output.filesCreated.length > 0) {
      lines.push('', '## Files Created');
      for (const f of output.filesCreated) {
        lines.push(`- ${f}`);
      }
    }

    if (output.structured) {
      lines.push('', '## Structured Report');
      if (output.structured.findings && output.structured.findings.length > 0) {
        lines.push('', '### Findings');
        for (const f of output.structured.findings) {
          lines.push(`- ${f}`);
        }
      }
      if (output.structured.actionsTaken && output.structured.actionsTaken.length > 0) {
        lines.push('', '### Actions Taken');
        for (const a of output.structured.actionsTaken) {
          lines.push(`- ${a}`);
        }
      }
      if (output.structured.failures && output.structured.failures.length > 0) {
        lines.push('', '### Failures');
        for (const f of output.structured.failures) {
          lines.push(`- ${f}`);
        }
      }
      if (output.structured.remainingWork && output.structured.remainingWork.length > 0) {
        lines.push('', '### Remaining Work');
        for (const r of output.structured.remainingWork) {
          lines.push(`- ${r}`);
        }
      }
    }

    lines.push('', '## Full Output', '', output.fullOutput);

    return lines.join('\n');
  }
}

/**
 * Create a subagent output store.
 */
export function createSubagentOutputStore(
  config?: Partial<SubagentOutputStoreConfig>,
): SubagentOutputStore {
  return new SubagentOutputStore(config);
}
