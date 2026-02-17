/**
 * Result Synthesizer Integration
 *
 * Structured merging of results from multiple agents.
 * Goes beyond simple consensus to intelligently combine outputs.
 *
 * Key features:
 * - Code merging: Intelligent merge of code changes from multiple agents
 * - Finding synthesis: Combine research findings, deduplicate insights
 * - Conflict detection: Identify contradictions between results
 * - Conflict resolution: Strategies for resolving disagreements
 * - Confidence weighting: Weight results by agent confidence and authority
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * A result from an agent that can be synthesized.
 */
export interface AgentOutput {
  /** Agent identifier */
  agentId: string;
  /** Output content */
  content: string;
  /** Type of output */
  type: OutputType;
  /** Confidence score (0-1) */
  confidence: number;
  /** Agent's authority/expertise level (0-1) */
  authority?: number;
  /** Files modified by this result */
  filesModified?: FileChange[];
  /** Key findings/insights */
  findings?: string[];
  /** Errors encountered */
  errors?: string[];
  /** Metadata */
  metadata?: Record<string, unknown>;
}

export type OutputType =
  | 'code' // Code implementation
  | 'research' // Research findings
  | 'analysis' // Analysis/interpretation
  | 'review' // Code review feedback
  | 'plan' // Implementation plan
  | 'documentation' // Documentation
  | 'mixed'; // Combination of types

/**
 * A file change from an agent.
 */
export interface FileChange {
  /** File path */
  path: string;
  /** Change type */
  type: 'create' | 'modify' | 'delete';
  /** Original content (for modify) */
  originalContent?: string;
  /** New content */
  newContent: string;
  /** Line-level changes */
  hunks?: Hunk[];
}

/**
 * A hunk of changes (like git diff).
 */
export interface Hunk {
  /** Start line in original */
  originalStart: number;
  /** Number of lines in original */
  originalLength: number;
  /** Start line in new */
  newStart: number;
  /** Number of lines in new */
  newLength: number;
  /** The actual lines */
  lines: string[];
}

/**
 * A detected conflict between results.
 */
export interface ResultConflict {
  /** Unique identifier */
  id: string;
  /** Type of conflict */
  type: ConflictType;
  /** Agents involved */
  agentIds: string[];
  /** Description of the conflict */
  description: string;
  /** Conflicting values/content */
  conflictingContent: string[];
  /** Severity */
  severity: 'low' | 'medium' | 'high';
  /** File path if applicable */
  filePath?: string;
  /** Line numbers if applicable */
  lines?: number[];
  /** Suggested resolution */
  suggestedResolution?: string;
  /** Resolution if applied */
  resolution?: ConflictResolution;
}

export type ConflictType =
  | 'code_overlap' // Same lines modified differently
  | 'logic_contradiction' // Contradicting logic/conclusions
  | 'approach_mismatch' // Different approaches to same problem
  | 'fact_disagreement' // Disagreement on facts
  | 'priority_conflict' // Different prioritization
  | 'naming_conflict'; // Different names for same thing

/**
 * Resolution applied to a conflict.
 */
export interface ConflictResolution {
  /** How it was resolved */
  strategy: ResolutionStrategy;
  /** Which agent's version was chosen (if applicable) */
  chosenAgentId?: string;
  /** Merged content (if applicable) */
  mergedContent?: string;
  /** Explanation of resolution */
  explanation: string;
  /** Timestamp */
  resolvedAt: Date;
}

export type ResolutionStrategy =
  | 'choose_highest_confidence'
  | 'choose_highest_authority'
  | 'merge_both'
  | 'human_decision'
  | 'llm_decision'
  | 'voting'
  | 'discard_all';

/**
 * Result of synthesis.
 */
export interface SynthesisResult {
  /** Synthesized output */
  output: string;
  /** Type of synthesized output */
  type: OutputType;
  /** Combined confidence */
  confidence: number;
  /** Merged file changes */
  fileChanges: FileChange[];
  /** Synthesized findings */
  findings: string[];
  /** Detected conflicts */
  conflicts: ResultConflict[];
  /** Statistics about the synthesis */
  stats: SynthesisStats;
  /** How the synthesis was performed */
  method: SynthesisMethod;
}

/**
 * Statistics about the synthesis process.
 */
export interface SynthesisStats {
  /** Number of inputs */
  inputCount: number;
  /** Total content length */
  totalContentLength: number;
  /** Synthesized content length */
  synthesizedLength: number;
  /** Deduplication rate (0-1) */
  deduplicationRate: number;
  /** Number of conflicts detected */
  conflictsDetected: number;
  /** Number of conflicts resolved */
  conflictsResolved: number;
  /** Agreement rate between agents (0-1) */
  agreementRate: number;
}

export type SynthesisMethod =
  | 'concatenate' // Simple concatenation
  | 'deduplicate' // Remove duplicates
  | 'merge_structured' // Structured merge (for code)
  | 'synthesize_llm' // LLM-based synthesis
  | 'majority_vote'; // Take majority opinion

/**
 * Configuration for the result synthesizer.
 */
export interface ResultSynthesizerConfig {
  /** Default synthesis method */
  defaultMethod?: SynthesisMethod;
  /** Conflict resolution strategy */
  conflictResolution?: ResolutionStrategy;
  /** Minimum similarity for deduplication (0-1) */
  deduplicationThreshold?: number;
  /** Enable LLM-assisted synthesis */
  useLLM?: boolean;
  /** LLM synthesis function */
  llmSynthesizer?: LLMSynthesizeFunction;
  /** Prefer higher confidence results */
  preferHigherConfidence?: boolean;
  /** Prefer higher authority results */
  preferHigherAuthority?: boolean;
}

/**
 * Function type for LLM-assisted synthesis.
 */
export type LLMSynthesizeFunction = (
  outputs: AgentOutput[],
  conflicts: ResultConflict[],
) => Promise<LLMSynthesisResult>;

/**
 * Result from LLM synthesis.
 */
export interface LLMSynthesisResult {
  /** Synthesized content */
  content: string;
  /** Key findings extracted */
  findings: string[];
  /** Conflict resolutions */
  resolutions: Array<{
    conflictId: string;
    resolution: string;
    explanation: string;
  }>;
  /** Overall confidence */
  confidence: number;
}

/**
 * Events emitted by the result synthesizer.
 */
export type ResultSynthesizerEvent =
  | { type: 'synthesis.started'; outputCount: number }
  | { type: 'synthesis.completed'; result: SynthesisResult }
  | { type: 'conflict.detected'; conflict: ResultConflict }
  | { type: 'conflict.resolved'; conflict: ResultConflict }
  | { type: 'deduplication.performed'; original: number; deduplicated: number };

export type ResultSynthesizerEventListener = (event: ResultSynthesizerEvent) => void;

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_CONFIG: Required<ResultSynthesizerConfig> = {
  defaultMethod: 'deduplicate',
  conflictResolution: 'choose_highest_confidence',
  deduplicationThreshold: 0.8,
  useLLM: false,
  llmSynthesizer: undefined as unknown as LLMSynthesizeFunction,
  preferHigherConfidence: true,
  preferHigherAuthority: true,
};

// =============================================================================
// RESULT SYNTHESIZER
// =============================================================================

/**
 * Synthesizes results from multiple agents into a coherent output.
 *
 * @example
 * ```typescript
 * const synthesizer = createResultSynthesizer();
 *
 * const result = await synthesizer.synthesize([
 *   {
 *     agentId: 'agent-a',
 *     content: 'Found auth logic in src/auth.ts',
 *     type: 'research',
 *     confidence: 0.9,
 *     findings: ['JWT tokens used', 'Session stored in Redis'],
 *   },
 *   {
 *     agentId: 'agent-b',
 *     content: 'Auth implemented in src/auth.ts using JWT',
 *     type: 'research',
 *     confidence: 0.85,
 *     findings: ['JWT tokens used', 'Password hashing with bcrypt'],
 *   },
 * ]);
 *
 * console.log(result.findings); // Deduplicated findings
 * console.log(result.conflicts); // Any disagreements
 * ```
 */
export class ResultSynthesizer {
  private config: Required<ResultSynthesizerConfig>;
  private listeners: ResultSynthesizerEventListener[] = [];
  private conflictCounter = 0;

  constructor(config: ResultSynthesizerConfig = {}) {
    this.config = {
      ...DEFAULT_CONFIG,
      ...config,
      llmSynthesizer: config.llmSynthesizer ?? DEFAULT_CONFIG.llmSynthesizer,
    };
  }

  // ===========================================================================
  // SYNTHESIS
  // ===========================================================================

  /**
   * Synthesize multiple agent outputs into a coherent result.
   */
  async synthesize(outputs: AgentOutput[]): Promise<SynthesisResult> {
    this.emit({ type: 'synthesis.started', outputCount: outputs.length });

    if (outputs.length === 0) {
      return this.createEmptyResult();
    }

    if (outputs.length === 1) {
      return this.createSingleResult(outputs[0]);
    }

    // Detect conflicts
    const conflicts = this.detectConflicts(outputs);
    for (const conflict of conflicts) {
      this.emit({ type: 'conflict.detected', conflict });
    }

    // Determine synthesis method based on output types
    const method = this.determineMethod(outputs);

    let result: SynthesisResult;

    switch (method) {
      case 'merge_structured':
        result = await this.mergeStructured(outputs, conflicts);
        break;
      case 'synthesize_llm':
        result = await this.synthesizeLLM(outputs, conflicts);
        break;
      case 'majority_vote':
        result = this.majorityVote(outputs, conflicts);
        break;
      case 'deduplicate':
        result = this.deduplicateMerge(outputs, conflicts);
        break;
      default:
        result = this.concatenateMerge(outputs, conflicts);
    }

    this.emit({ type: 'synthesis.completed', result });

    return result;
  }

  /**
   * Synthesize code changes from multiple agents.
   */
  async synthesizeCode(outputs: AgentOutput[]): Promise<SynthesisResult> {
    const codeOutputs = outputs.filter((o) => o.type === 'code' || o.filesModified);

    if (codeOutputs.length === 0) {
      return this.createEmptyResult();
    }

    // Collect all file changes
    const changesByFile = new Map<string, FileChange[]>();

    for (const output of codeOutputs) {
      for (const change of output.filesModified ?? []) {
        if (!changesByFile.has(change.path)) {
          changesByFile.set(change.path, []);
        }
        changesByFile.get(change.path)!.push(change);
      }
    }

    // Merge changes per file
    const mergedChanges: FileChange[] = [];
    const conflicts: ResultConflict[] = [];

    for (const [filePath, changes] of changesByFile) {
      if (changes.length === 1) {
        mergedChanges.push(changes[0]);
      } else {
        const mergeResult = this.mergeFileChanges(filePath, changes, codeOutputs);
        if (mergeResult.merged) {
          mergedChanges.push(mergeResult.merged);
        }
        conflicts.push(...mergeResult.conflicts);
      }
    }

    // Build output content
    const outputParts: string[] = [];
    for (const change of mergedChanges) {
      outputParts.push(`// File: ${change.path}`);
      outputParts.push(change.newContent);
      outputParts.push('');
    }

    const result: SynthesisResult = {
      output: outputParts.join('\n'),
      type: 'code',
      confidence: this.calculateCombinedConfidence(codeOutputs),
      fileChanges: mergedChanges,
      findings: [],
      conflicts,
      stats: this.calculateStats(codeOutputs, outputParts.join('\n'), conflicts),
      method: 'merge_structured',
    };

    return result;
  }

  /**
   * Synthesize research findings from multiple agents.
   */
  synthesizeFindings(outputs: AgentOutput[]): SynthesisResult {
    const allFindings: Array<{ finding: string; agentId: string; confidence: number }> = [];

    for (const output of outputs) {
      for (const finding of output.findings ?? []) {
        allFindings.push({
          finding,
          agentId: output.agentId,
          confidence: output.confidence,
        });
      }

      // Also extract findings from content
      const extracted = this.extractFindingsFromContent(output.content);
      for (const finding of extracted) {
        allFindings.push({
          finding,
          agentId: output.agentId,
          confidence: output.confidence * 0.8, // Lower confidence for extracted
        });
      }
    }

    // Deduplicate findings
    const deduplicated = this.deduplicateFindings(allFindings);

    this.emit({
      type: 'deduplication.performed',
      original: allFindings.length,
      deduplicated: deduplicated.length,
    });

    // Build output
    const outputParts = [
      '## Synthesized Findings',
      '',
      ...deduplicated.map(
        (f, i) => `${i + 1}. ${f.finding} (confidence: ${(f.confidence * 100).toFixed(0)}%)`,
      ),
    ];

    // Detect contradictions
    const conflicts = this.detectFindingContradictions(deduplicated);

    return {
      output: outputParts.join('\n'),
      type: 'research',
      confidence: this.calculateCombinedConfidence(outputs),
      fileChanges: [],
      findings: deduplicated.map((f) => f.finding),
      conflicts,
      stats: this.calculateStats(outputs, outputParts.join('\n'), conflicts),
      method: 'deduplicate',
    };
  }

  // ===========================================================================
  // CONFLICT DETECTION
  // ===========================================================================

  /**
   * Detect conflicts between agent outputs.
   */
  detectConflicts(outputs: AgentOutput[]): ResultConflict[] {
    const conflicts: ResultConflict[] = [];

    // Check for code overlaps
    conflicts.push(...this.detectCodeOverlaps(outputs));

    // Check for logic contradictions
    conflicts.push(...this.detectLogicContradictions(outputs));

    // Check for approach mismatches
    conflicts.push(...this.detectApproachMismatches(outputs));

    return conflicts;
  }

  /**
   * Detect overlapping code changes.
   */
  private detectCodeOverlaps(outputs: AgentOutput[]): ResultConflict[] {
    const conflicts: ResultConflict[] = [];
    const changesByFile = new Map<string, Array<{ change: FileChange; agentId: string }>>();

    // Collect changes by file
    for (const output of outputs) {
      for (const change of output.filesModified ?? []) {
        if (!changesByFile.has(change.path)) {
          changesByFile.set(change.path, []);
        }
        changesByFile.get(change.path)!.push({ change, agentId: output.agentId });
      }
    }

    // Check each file for overlaps
    for (const [filePath, changes] of changesByFile) {
      if (changes.length <= 1) continue;

      // Compare each pair
      for (let i = 0; i < changes.length; i++) {
        for (let j = i + 1; j < changes.length; j++) {
          const overlap = this.checkCodeOverlap(changes[i].change, changes[j].change);
          if (overlap) {
            conflicts.push({
              id: `conflict-${++this.conflictCounter}`,
              type: 'code_overlap',
              agentIds: [changes[i].agentId, changes[j].agentId],
              description: `Overlapping changes to ${filePath}`,
              conflictingContent: [changes[i].change.newContent, changes[j].change.newContent],
              severity: 'high',
              filePath,
              lines: overlap.lines,
              suggestedResolution: 'Review both changes and merge manually or choose one',
            });
          }
        }
      }
    }

    return conflicts;
  }

  /**
   * Check if two file changes overlap.
   */
  private checkCodeOverlap(a: FileChange, b: FileChange): { lines: number[] } | null {
    // Simple line-based overlap detection
    const aLines = new Set(a.newContent.split('\n').map((_, i) => i));
    const bLines = new Set(b.newContent.split('\n').map((_, i) => i));

    // If both modify similar regions, there's an overlap
    if (a.type === 'modify' && b.type === 'modify') {
      // Check for significantly different content
      const similarity = this.calculateSimilarity(a.newContent, b.newContent);
      if (similarity < 0.9) {
        return { lines: Array.from(aLines).filter((l) => bLines.has(l)) };
      }
    }

    return null;
  }

  /**
   * Detect logic contradictions in findings.
   */
  private detectLogicContradictions(outputs: AgentOutput[]): ResultConflict[] {
    const conflicts: ResultConflict[] = [];

    // Check for contradicting findings
    for (let i = 0; i < outputs.length; i++) {
      for (let j = i + 1; j < outputs.length; j++) {
        const contradictions = this.findContradictions(outputs[i].content, outputs[j].content);

        for (const contradiction of contradictions) {
          conflicts.push({
            id: `conflict-${++this.conflictCounter}`,
            type: 'logic_contradiction',
            agentIds: [outputs[i].agentId, outputs[j].agentId],
            description: contradiction.description,
            conflictingContent: [contradiction.contentA, contradiction.contentB],
            severity: 'medium',
            suggestedResolution: 'Verify which conclusion is correct',
          });
        }
      }
    }

    return conflicts;
  }

  /**
   * Find contradicting statements between two texts.
   */
  private findContradictions(
    textA: string,
    textB: string,
  ): Array<{ description: string; contentA: string; contentB: string }> {
    const contradictions: Array<{ description: string; contentA: string; contentB: string }> = [];

    // Simple heuristic: look for opposite assertions
    const negationPairs = [
      ['is', 'is not'],
      ['does', 'does not'],
      ['can', 'cannot'],
      ['should', 'should not'],
      ['will', 'will not'],
      ['works', 'does not work'],
      ['exists', 'does not exist'],
      ['found', 'not found'],
    ];

    const sentencesA = textA.split(/[.!?]+/).map((s) => s.trim().toLowerCase());
    const sentencesB = textB.split(/[.!?]+/).map((s) => s.trim().toLowerCase());

    for (const sentA of sentencesA) {
      for (const sentB of sentencesB) {
        for (const [pos, neg] of negationPairs) {
          if (
            (sentA.includes(pos) && sentB.includes(neg)) ||
            (sentA.includes(neg) && sentB.includes(pos))
          ) {
            // Check if they're about the same thing
            const similarity = this.calculateSimilarity(
              sentA.replace(pos, '').replace(neg, ''),
              sentB.replace(pos, '').replace(neg, ''),
            );

            if (similarity > 0.5) {
              contradictions.push({
                description: `Contradiction about: "${sentA.slice(0, 50)}..."`,
                contentA: sentA,
                contentB: sentB,
              });
            }
          }
        }
      }
    }

    return contradictions;
  }

  /**
   * Detect different approaches to the same problem.
   */
  private detectApproachMismatches(outputs: AgentOutput[]): ResultConflict[] {
    const conflicts: ResultConflict[] = [];

    // Check for significantly different code structures
    const codeOutputs = outputs.filter((o) => o.type === 'code');

    if (codeOutputs.length <= 1) return conflicts;

    for (let i = 0; i < codeOutputs.length; i++) {
      for (let j = i + 1; j < codeOutputs.length; j++) {
        const similarity = this.calculateSimilarity(codeOutputs[i].content, codeOutputs[j].content);

        // If outputs are similar in length but very different in content
        const lengthRatio =
          Math.min(codeOutputs[i].content.length, codeOutputs[j].content.length) /
          Math.max(codeOutputs[i].content.length, codeOutputs[j].content.length);

        if (lengthRatio > 0.5 && similarity < 0.3) {
          conflicts.push({
            id: `conflict-${++this.conflictCounter}`,
            type: 'approach_mismatch',
            agentIds: [codeOutputs[i].agentId, codeOutputs[j].agentId],
            description: 'Different approaches to the same implementation',
            conflictingContent: [
              codeOutputs[i].content.slice(0, 200),
              codeOutputs[j].content.slice(0, 200),
            ],
            severity: 'medium',
            suggestedResolution: 'Review both approaches and select the best one',
          });
        }
      }
    }

    return conflicts;
  }

  // ===========================================================================
  // MERGE STRATEGIES
  // ===========================================================================

  /**
   * Merge with deduplication.
   */
  private deduplicateMerge(outputs: AgentOutput[], conflicts: ResultConflict[]): SynthesisResult {
    // Combine all content
    const allParts: Array<{ content: string; confidence: number }> = [];

    for (const output of outputs) {
      // Split content into paragraphs/sections
      const parts = output.content.split(/\n\n+/);
      for (const part of parts) {
        if (part.trim().length > 20) {
          allParts.push({ content: part.trim(), confidence: output.confidence });
        }
      }
    }

    // Deduplicate
    const deduplicated: Array<{ content: string; confidence: number }> = [];
    for (const part of allParts) {
      const isDuplicate = deduplicated.some(
        (d) =>
          this.calculateSimilarity(d.content, part.content) > this.config.deduplicationThreshold,
      );
      if (!isDuplicate) {
        deduplicated.push(part);
      }
    }

    // Sort by confidence
    deduplicated.sort((a, b) => b.confidence - a.confidence);

    const output = deduplicated.map((d) => d.content).join('\n\n');

    return {
      output,
      type: this.determineOutputType(outputs),
      confidence: this.calculateCombinedConfidence(outputs),
      fileChanges: this.mergeAllFileChanges(outputs),
      findings: this.extractAllFindings(outputs),
      conflicts,
      stats: this.calculateStats(outputs, output, conflicts),
      method: 'deduplicate',
    };
  }

  /**
   * Simple concatenation merge.
   */
  private concatenateMerge(outputs: AgentOutput[], conflicts: ResultConflict[]): SynthesisResult {
    const parts = outputs.map((o) => `## From ${o.agentId}\n\n${o.content}`);
    const output = parts.join('\n\n---\n\n');

    return {
      output,
      type: 'mixed',
      confidence: this.calculateCombinedConfidence(outputs),
      fileChanges: this.mergeAllFileChanges(outputs),
      findings: this.extractAllFindings(outputs),
      conflicts,
      stats: this.calculateStats(outputs, output, conflicts),
      method: 'concatenate',
    };
  }

  /**
   * Structured merge for code.
   */
  private async mergeStructured(
    outputs: AgentOutput[],
    conflicts: ResultConflict[],
  ): Promise<SynthesisResult> {
    // Resolve conflicts first
    for (const conflict of conflicts) {
      if (!conflict.resolution) {
        conflict.resolution = this.resolveConflict(conflict, outputs);
        this.emit({ type: 'conflict.resolved', conflict });
      }
    }

    // Merge file changes
    const mergedChanges = this.mergeAllFileChanges(outputs);

    // Build output
    const outputParts: string[] = [];
    for (const change of mergedChanges) {
      outputParts.push(`// File: ${change.path}`);
      outputParts.push(change.newContent);
    }

    const output = outputParts.join('\n\n');

    return {
      output,
      type: 'code',
      confidence: this.calculateCombinedConfidence(outputs),
      fileChanges: mergedChanges,
      findings: [],
      conflicts,
      stats: this.calculateStats(outputs, output, conflicts),
      method: 'merge_structured',
    };
  }

  /**
   * LLM-assisted synthesis.
   */
  private async synthesizeLLM(
    outputs: AgentOutput[],
    conflicts: ResultConflict[],
  ): Promise<SynthesisResult> {
    if (!this.config.llmSynthesizer) {
      return this.deduplicateMerge(outputs, conflicts);
    }

    try {
      const llmResult = await this.config.llmSynthesizer(outputs, conflicts);

      // Apply LLM conflict resolutions
      for (const resolution of llmResult.resolutions) {
        const conflict = conflicts.find((c) => c.id === resolution.conflictId);
        if (conflict && !conflict.resolution) {
          conflict.resolution = {
            strategy: 'llm_decision',
            mergedContent: resolution.resolution,
            explanation: resolution.explanation,
            resolvedAt: new Date(),
          };
          this.emit({ type: 'conflict.resolved', conflict });
        }
      }

      return {
        output: llmResult.content,
        type: this.determineOutputType(outputs),
        confidence: llmResult.confidence,
        fileChanges: this.mergeAllFileChanges(outputs),
        findings: llmResult.findings,
        conflicts,
        stats: this.calculateStats(outputs, llmResult.content, conflicts),
        method: 'synthesize_llm',
      };
    } catch {
      // Fall back to deduplication
      return this.deduplicateMerge(outputs, conflicts);
    }
  }

  /**
   * Majority vote synthesis.
   */
  private majorityVote(outputs: AgentOutput[], conflicts: ResultConflict[]): SynthesisResult {
    // Group similar outputs
    const groups: Array<{ outputs: AgentOutput[]; representative: AgentOutput }> = [];

    for (const output of outputs) {
      let addedToGroup = false;

      for (const group of groups) {
        if (this.calculateSimilarity(output.content, group.representative.content) > 0.7) {
          group.outputs.push(output);
          // Update representative if this one has higher confidence
          if (output.confidence > group.representative.confidence) {
            group.representative = output;
          }
          addedToGroup = true;
          break;
        }
      }

      if (!addedToGroup) {
        groups.push({ outputs: [output], representative: output });
      }
    }

    // Choose the largest group
    groups.sort((a, b) => b.outputs.length - a.outputs.length);
    const winner = groups[0].representative;

    return {
      output: winner.content,
      type: winner.type,
      confidence: winner.confidence * (groups[0].outputs.length / outputs.length),
      fileChanges: winner.filesModified ?? [],
      findings: winner.findings ?? [],
      conflicts,
      stats: this.calculateStats(outputs, winner.content, conflicts),
      method: 'majority_vote',
    };
  }

  // ===========================================================================
  // CONFLICT RESOLUTION
  // ===========================================================================

  /**
   * Resolve a conflict using the configured strategy.
   */
  resolveConflict(conflict: ResultConflict, outputs: AgentOutput[]): ConflictResolution {
    switch (this.config.conflictResolution) {
      case 'choose_highest_confidence':
        return this.resolveByConfidence(conflict, outputs);
      case 'choose_highest_authority':
        return this.resolveByAuthority(conflict, outputs);
      case 'merge_both':
        return this.resolveMergeBoth(conflict);
      case 'voting':
        return this.resolveByVoting(conflict, outputs);
      default:
        return {
          strategy: 'discard_all',
          explanation: 'No resolution strategy available',
          resolvedAt: new Date(),
        };
    }
  }

  private resolveByConfidence(
    conflict: ResultConflict,
    outputs: AgentOutput[],
  ): ConflictResolution {
    const relevant = outputs.filter((o) => conflict.agentIds.includes(o.agentId));
    const winner = relevant.reduce((best, curr) =>
      curr.confidence > best.confidence ? curr : best,
    );

    return {
      strategy: 'choose_highest_confidence',
      chosenAgentId: winner.agentId,
      explanation: `Chose ${winner.agentId} with confidence ${winner.confidence}`,
      resolvedAt: new Date(),
    };
  }

  private resolveByAuthority(conflict: ResultConflict, outputs: AgentOutput[]): ConflictResolution {
    const relevant = outputs.filter((o) => conflict.agentIds.includes(o.agentId));
    const winner = relevant.reduce((best, curr) =>
      (curr.authority ?? 0) > (best.authority ?? 0) ? curr : best,
    );

    return {
      strategy: 'choose_highest_authority',
      chosenAgentId: winner.agentId,
      explanation: `Chose ${winner.agentId} with authority ${winner.authority}`,
      resolvedAt: new Date(),
    };
  }

  private resolveMergeBoth(conflict: ResultConflict): ConflictResolution {
    const merged = conflict.conflictingContent.join('\n\n// --- Alternative ---\n\n');

    return {
      strategy: 'merge_both',
      mergedContent: merged,
      explanation: 'Merged both versions',
      resolvedAt: new Date(),
    };
  }

  private resolveByVoting(conflict: ResultConflict, _outputs: AgentOutput[]): ConflictResolution {
    // Count "votes" for each version
    const votes = new Map<string, number>();
    for (const agentId of conflict.agentIds) {
      votes.set(agentId, (votes.get(agentId) ?? 0) + 1);
    }

    const winner = Array.from(votes.entries()).reduce((best, curr) =>
      curr[1] > best[1] ? curr : best,
    )[0];

    return {
      strategy: 'voting',
      chosenAgentId: winner,
      explanation: `${winner} won by vote`,
      resolvedAt: new Date(),
    };
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  /**
   * Calculate content similarity (Jaccard index).
   */
  private calculateSimilarity(a: string, b: string): number {
    const wordsA = new Set(a.toLowerCase().split(/\s+/));
    const wordsB = new Set(b.toLowerCase().split(/\s+/));

    const intersection = new Set([...wordsA].filter((x) => wordsB.has(x)));
    const union = new Set([...wordsA, ...wordsB]);

    return intersection.size / union.size;
  }

  /**
   * Calculate combined confidence from multiple outputs.
   */
  private calculateCombinedConfidence(outputs: AgentOutput[]): number {
    if (outputs.length === 0) return 0;

    // Weight by confidence and agreement
    const totalWeight = outputs.reduce((sum, o) => sum + o.confidence, 0);
    const avgConfidence = totalWeight / outputs.length;

    // Boost if agents agree
    const agreementBoost = this.calculateAgreement(outputs) * 0.1;

    return Math.min(1, avgConfidence + agreementBoost);
  }

  /**
   * Calculate agreement rate between outputs.
   */
  private calculateAgreement(outputs: AgentOutput[]): number {
    if (outputs.length <= 1) return 1;

    let totalSimilarity = 0;
    let pairs = 0;

    for (let i = 0; i < outputs.length; i++) {
      for (let j = i + 1; j < outputs.length; j++) {
        totalSimilarity += this.calculateSimilarity(outputs[i].content, outputs[j].content);
        pairs++;
      }
    }

    return pairs > 0 ? totalSimilarity / pairs : 0;
  }

  /**
   * Determine synthesis method based on output types.
   */
  private determineMethod(outputs: AgentOutput[]): SynthesisMethod {
    const types = outputs.map((o) => o.type);

    if (types.every((t) => t === 'code')) {
      return 'merge_structured';
    }

    if (types.every((t) => t === 'research')) {
      return 'deduplicate';
    }

    if (this.config.useLLM && this.config.llmSynthesizer !== undefined) {
      return 'synthesize_llm';
    }

    return this.config.defaultMethod;
  }

  /**
   * Determine output type from multiple outputs.
   */
  private determineOutputType(outputs: AgentOutput[]): OutputType {
    const types = outputs.map((o) => o.type);
    const uniqueTypes = new Set(types);

    if (uniqueTypes.size === 1) {
      return types[0];
    }

    return 'mixed';
  }

  /**
   * Merge all file changes from outputs.
   */
  private mergeAllFileChanges(outputs: AgentOutput[]): FileChange[] {
    const byFile = new Map<string, FileChange[]>();

    for (const output of outputs) {
      for (const change of output.filesModified ?? []) {
        if (!byFile.has(change.path)) {
          byFile.set(change.path, []);
        }
        byFile.get(change.path)!.push(change);
      }
    }

    const merged: FileChange[] = [];
    for (const [_filePath, changes] of byFile) {
      if (changes.length === 1) {
        merged.push(changes[0]);
      } else {
        // Take the one with most content or merge
        const best = changes.reduce((a, b) => (a.newContent.length > b.newContent.length ? a : b));
        merged.push(best);
      }
    }

    return merged;
  }

  /**
   * Merge file changes for a single file.
   */
  private mergeFileChanges(
    filePath: string,
    changes: FileChange[],
    outputs: AgentOutput[],
  ): { merged: FileChange | null; conflicts: ResultConflict[] } {
    const conflicts: ResultConflict[] = [];

    // Simple strategy: take the change with highest confidence
    let bestChange = changes[0];
    let bestConfidence = 0;

    for (const change of changes) {
      const output = outputs.find((o) =>
        o.filesModified?.some((f) => f.path === filePath && f.newContent === change.newContent),
      );
      if (output && output.confidence > bestConfidence) {
        bestConfidence = output.confidence;
        bestChange = change;
      }
    }

    // Detect if there are significant differences
    for (let i = 0; i < changes.length; i++) {
      for (let j = i + 1; j < changes.length; j++) {
        const similarity = this.calculateSimilarity(changes[i].newContent, changes[j].newContent);
        if (similarity < 0.8) {
          conflicts.push({
            id: `conflict-${++this.conflictCounter}`,
            type: 'code_overlap',
            agentIds: outputs
              .filter((o) => o.filesModified?.some((f) => f.path === filePath))
              .map((o) => o.agentId),
            description: `Different versions of ${filePath}`,
            conflictingContent: [
              changes[i].newContent.slice(0, 200),
              changes[j].newContent.slice(0, 200),
            ],
            severity: 'high',
            filePath,
          });
        }
      }
    }

    return { merged: bestChange, conflicts };
  }

  /**
   * Extract all findings from outputs.
   */
  private extractAllFindings(outputs: AgentOutput[]): string[] {
    const all: string[] = [];

    for (const output of outputs) {
      all.push(...(output.findings ?? []));
    }

    // Deduplicate
    return [...new Set(all)];
  }

  /**
   * Extract findings from content text.
   */
  private extractFindingsFromContent(content: string): string[] {
    const findings: string[] = [];
    const lines = content.split('\n');

    for (const line of lines) {
      const trimmed = line.trim();
      // Look for bullet points or findings indicators
      if (
        trimmed.match(/^[-*•]\s+/) ||
        trimmed.match(/^\d+\.\s+/) ||
        trimmed.toLowerCase().includes('found:') ||
        trimmed.toLowerCase().includes('discovered:')
      ) {
        const finding = trimmed.replace(/^[-*•\d.]+\s+/, '');
        if (finding.length > 10) {
          findings.push(finding);
        }
      }
    }

    return findings;
  }

  /**
   * Deduplicate findings.
   */
  private deduplicateFindings(
    findings: Array<{ finding: string; agentId: string; confidence: number }>,
  ): Array<{ finding: string; confidence: number }> {
    const deduplicated: Array<{ finding: string; confidence: number }> = [];

    for (const f of findings) {
      const existing = deduplicated.find(
        (d) => this.calculateSimilarity(d.finding, f.finding) > this.config.deduplicationThreshold,
      );

      if (existing) {
        // Keep higher confidence
        if (f.confidence > existing.confidence) {
          existing.confidence = f.confidence;
        }
      } else {
        deduplicated.push({ finding: f.finding, confidence: f.confidence });
      }
    }

    return deduplicated;
  }

  /**
   * Detect contradictions between findings.
   */
  private detectFindingContradictions(
    findings: Array<{ finding: string; confidence: number }>,
  ): ResultConflict[] {
    const conflicts: ResultConflict[] = [];

    for (let i = 0; i < findings.length; i++) {
      for (let j = i + 1; j < findings.length; j++) {
        const contradictions = this.findContradictions(findings[i].finding, findings[j].finding);
        for (const c of contradictions) {
          conflicts.push({
            id: `conflict-${++this.conflictCounter}`,
            type: 'fact_disagreement',
            agentIds: [],
            description: c.description,
            conflictingContent: [c.contentA, c.contentB],
            severity: 'medium',
          });
        }
      }
    }

    return conflicts;
  }

  /**
   * Calculate synthesis statistics.
   */
  private calculateStats(
    outputs: AgentOutput[],
    synthesizedContent: string,
    conflicts: ResultConflict[],
  ): SynthesisStats {
    const totalContentLength = outputs.reduce((sum, o) => sum + o.content.length, 0);

    return {
      inputCount: outputs.length,
      totalContentLength,
      synthesizedLength: synthesizedContent.length,
      deduplicationRate:
        totalContentLength > 0 ? 1 - synthesizedContent.length / totalContentLength : 0,
      conflictsDetected: conflicts.length,
      conflictsResolved: conflicts.filter((c) => c.resolution).length,
      agreementRate: this.calculateAgreement(outputs),
    };
  }

  /**
   * Create empty result.
   */
  private createEmptyResult(): SynthesisResult {
    return {
      output: '',
      type: 'mixed',
      confidence: 0,
      fileChanges: [],
      findings: [],
      conflicts: [],
      stats: {
        inputCount: 0,
        totalContentLength: 0,
        synthesizedLength: 0,
        deduplicationRate: 0,
        conflictsDetected: 0,
        conflictsResolved: 0,
        agreementRate: 1,
      },
      method: 'concatenate',
    };
  }

  /**
   * Create result from single output.
   */
  private createSingleResult(output: AgentOutput): SynthesisResult {
    return {
      output: output.content,
      type: output.type,
      confidence: output.confidence,
      fileChanges: output.filesModified ?? [],
      findings: output.findings ?? [],
      conflicts: [],
      stats: {
        inputCount: 1,
        totalContentLength: output.content.length,
        synthesizedLength: output.content.length,
        deduplicationRate: 0,
        conflictsDetected: 0,
        conflictsResolved: 0,
        agreementRate: 1,
      },
      method: 'concatenate',
    };
  }

  /**
   * Subscribe to events.
   */
  on(listener: ResultSynthesizerEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  private emit(event: ResultSynthesizerEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a result synthesizer.
 *
 * @example
 * ```typescript
 * const synthesizer = createResultSynthesizer({
 *   conflictResolution: 'choose_highest_confidence',
 *   deduplicationThreshold: 0.85,
 * });
 *
 * const result = await synthesizer.synthesize(agentOutputs);
 * ```
 */
export function createResultSynthesizer(config: ResultSynthesizerConfig = {}): ResultSynthesizer {
  return new ResultSynthesizer(config);
}

/**
 * Create an LLM prompt for synthesis.
 */
export function createSynthesisPrompt(outputs: AgentOutput[], conflicts: ResultConflict[]): string {
  const parts = [
    'You are synthesizing results from multiple AI agents. Combine their findings into a coherent, unified response.',
    '',
    '## Agent Outputs',
    '',
  ];

  for (const output of outputs) {
    parts.push(`### Agent: ${output.agentId} (confidence: ${output.confidence})`);
    parts.push('');
    parts.push(output.content);
    parts.push('');
  }

  if (conflicts.length > 0) {
    parts.push('## Detected Conflicts');
    parts.push('');
    for (const conflict of conflicts) {
      parts.push(`- ${conflict.type}: ${conflict.description}`);
    }
    parts.push('');
    parts.push('Please resolve these conflicts in your synthesis.');
  }

  parts.push('');
  parts.push('## Instructions');
  parts.push('1. Combine the key insights from all agents');
  parts.push('2. Remove duplicate information');
  parts.push('3. Resolve any contradictions');
  parts.push('4. Provide a unified, coherent response');
  parts.push('');
  parts.push(
    'Respond with JSON: { "content": "...", "findings": [...], "resolutions": [...], "confidence": 0.X }',
  );

  return parts.join('\n');
}
