/**
 * Smart Task Decomposer Integration
 *
 * Uses LLM-assisted analysis for intelligent task decomposition.
 * Replaces keyword-based decomposition with semantic understanding.
 *
 * Key features:
 * - Semantic task analysis (understands intent, not just keywords)
 * - Implicit dependency detection ("implement auth" needs "design schema")
 * - Codebase-aware decomposition (considers existing structure)
 * - Resource contention detection (identifies potential conflicts)
 * - Dynamic strategy selection based on task characteristics
 */

import type { RepoMap, CodeChunk } from './codebase-context.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * A decomposed subtask with rich metadata.
 */
export interface SmartSubtask {
  /** Unique identifier */
  id: string;
  /** Human-readable description */
  description: string;
  /** Current status */
  status: SubtaskStatus;
  /** IDs of tasks this depends on */
  dependencies: string[];
  /** Estimated complexity (1-10) */
  complexity: number;
  /** Estimated token budget needed */
  estimatedTokens?: number;
  /** Files likely to be involved */
  relevantFiles?: string[];
  /** Symbols/functions likely to be involved */
  relevantSymbols?: string[];
  /** Type of task */
  type: SubtaskType;
  /** Can be parallelized with other tasks */
  parallelizable: boolean;
  /** Resources this task will modify */
  modifies?: string[];
  /** Resources this task will read */
  reads?: string[];
  /** Suggested agent role */
  suggestedRole?: string;
  /** Additional notes */
  notes?: string;
}

export type SubtaskStatus =
  | 'pending'      // Not yet started
  | 'ready'        // Dependencies satisfied, can start
  | 'blocked'      // Waiting on dependencies
  | 'in_progress'  // Currently executing
  | 'completed'    // Successfully finished
  | 'failed'       // Failed
  | 'skipped';     // Skipped (e.g., deemed unnecessary)

/** Known built-in task types (for autocomplete + defaults) */
export type BuiltinSubtaskType =
  | 'research'     // Gather information
  | 'analysis'     // Analyze existing code/data
  | 'design'       // Design/plan implementation
  | 'implement'    // Write code
  | 'test'         // Write/run tests
  | 'refactor'     // Improve existing code
  | 'review'       // Review code/changes
  | 'document'     // Write documentation
  | 'integrate'    // Integrate components
  | 'deploy'       // Deploy/release
  | 'merge';       // Combine results

/** Any string is valid — custom types are first-class citizens. */
export type SubtaskType = BuiltinSubtaskType | (string & {});

/**
 * A dependency graph for subtasks.
 */
export interface DependencyGraph {
  /** Map of task ID to its dependencies */
  dependencies: Map<string, string[]>;
  /** Map of task ID to tasks that depend on it */
  dependents: Map<string, string[]>;
  /** Topological order of tasks */
  executionOrder: string[];
  /** Tasks that can be parallelized together */
  parallelGroups: string[][];
  /** Detected cycles (should be empty for valid graph) */
  cycles: string[][];
}

/**
 * Detected resource conflict.
 */
export interface ResourceConflict {
  /** Resource that has a conflict */
  resource: string;
  /** Tasks that conflict */
  taskIds: string[];
  /** Type of conflict */
  type: 'write-write' | 'read-write';
  /** Severity */
  severity: 'warning' | 'error';
  /** Suggested resolution */
  suggestion: string;
}

/**
 * Result of smart decomposition.
 */
export interface SmartDecompositionResult {
  /** Original task description */
  originalTask: string;
  /** Decomposed subtasks */
  subtasks: SmartSubtask[];
  /** Dependency graph */
  dependencyGraph: DependencyGraph;
  /** Detected resource conflicts */
  conflicts: ResourceConflict[];
  /** Strategy used */
  strategy: DecompositionStrategy;
  /** Overall estimated complexity */
  totalComplexity: number;
  /** Overall estimated tokens */
  totalEstimatedTokens: number;
  /** Decomposition metadata */
  metadata: {
    decomposedAt: Date;
    codebaseAware: boolean;
    llmAssisted: boolean;
  };
}

export type DecompositionStrategy =
  | 'sequential'    // Tasks must run in order
  | 'parallel'      // Tasks can run simultaneously
  | 'hierarchical'  // Tasks have subtasks
  | 'adaptive'      // Mix of strategies
  | 'pipeline';     // Data flows through stages

/**
 * Configuration for smart decomposer.
 */
export interface SmartDecomposerConfig {
  /** Maximum number of subtasks */
  maxSubtasks?: number;
  /** Minimum complexity to trigger decomposition */
  minComplexityToDecompose?: number;
  /** Enable LLM-assisted analysis */
  useLLM?: boolean;
  /** LLM provider function */
  llmProvider?: LLMDecomposeFunction;
  /** Enable codebase-aware decomposition */
  codebaseAware?: boolean;
  /** Default strategy */
  defaultStrategy?: DecompositionStrategy;
  /** Detect resource conflicts */
  detectConflicts?: boolean;
}

/**
 * Function type for LLM-assisted decomposition.
 */
export type LLMDecomposeFunction = (
  task: string,
  context: DecomposeContext
) => Promise<LLMDecomposeResult>;

/**
 * Context provided to the LLM for decomposition.
 */
export interface DecomposeContext {
  /** Codebase structure if available */
  repoMap?: RepoMap;
  /** Relevant code chunks */
  relevantCode?: CodeChunk[];
  /** Previous decompositions for learning */
  previousDecompositions?: SmartDecompositionResult[];
  /** Hints about desired decomposition */
  hints?: string[];
}

/**
 * Result from LLM decomposition.
 */
export interface LLMDecomposeResult {
  /** Suggested subtasks */
  subtasks: Array<{
    description: string;
    type: SubtaskType;
    complexity: number;
    dependencies: string[]; // References by description or index
    parallelizable: boolean;
    relevantFiles?: string[];
    suggestedRole?: string;
  }>;
  /** Suggested strategy */
  strategy: DecompositionStrategy;
  /** Reasoning for the decomposition */
  reasoning: string;
  /** Parse error details when decomposition fails (undefined on success) */
  parseError?: string;
}

/**
 * Events emitted by the smart decomposer.
 */
export type SmartDecomposerEvent =
  | { type: 'decomposition.started'; task: string }
  | { type: 'decomposition.completed'; result: SmartDecompositionResult }
  | { type: 'llm.called'; task: string }
  | { type: 'llm.fallback'; reason: string; task: string }
  | { type: 'conflict.detected'; conflict: ResourceConflict }
  | { type: 'cycle.detected'; cycle: string[] };

export type SmartDecomposerEventListener = (event: SmartDecomposerEvent) => void;

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_CONFIG: Required<SmartDecomposerConfig> = {
  maxSubtasks: 10,
  minComplexityToDecompose: 3,
  useLLM: false,
  llmProvider: undefined as unknown as LLMDecomposeFunction,
  codebaseAware: true,
  defaultStrategy: 'adaptive',
  detectConflicts: true,
};

// Task type indicators for heuristic analysis
const TYPE_INDICATORS: Record<SubtaskType, string[]> = {
  research: ['find', 'search', 'discover', 'locate', 'identify', 'explore', 'investigate'],
  analysis: ['analyze', 'understand', 'examine', 'review', 'study', 'evaluate'],
  design: ['design', 'plan', 'architect', 'structure', 'outline', 'sketch'],
  implement: ['implement', 'create', 'build', 'write', 'code', 'develop', 'add'],
  test: ['test', 'verify', 'validate', 'check', 'ensure', 'assert'],
  refactor: ['refactor', 'improve', 'optimize', 'clean', 'simplify', 'restructure'],
  review: ['review', 'inspect', 'audit', 'check', 'examine'],
  document: ['document', 'describe', 'explain', 'annotate', 'comment'],
  integrate: ['integrate', 'connect', 'combine', 'merge', 'link'],
  deploy: ['deploy', 'release', 'publish', 'ship', 'launch'],
  merge: ['merge', 'combine', 'consolidate', 'aggregate', 'synthesize'],
};

// =============================================================================
// SMART DECOMPOSER
// =============================================================================

/**
 * Intelligently decomposes tasks using semantic analysis.
 *
 * @example
 * ```typescript
 * const decomposer = createSmartDecomposer({
 *   useLLM: true,
 *   llmProvider: async (task, context) => {
 *     // Call your LLM here
 *     return { subtasks: [...], strategy: 'parallel', reasoning: '...' };
 *   },
 * });
 *
 * const result = await decomposer.decompose(
 *   'Implement user authentication with OAuth2 and session management',
 *   { repoMap }
 * );
 *
 * console.log(`Decomposed into ${result.subtasks.length} subtasks`);
 * console.log(`Strategy: ${result.strategy}`);
 * ```
 */
export class SmartDecomposer {
  private config: Required<SmartDecomposerConfig>;
  private listeners: SmartDecomposerEventListener[] = [];
  private taskCounter = 0;

  constructor(config: SmartDecomposerConfig = {}) {
    this.config = {
      ...DEFAULT_CONFIG,
      ...config,
      llmProvider: config.llmProvider ?? DEFAULT_CONFIG.llmProvider,
    };
  }

  // ===========================================================================
  // DECOMPOSITION
  // ===========================================================================

  /**
   * Decompose a task into subtasks.
   */
  async decompose(
    task: string,
    context: DecomposeContext = {}
  ): Promise<SmartDecompositionResult> {
    this.emit({ type: 'decomposition.started', task });

    let subtasks: SmartSubtask[] = [];
    let strategy: DecompositionStrategy = this.config.defaultStrategy;
    let llmAssisted = false;

    // Try LLM-assisted decomposition first (with 1 retry before heuristic fallback)
    if (this.config.useLLM && this.config.llmProvider) {
      const maxLLMAttempts = 2;
      for (let attempt = 0; attempt < maxLLMAttempts; attempt++) {
        try {
          this.emit({ type: 'llm.called', task });
          const llmResult = await this.config.llmProvider(task, context);
          subtasks = this.convertLLMResult(llmResult);
          strategy = llmResult.strategy;
          llmAssisted = true;
          if (subtasks.length > 0) break; // Success
          // 0 subtasks on first attempt → retry
          if (attempt === 0) {
            this.emit({ type: 'llm.fallback', reason: 'LLM returned 0 subtasks, retrying...', task });
            continue;
          }
        } catch (error) {
          if (attempt === 0) {
            this.emit({ type: 'llm.fallback', reason: `${(error as Error).message}, retrying...`, task });
            continue;
          }
        }
        // Both attempts failed → return empty so orchestrator can try lastResortDecompose
        this.emit({ type: 'llm.fallback', reason: 'LLM failed after 2 attempts — skipping heuristic', task });
        subtasks = [];
        strategy = 'adaptive';
        llmAssisted = false;
      }
    } else {
      // Use heuristic decomposition
      const heuristicResult = this.decomposeHeuristic(task, context);
      subtasks = heuristicResult.subtasks;
      strategy = heuristicResult.strategy;
    }

    // Limit subtasks
    if (subtasks.length > this.config.maxSubtasks) {
      subtasks = subtasks.slice(0, this.config.maxSubtasks);
    }

    // Enhance with codebase awareness
    if (this.config.codebaseAware && context.repoMap) {
      subtasks = this.enhanceWithCodebaseContext(subtasks, context.repoMap);
    }

    // Build dependency graph
    const dependencyGraph = this.buildDependencyGraph(subtasks);

    // Check for cycles
    if (dependencyGraph.cycles.length > 0) {
      for (const cycle of dependencyGraph.cycles) {
        this.emit({ type: 'cycle.detected', cycle });
      }
    }

    // Detect resource conflicts
    let conflicts: ResourceConflict[] = [];
    if (this.config.detectConflicts) {
      conflicts = this.detectConflicts(subtasks);
      for (const conflict of conflicts) {
        this.emit({ type: 'conflict.detected', conflict });
      }
    }

    // Calculate totals
    const totalComplexity = subtasks.reduce((sum, t) => sum + t.complexity, 0);
    const totalEstimatedTokens = subtasks.reduce(
      (sum, t) => sum + (t.estimatedTokens ?? 1000),
      0
    );

    const result: SmartDecompositionResult = {
      originalTask: task,
      subtasks,
      dependencyGraph,
      conflicts,
      strategy,
      totalComplexity,
      totalEstimatedTokens,
      metadata: {
        decomposedAt: new Date(),
        codebaseAware: this.config.codebaseAware && !!context.repoMap,
        llmAssisted,
      },
    };

    this.emit({ type: 'decomposition.completed', result });

    return result;
  }

  /**
   * Convert LLM result to SmartSubtask array.
   */
  private convertLLMResult(llmResult: LLMDecomposeResult): SmartSubtask[] {
    const idMap = new Map<string, string>();

    // First pass: create IDs and populate lookup map with common LLM reference patterns
    const subtasks = llmResult.subtasks.map((s, index) => {
      const id = `task-${++this.taskCounter}`;
      idMap.set(s.description, id);
      idMap.set(String(index), id);
      // Common LLM reference patterns
      idMap.set(`task-${index}`, id);
      idMap.set(`subtask-${index}`, id);
      idMap.set(`st-${index}`, id);

      // F14: Populate modifies/reads from relevantFiles so downstream consumers
      // (F12 hollow retry prompts, quality gate) get concrete file targets.
      const isModifyType = ['implement', 'fix', 'refactor', 'integrate', 'test', 'deploy'].includes(s.type);

      return {
        id,
        description: s.description,
        status: 'pending' as SubtaskStatus,
        dependencies: [] as string[], // Will be resolved in second pass
        complexity: s.complexity,
        type: s.type,
        parallelizable: s.parallelizable,
        relevantFiles: s.relevantFiles,
        modifies: isModifyType ? s.relevantFiles : undefined,
        reads: s.relevantFiles,
        suggestedRole: s.suggestedRole,
      };
    });

    // Build set of all valid task IDs for strict filtering
    const validTaskIds = new Set(idMap.values());

    // Second pass: resolve dependencies with strict filtering
    return subtasks.map((subtask, index) => {
      const original = llmResult.subtasks[index];
      subtask.dependencies = original.dependencies
        .map((dep) => {
          const key = typeof dep === 'number' ? String(dep) : dep;
          return idMap.get(key) ?? idMap.get(key.trim()) ?? null;
        })
        .filter((dep): dep is string => {
          if (dep === null) return false;
          if (dep === subtask.id) return false;
          if (!validTaskIds.has(dep)) return false;
          return true;
        });

      // Update status based on dependencies
      subtask.status = subtask.dependencies.length > 0 ? 'blocked' : 'ready';

      return subtask;
    });
  }

  /**
   * Heuristic-based decomposition when LLM is not available.
   */
  private decomposeHeuristic(
    task: string,
    _context: DecomposeContext
  ): { subtasks: SmartSubtask[]; strategy: DecompositionStrategy } {
    const taskLower = task.toLowerCase();

    // Determine task type
    const primaryType = this.inferTaskType(taskLower);

    // Determine strategy
    const strategy = this.inferStrategy(taskLower, primaryType);

    // Generate subtasks based on strategy
    let subtasks: SmartSubtask[];

    switch (strategy) {
      case 'sequential':
        subtasks = this.generateSequentialSubtasks(task, primaryType);
        break;
      case 'parallel':
        subtasks = this.generateParallelSubtasks(task, primaryType);
        break;
      case 'hierarchical':
        subtasks = this.generateHierarchicalSubtasks(task, primaryType);
        break;
      case 'pipeline':
        subtasks = this.generatePipelineSubtasks(task, primaryType);
        break;
      default:
        subtasks = this.generateAdaptiveSubtasks(task, primaryType);
    }

    return { subtasks, strategy };
  }

  /**
   * Infer the primary task type from description.
   */
  private inferTaskType(taskLower: string): SubtaskType {
    for (const [type, indicators] of Object.entries(TYPE_INDICATORS)) {
      for (const indicator of indicators) {
        if (taskLower.includes(indicator)) {
          return type as SubtaskType;
        }
      }
    }
    return 'implement'; // Default
  }

  /**
   * Infer decomposition strategy from task description.
   */
  private inferStrategy(taskLower: string, primaryType: SubtaskType): DecompositionStrategy {
    // Sequential indicators
    if (
      taskLower.includes('then') ||
      taskLower.includes('after') ||
      taskLower.includes('before') ||
      taskLower.includes('first') ||
      taskLower.includes('step by step')
    ) {
      return 'sequential';
    }

    // Parallel indicators
    if (
      taskLower.includes('in parallel') ||
      taskLower.includes('simultaneously') ||
      taskLower.includes('at the same time') ||
      (taskLower.includes('all') && taskLower.includes('files'))
    ) {
      return 'parallel';
    }

    // Pipeline indicators
    if (
      taskLower.includes('process') ||
      taskLower.includes('transform') ||
      taskLower.includes('pipeline')
    ) {
      return 'pipeline';
    }

    // Hierarchical for complex tasks
    if (
      taskLower.includes('complex') ||
      taskLower.includes('comprehensive') ||
      taskLower.includes('full') ||
      taskLower.length > 200
    ) {
      return 'hierarchical';
    }

    // Type-based defaults
    switch (primaryType) {
      case 'research':
      case 'analysis':
        return 'parallel';
      case 'implement':
      case 'refactor':
        return 'adaptive';
      default:
        return 'adaptive';
    }
  }

  /**
   * Generate sequential subtasks.
   */
  private generateSequentialSubtasks(task: string, type: SubtaskType): SmartSubtask[] {
    const subtasks: SmartSubtask[] = [];
    let prevId: string | null = null;

    // Research phase
    const researchId = `task-${++this.taskCounter}`;
    subtasks.push({
      id: researchId,
      description: `Research and understand: ${task}`,
      status: 'ready',
      dependencies: [],
      complexity: 2,
      type: 'research',
      parallelizable: false,
    });
    prevId = researchId;

    // Main execution phase
    const executeId = `task-${++this.taskCounter}`;
    subtasks.push({
      id: executeId,
      description: `Execute: ${task}`,
      status: 'blocked',
      dependencies: [prevId],
      complexity: 5,
      type,
      parallelizable: false,
    });
    prevId = executeId;

    // Verification phase
    const verifyId = `task-${++this.taskCounter}`;
    subtasks.push({
      id: verifyId,
      description: `Verify and test: ${task}`,
      status: 'blocked',
      dependencies: [prevId],
      complexity: 2,
      type: 'test',
      parallelizable: false,
    });

    return subtasks;
  }

  /**
   * Generate parallel subtasks.
   */
  private generateParallelSubtasks(task: string, type: SubtaskType): SmartSubtask[] {
    const subtasks: SmartSubtask[] = [];

    // Split task into parts
    const parts = this.splitIntoParts(task);
    const partIds: string[] = [];

    for (const part of parts) {
      const id = `task-${++this.taskCounter}`;
      partIds.push(id);
      subtasks.push({
        id,
        description: part,
        status: 'ready',
        dependencies: [],
        complexity: Math.ceil(5 / parts.length),
        type,
        parallelizable: true,
      });
    }

    // Merge task
    subtasks.push({
      id: `task-${++this.taskCounter}`,
      description: `Combine results: ${task}`,
      status: 'blocked',
      dependencies: partIds,
      complexity: 2,
      type: 'merge',
      parallelizable: false,
    });

    return subtasks;
  }

  /**
   * Generate hierarchical subtasks.
   */
  private generateHierarchicalSubtasks(task: string, _type: SubtaskType): SmartSubtask[] {
    const subtasks: SmartSubtask[] = [];
    let prevId: string | null = null;

    const phases = [
      { name: 'Analysis', type: 'analysis' as SubtaskType, complexity: 2 },
      { name: 'Design', type: 'design' as SubtaskType, complexity: 3 },
      { name: 'Implementation', type: 'implement' as SubtaskType, complexity: 5 },
      { name: 'Testing', type: 'test' as SubtaskType, complexity: 2 },
      { name: 'Review', type: 'review' as SubtaskType, complexity: 2 },
    ];

    for (const phase of phases) {
      const id = `task-${++this.taskCounter}`;
      subtasks.push({
        id,
        description: `${phase.name}: ${task}`,
        status: prevId ? 'blocked' : 'ready',
        dependencies: prevId ? [prevId] : [],
        complexity: phase.complexity,
        type: phase.type,
        parallelizable: false,
      });
      prevId = id;
    }

    return subtasks;
  }

  /**
   * Generate pipeline subtasks.
   */
  private generatePipelineSubtasks(task: string, type: SubtaskType): SmartSubtask[] {
    const subtasks: SmartSubtask[] = [];
    let prevId: string | null = null;

    const stages = [
      { name: 'Input', desc: 'Gather inputs' },
      { name: 'Transform', desc: 'Process data' },
      { name: 'Validate', desc: 'Validate results' },
      { name: 'Output', desc: 'Generate output' },
    ];

    for (const stage of stages) {
      const id = `task-${++this.taskCounter}`;
      subtasks.push({
        id,
        description: `${stage.name}: ${stage.desc} for ${task}`,
        status: prevId ? 'blocked' : 'ready',
        dependencies: prevId ? [prevId] : [],
        complexity: 2,
        type,
        parallelizable: false,
      });
      prevId = id;
    }

    return subtasks;
  }

  /**
   * Generate adaptive subtasks (mix of strategies).
   */
  private generateAdaptiveSubtasks(task: string, type: SubtaskType): SmartSubtask[] {
    const subtasks: SmartSubtask[] = [];

    // Research (can be parallel)
    const researchId = `task-${++this.taskCounter}`;
    subtasks.push({
      id: researchId,
      description: `Research: ${task}`,
      status: 'ready',
      dependencies: [],
      complexity: 2,
      type: 'research',
      parallelizable: true,
    });

    // Analysis (can be parallel with research)
    const analysisId = `task-${++this.taskCounter}`;
    subtasks.push({
      id: analysisId,
      description: `Analyze requirements: ${task}`,
      status: 'ready',
      dependencies: [],
      complexity: 2,
      type: 'analysis',
      parallelizable: true,
    });

    // Implementation (depends on both)
    const implId = `task-${++this.taskCounter}`;
    subtasks.push({
      id: implId,
      description: `Implement: ${task}`,
      status: 'blocked',
      dependencies: [researchId, analysisId],
      complexity: 5,
      type,
      parallelizable: false,
    });

    // Testing (depends on implementation)
    subtasks.push({
      id: `task-${++this.taskCounter}`,
      description: `Test: ${task}`,
      status: 'blocked',
      dependencies: [implId],
      complexity: 2,
      type: 'test',
      parallelizable: false,
    });

    return subtasks;
  }

  /**
   * Split task description into parts.
   */
  private splitIntoParts(task: string): string[] {
    // Try to find natural splits
    const connectors = [' and ', ', ', '; ', ' also ', ' additionally '];
    let parts: string[] = [task];

    for (const connector of connectors) {
      if (task.toLowerCase().includes(connector.toLowerCase())) {
        parts = task.split(new RegExp(connector, 'i'));
        break;
      }
    }

    // Clean up and filter
    parts = parts
      .map((p) => p.trim())
      .filter((p) => p.length > 10);

    // If no good splits, create generic parts
    if (parts.length < 2) {
      parts = [
        `Part 1: ${task}`,
        `Part 2: ${task}`,
      ];
    }

    return parts.slice(0, 5);
  }

  /**
   * Enhance subtasks with codebase context.
   */
  private enhanceWithCodebaseContext(
    subtasks: SmartSubtask[],
    repoMap: RepoMap
  ): SmartSubtask[] {
    return subtasks.map((subtask) => {
      // Find relevant files based on task description
      const relevantFiles = this.findRelevantFiles(subtask.description, repoMap);

      // Estimate tokens based on relevant files
      const estimatedTokens = relevantFiles.reduce((sum, file) => {
        const chunk = repoMap.chunks.get(file);
        return sum + (chunk?.tokenCount ?? 500);
      }, 1000); // Base tokens for the task itself

      return {
        ...subtask,
        relevantFiles: relevantFiles.slice(0, 5),
        estimatedTokens,
      };
    });
  }

  /**
   * Find files relevant to a task description.
   */
  private findRelevantFiles(description: string, repoMap: RepoMap): string[] {
    const descLower = description.toLowerCase();
    const words = descLower.split(/\s+/).filter((w) => w.length > 3);
    const scored: Array<{ file: string; score: number }> = [];

    for (const [file, chunk] of repoMap.chunks) {
      let score = 0;

      // Check file path
      const fileLower = file.toLowerCase();
      for (const word of words) {
        if (fileLower.includes(word)) {
          score += 2;
        }
      }

      // Check symbols
      for (const symbol of chunk.symbols) {
        const symbolLower = symbol.toLowerCase();
        for (const word of words) {
          if (symbolLower.includes(word) || word.includes(symbolLower)) {
            score += 1;
          }
        }
      }

      if (score > 0) {
        scored.push({ file, score });
      }
    }

    // Sort by score and return top files
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, 10).map((s) => s.file);
  }

  // ===========================================================================
  // DEPENDENCY GRAPH
  // ===========================================================================

  /**
   * Build a dependency graph from subtasks.
   */
  buildDependencyGraph(subtasks: SmartSubtask[]): DependencyGraph {
    const dependencies = new Map<string, string[]>();
    const dependents = new Map<string, string[]>();

    // Build maps
    for (const subtask of subtasks) {
      dependencies.set(subtask.id, subtask.dependencies);

      for (const dep of subtask.dependencies) {
        if (!dependents.has(dep)) {
          dependents.set(dep, []);
        }
        dependents.get(dep)!.push(subtask.id);
      }
    }

    // Detect cycles
    const cycles = this.detectCycles(subtasks, dependencies);

    // Calculate execution order (topological sort)
    const executionOrder = this.topologicalSort(subtasks, dependencies);

    // Calculate parallel groups
    const parallelGroups = this.calculateParallelGroups(subtasks, dependencies);

    return {
      dependencies,
      dependents,
      executionOrder,
      parallelGroups,
      cycles,
    };
  }

  /**
   * Detect cycles in dependency graph.
   */
  private detectCycles(
    subtasks: SmartSubtask[],
    dependencies: Map<string, string[]>
  ): string[][] {
    const cycles: string[][] = [];
    const visited = new Set<string>();
    const inStack = new Set<string>();

    const dfs = (id: string, path: string[]): void => {
      if (inStack.has(id)) {
        // Found cycle
        const cycleStart = path.indexOf(id);
        cycles.push(path.slice(cycleStart));
        return;
      }

      if (visited.has(id)) return;

      visited.add(id);
      inStack.add(id);

      const deps = dependencies.get(id) ?? [];
      for (const dep of deps) {
        dfs(dep, [...path, id]);
      }

      inStack.delete(id);
    };

    for (const subtask of subtasks) {
      dfs(subtask.id, []);
    }

    return cycles;
  }

  /**
   * Topological sort of tasks.
   */
  private topologicalSort(
    subtasks: SmartSubtask[],
    dependencies: Map<string, string[]>
  ): string[] {
    const result: string[] = [];
    const visited = new Set<string>();
    const temp = new Set<string>();

    const visit = (id: string): boolean => {
      if (temp.has(id)) return false; // Cycle
      if (visited.has(id)) return true;

      temp.add(id);

      const deps = dependencies.get(id) ?? [];
      for (const dep of deps) {
        if (!visit(dep)) return false;
      }

      temp.delete(id);
      visited.add(id);
      result.push(id);
      return true;
    };

    for (const subtask of subtasks) {
      visit(subtask.id);
    }

    return result;
  }

  /**
   * Calculate groups of tasks that can run in parallel.
   */
  private calculateParallelGroups(
    subtasks: SmartSubtask[],
    dependencies: Map<string, string[]>
  ): string[][] {
    const groups: string[][] = [];
    const completed = new Set<string>();
    const remaining = new Set(subtasks.map((s) => s.id));

    while (remaining.size > 0) {
      const group: string[] = [];

      for (const id of remaining) {
        const deps = dependencies.get(id) ?? [];
        const allDepsCompleted = deps.every((dep) => completed.has(dep));

        if (allDepsCompleted) {
          const subtask = subtasks.find((s) => s.id === id);
          if (subtask?.parallelizable || group.length === 0) {
            group.push(id);
          }
        }
      }

      if (group.length === 0) {
        // No progress - likely a cycle, break to avoid infinite loop
        break;
      }

      groups.push(group);
      for (const id of group) {
        completed.add(id);
        remaining.delete(id);
      }
    }

    return groups;
  }

  // ===========================================================================
  // CONFLICT DETECTION
  // ===========================================================================

  /**
   * Detect resource conflicts between subtasks.
   */
  detectConflicts(subtasks: SmartSubtask[]): ResourceConflict[] {
    const conflicts: ResourceConflict[] = [];
    const writeResources = new Map<string, string[]>(); // resource -> taskIds
    const readResources = new Map<string, string[]>();

    // Collect resource usage
    for (const subtask of subtasks) {
      for (const resource of subtask.modifies ?? []) {
        if (!writeResources.has(resource)) {
          writeResources.set(resource, []);
        }
        writeResources.get(resource)!.push(subtask.id);
      }

      for (const resource of subtask.reads ?? []) {
        if (!readResources.has(resource)) {
          readResources.set(resource, []);
        }
        readResources.get(resource)!.push(subtask.id);
      }
    }

    // Check for write-write conflicts
    for (const [resource, taskIds] of writeResources) {
      if (taskIds.length > 1) {
        // Check if tasks are in parallel groups
        const parallelConflict = this.areInParallel(taskIds, subtasks);
        if (parallelConflict) {
          conflicts.push({
            resource,
            taskIds,
            type: 'write-write',
            severity: 'error',
            suggestion: `Tasks ${taskIds.join(', ')} both write to ${resource}. ` +
              `Consider making them sequential or coordinating through the blackboard.`,
          });
        }
      }
    }

    // Check for read-write conflicts
    for (const [resource, writeTaskIds] of writeResources) {
      const readTaskIds = readResources.get(resource) ?? [];
      for (const writeId of writeTaskIds) {
        for (const readId of readTaskIds) {
          if (writeId !== readId && this.areInParallel([writeId, readId], subtasks)) {
            conflicts.push({
              resource,
              taskIds: [writeId, readId],
              type: 'read-write',
              severity: 'warning',
              suggestion: `Task ${writeId} writes to ${resource} while ${readId} reads it. ` +
                `Consider adding a dependency to ensure correct ordering.`,
            });
          }
        }
      }
    }

    return conflicts;
  }

  /**
   * Check if tasks can run in parallel (no dependencies between them).
   */
  private areInParallel(taskIds: string[], subtasks: SmartSubtask[]): boolean {
    const taskMap = new Map(subtasks.map((s) => [s.id, s]));

    for (let i = 0; i < taskIds.length; i++) {
      for (let j = i + 1; j < taskIds.length; j++) {
        const task1 = taskMap.get(taskIds[i]);
        const task2 = taskMap.get(taskIds[j]);

        if (task1 && task2) {
          // Check if either depends on the other
          if (
            !task1.dependencies.includes(task2.id) &&
            !task2.dependencies.includes(task1.id)
          ) {
            return true; // Can run in parallel
          }
        }
      }
    }

    return false;
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  /**
   * Subscribe to events.
   */
  on(listener: SmartDecomposerEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  private emit(event: SmartDecomposerEvent): void {
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
// F5: DECOMPOSITION VALIDATION
// =============================================================================

export interface DecompositionValidationResult {
  valid: boolean;
  issues: string[];
  warnings: string[];
}

/**
 * F5: Validate a decomposition result for structural correctness, feasibility, and granularity.
 *
 * Checks:
 * 1. Structural: no cycles, valid dependency refs, each subtask has description
 * 2. Feasibility: referenced files exist (warning only)
 * 3. Granularity: no subtask complexity > 7 (should split further)
 */
export function validateDecomposition(result: SmartDecompositionResult): DecompositionValidationResult {
  const issues: string[] = [];
  const warnings: string[] = [];
  const taskIds = new Set(result.subtasks.map(s => s.id));

  // 1. Structural checks
  // Cycle detection
  if (result.dependencyGraph.cycles.length > 0) {
    for (const cycle of result.dependencyGraph.cycles) {
      issues.push(`Dependency cycle detected: ${cycle.join(' → ')}`);
    }
  }

  // Valid dependency references
  for (const subtask of result.subtasks) {
    for (const dep of subtask.dependencies) {
      if (!taskIds.has(dep)) {
        issues.push(`Task ${subtask.id} references non-existent dependency: ${dep}`);
      }
      if (dep === subtask.id) {
        issues.push(`Task ${subtask.id} depends on itself`);
      }
    }
    // Each subtask must have a meaningful description
    if (!subtask.description || subtask.description.trim().length < 5) {
      issues.push(`Task ${subtask.id} has empty or trivial description`);
    }
  }

  // 2. Feasibility: check if referenced files exist (warnings only — files may be created by earlier tasks)
  for (const subtask of result.subtasks) {
    if (subtask.relevantFiles) {
      for (const file of subtask.relevantFiles) {
        try {
          const fs = require('node:fs');
          const path = require('node:path');
          if (!fs.existsSync(path.resolve(file))) {
            warnings.push(`Task ${subtask.id} references non-existent file: ${file}`);
          }
        } catch {
          // Can't check — skip
        }
      }
    }
  }

  // 3. Granularity: flag overly complex subtasks
  for (const subtask of result.subtasks) {
    if (subtask.complexity > 7) {
      warnings.push(`Task ${subtask.id} has complexity ${subtask.complexity} (>7) — consider splitting further`);
    }
  }

  // Additional structural check: at least 2 subtasks
  if (result.subtasks.length < 2) {
    issues.push(`Decomposition produced only ${result.subtasks.length} subtask(s) — too few for swarm mode`);
  }

  return {
    valid: issues.length === 0,
    issues,
    warnings,
  };
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a smart decomposer.
 *
 * @example
 * ```typescript
 * // Simple heuristic decomposition
 * const decomposer = createSmartDecomposer();
 *
 * // LLM-assisted decomposition
 * const decomposer = createSmartDecomposer({
 *   useLLM: true,
 *   llmProvider: async (task, context) => {
 *     const response = await llm.complete({
 *       prompt: `Decompose this task: ${task}`,
 *       // ...
 *     });
 *     return parseDecomposition(response);
 *   },
 * });
 *
 * const result = await decomposer.decompose('Build a REST API for user management');
 * ```
 */
export function createSmartDecomposer(
  config: SmartDecomposerConfig = {}
): SmartDecomposer {
  return new SmartDecomposer(config);
}

/**
 * Create an LLM prompt for task decomposition.
 */
export function createDecompositionPrompt(
  task: string,
  context: DecomposeContext
): string {
  const parts = [
    'You are a task decomposition expert. Break down the following task into subtasks.',
    '',
    `Task: ${task}`,
    '',
  ];

  if (context.repoMap) {
    parts.push('Codebase context:');
    parts.push(`- ${context.repoMap.chunks.size} files`);
    parts.push(`- Entry points: ${context.repoMap.entryPoints.slice(0, 3).join(', ')}`);
    parts.push('');
  }

  if (context.hints && context.hints.length > 0) {
    parts.push('Hints:');
    for (const hint of context.hints) {
      parts.push(`- ${hint}`);
    }
    parts.push('');
  }

  parts.push('For each subtask, provide:');
  parts.push('1. Description');
  parts.push('2. Type (research, analysis, design, implement, test, refactor, review, document, integrate, deploy, merge)');
  parts.push('3. Complexity (1-10)');
  parts.push('4. Dependencies (which other subtasks must complete first)');
  parts.push('5. Whether it can run in parallel with other tasks');
  parts.push('');
  parts.push('Also suggest an overall strategy: sequential, parallel, hierarchical, adaptive, or pipeline.');
  parts.push('');
  parts.push('Respond in JSON format.');

  return parts.join('\n');
}

/**
 * Normalize a raw subtask object from JSON into a consistent shape.
 */
function normalizeSubtask(s: any): LLMDecomposeResult['subtasks'][number] {
  return {
    description: s.description || s.desc || s.title || s.name || '',
    type: s.type || s.task_type || s.category || 'implement',
    complexity: s.complexity || s.difficulty || 3,
    dependencies: s.dependencies || s.deps || s.depends_on || [],
    parallelizable: s.parallelizable ?? s.parallel ?? true,
    relevantFiles: s.relevantFiles || s.relevant_files || s.files,
    suggestedRole: s.suggestedRole || s.suggested_role || s.role,
  };
}

/**
 * Try to extract subtasks from a parsed JSON object/array.
 * Returns null if the structure doesn't contain usable subtask data.
 */
function extractSubtasksFromParsed(parsed: any): LLMDecomposeResult | null {
  // Handle array-at-root: some models return [{...}, {...}] instead of {"subtasks": [...]}
  if (Array.isArray(parsed)) {
    parsed = { subtasks: parsed, strategy: 'adaptive', reasoning: '(array-at-root)' };
  }

  // Normalize alternative key names: tasks, steps, task_list → subtasks
  const subtasksArray = parsed.subtasks
    ?? parsed.tasks
    ?? parsed.steps
    ?? parsed.task_list
    ?? parsed.decomposition;

  if (!subtasksArray || !Array.isArray(subtasksArray) || subtasksArray.length === 0) {
    return null;
  }

  return {
    subtasks: subtasksArray.map(normalizeSubtask),
    strategy: parsed.strategy || 'adaptive',
    reasoning: parsed.reasoning || '',
  };
}

/**
 * Layer 1: Lenient JSON repair.
 * Fixes common LLM JSON mistakes before parsing:
 * - Trailing commas before ] and }
 * - JS-style comments (// and block comments)
 * - Single-quoted strings → double-quoted
 * - Unquoted object keys
 */
export function repairJSON(jsonStr: string): string {
  let s = jsonStr;

  // Strip JS-style line comments (// ...) outside strings
  s = s.replace(/("(?:[^"\\]|\\.)*")|\/\/[^\n]*/g, (_match, str) => str ?? '');

  // Strip JS-style block comments outside strings
  s = s.replace(/("(?:[^"\\]|\\.)*")|\/\*[\s\S]*?\*\//g, (_match, str) => str ?? '');

  // Replace single-quoted strings with double-quoted (outside existing double-quoted strings)
  s = s.replace(/("(?:[^"\\]|\\.)*")|'((?:[^'\\]|\\.)*)'/g, (_match, dq, sq) => {
    if (dq) return dq; // Already double-quoted, keep as-is
    const escaped = sq.replace(/(?<!\\)"/g, '\\"');
    return `"${escaped}"`;
  });

  // Fix unquoted object keys: { key: "value" } → { "key": "value" }
  s = s.replace(/("(?:[^"\\]|\\.)*")|\b([a-zA-Z_][a-zA-Z0-9_]*)\s*:/g, (match, str, key) => {
    if (str) return match; // Inside a string, keep as-is
    return `"${key}":`;
  });

  // Strip trailing commas before ] and }
  s = s.replace(/,\s*([}\]])/g, '$1');

  return s;
}

/**
 * Layer 2: Extract subtasks from natural language (numbered/bulleted lists).
 * Handles formats like:
 * - "1. Description" / "1) Description"
 * - "- Description" / "* Description"
 * - "Task 1: Description" / "Step 1: Description"
 * - "- [ ] Description" / "- [x] Description" (markdown task lists)
 */
export function extractSubtasksFromNaturalLanguage(response: string): LLMDecomposeResult | null {
  const items: string[] = [];

  // Try markdown task lists first: - [ ] Task / - [x] Task
  const taskListPattern = /^[ \t]*[-*]\s*\[[ x]\]\s+(.+)$/gm;
  let match;
  while ((match = taskListPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    if (desc.length > 5) items.push(desc);
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  // Try numbered lists: 1. Desc / 1) Desc / 1: Desc
  items.length = 0;
  const numberedPattern = /^[ \t]*\d+[.):\-]\s+(.+)$/gm;
  while ((match = numberedPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    if (desc.length > 5) items.push(desc);
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  // Try bulleted lists: - Desc / * Desc (but not markdown task lists already tried)
  items.length = 0;
  const bulletPattern = /^[ \t]*[-*]\s+(?!\[[ x]\])(.+)$/gm;
  while ((match = bulletPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    if (desc.length > 5) items.push(desc);
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  // Try "Task N:" / "Step N:" / "Subtask N:" style headers
  items.length = 0;
  const headerPattern = /^[ \t]*(?:task|step|subtask|phase)\s*\d+[:.]\s*(.+)$/gim;
  while ((match = headerPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    if (desc.length > 5) items.push(desc);
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  // Try markdown headers: ## Subtask 1 / ### Step: Description
  items.length = 0;
  const mdHeaderPattern = /^#{2,4}\s+(?:(?:subtask|step|task|phase)\s*\d*[:.]*\s*)?(.+)$/gim;
  while ((match = mdHeaderPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    // Skip generic headers like "Summary", "Strategy", "Overview"
    if (desc.length > 5 && !/^(summary|strategy|overview|reasoning|conclusion|notes?)$/i.test(desc)) {
      items.push(desc);
    }
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  return null;
}

/**
 * Build an LLMDecomposeResult from a flat list of description strings.
 * Assigns sequential dependencies and infers task type from keywords.
 */
function buildSubtasksFromList(items: string[]): LLMDecomposeResult {
  const TYPE_KEYWORDS: Record<string, string[]> = {
    research: ['research', 'investigate', 'explore', 'analyze', 'understand', 'study', 'review existing'],
    design: ['design', 'plan', 'architect', 'schema', 'structure'],
    test: ['test', 'verify', 'validate', 'assert', 'check'],
    refactor: ['refactor', 'clean up', 'reorganize', 'simplify'],
    document: ['document', 'readme', 'docs', 'comment'],
    integrate: ['integrate', 'wire', 'connect', 'combine', 'merge'],
    deploy: ['deploy', 'release', 'publish', 'ship'],
  };

  return {
    subtasks: items.map((desc, i) => {
      const lower = desc.toLowerCase();
      let type: SubtaskType = 'implement';
      for (const [t, keywords] of Object.entries(TYPE_KEYWORDS)) {
        if (keywords.some(k => lower.includes(k))) {
          type = t as SubtaskType;
          break;
        }
      }
      return {
        description: desc,
        type,
        complexity: 3,
        dependencies: i > 0 ? [String(i - 1)] : [],
        parallelizable: i === 0 || type === 'research' || type === 'test',
      };
    }),
    strategy: 'sequential',
    reasoning: '(extracted from natural language list)',
  };
}

/**
 * Layer 3: Last-ditch single mega-task extraction.
 * If there's meaningful text but no structure could be found,
 * wrap the response as a single "implement" subtask so the swarm
 * has something to work with rather than aborting entirely.
 */
function extractMegaTask(response: string): LLMDecomposeResult | null {
  // Strip code blocks, JSON fragments, and whitespace to get prose content
  const prose = response
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\{[\s\S]*?\}/g, '')
    .replace(/\[[\s\S]*?\]/g, '')
    .trim();

  // Only create mega-task if there's substantial text (not just JSON garbage)
  if (prose.length < 20) return null;

  const desc = prose.length > 200
    ? prose.slice(0, 200).replace(/\s+\S*$/, '') + '...'
    : prose;

  return {
    subtasks: [{
      description: desc,
      type: 'implement',
      complexity: 5,
      dependencies: [],
      parallelizable: false,
    }],
    strategy: 'adaptive',
    reasoning: '(single mega-task — parser could not extract structured subtasks)',
  };
}

/**
 * Parse LLM response into decomposition result.
 *
 * Uses progressive fallback layers to handle messy LLM output:
 * 1. Standard JSON extraction (code blocks, raw JSON)
 * 2. Lenient JSON repair (trailing commas, comments, single quotes, unquoted keys)
 * 3. Truncated JSON recovery (missing closing brackets)
 * 4. Natural language extraction (numbered/bulleted lists, markdown task lists)
 * 5. Single mega-task fallback (wrap prose as one subtask)
 */
export function parseDecompositionResponse(response: string): LLMDecomposeResult {
  if (!response || response.trim().length === 0) {
    return {
      subtasks: [],
      strategy: 'adaptive',
      reasoning: '',
      parseError: 'Empty response from LLM',
    };
  }

  // ── Step 1: Extract JSON string (code block or raw) ──────────────
  let jsonStr: string | undefined;
  const codeBlockMatch = response.match(/```(?:json)?\s*\n?([\s\S]*?)```/);
  if (codeBlockMatch) {
    jsonStr = codeBlockMatch[1].trim();
  }
  if (!jsonStr) {
    // If the response starts with `[`, try array regex first to avoid
    // \{[\s\S]*\} greedily matching across multiple objects in the array
    const trimmed = response.trim();
    const jsonMatch = trimmed.startsWith('[')
      ? (response.match(/\[[\s\S]*\]/) || response.match(/\{[\s\S]*\}/))
      : (response.match(/\{[\s\S]*\}/) || response.match(/\[[\s\S]*\]/));
    if (jsonMatch) jsonStr = jsonMatch[0];
  }

  // ── Step 2: Try strict JSON parse ────────────────────────────────
  if (jsonStr) {
    try {
      const parsed = JSON.parse(jsonStr);
      const result = extractSubtasksFromParsed(parsed);
      if (result) return result;
    } catch {
      // Strict parse failed — continue to lenient repair
    }

    // ── Step 3: Lenient JSON repair + parse ──────────────────────────
    try {
      const repaired = repairJSON(jsonStr);
      const parsed = JSON.parse(repaired);
      const result = extractSubtasksFromParsed(parsed);
      if (result) {
        result.reasoning = result.reasoning
          ? result.reasoning + ' (repaired JSON)'
          : '(repaired JSON)';
        return result;
      }
    } catch {
      // Repaired parse also failed — continue to truncation recovery
    }
  }

  // ── Step 4: Truncated JSON recovery ────────────────────────────────
  const recovered = tryRecoverTruncatedJSON(response);
  if (recovered) {
    try {
      const parsed = JSON.parse(recovered);
      const result = extractSubtasksFromParsed(parsed);
      if (result) {
        result.reasoning = result.reasoning
          ? result.reasoning + ' (recovered from truncated response)'
          : '(recovered from truncated response)';
        return result;
      }
    } catch {
      // Truncation recovery also failed — try repaired version
      try {
        const repairedRecovered = repairJSON(recovered);
        const parsed = JSON.parse(repairedRecovered);
        const result = extractSubtasksFromParsed(parsed);
        if (result) {
          result.reasoning = '(recovered from truncated + repaired JSON)';
          return result;
        }
      } catch {
        // All JSON approaches exhausted
      }
    }
  }

  // ── Step 5: Natural language extraction ────────────────────────────
  const nlResult = extractSubtasksFromNaturalLanguage(response);
  if (nlResult) return nlResult;

  // ── Step 6: Single mega-task fallback ──────────────────────────────
  const megaResult = extractMegaTask(response);
  if (megaResult) return megaResult;

  // ── Truly nothing worked ───────────────────────────────────────────
  return {
    subtasks: [],
    strategy: 'adaptive',
    reasoning: '',
    parseError: `All parse strategies failed. First 200 chars: ${response.slice(0, 200)}`,
  };
}

/**
 * Attempt to recover a truncated JSON response by trimming incomplete trailing
 * content and adding missing closing brackets/braces.
 *
 * Works for the common case where the LLM output was cut off mid-JSON-array,
 * e.g.: `{"subtasks": [ {...}, {...}, {"desc` → trim last incomplete object → close array & object.
 */
function tryRecoverTruncatedJSON(response: string): string | null {
  // Extract JSON portion (from code block or raw)
  let jsonStr: string | undefined;
  const codeBlockMatch = response.match(/```(?:json)?\s*\n?([\s\S]*)/);
  if (codeBlockMatch) {
    // No closing ``` required — that's the truncation
    jsonStr = codeBlockMatch[1].replace(/```\s*$/, '').trim();
  }
  if (!jsonStr) {
    const jsonMatch = response.match(/\{[\s\S]*/);
    if (jsonMatch) jsonStr = jsonMatch[0].trim();
  }
  if (!jsonStr) return null;

  // Find the last complete JSON object in the subtasks array.
  // Strategy: find last `}` that closes a complete array element, trim there, close brackets.
  // We search backwards for `},` or `}\n` patterns that likely end a complete subtask object.
  let lastGoodPos = -1;
  let braceDepth = 0;
  let bracketDepth = 0;
  let inString = false;
  let escape = false;

  for (let i = 0; i < jsonStr.length; i++) {
    const ch = jsonStr[i];
    if (escape) { escape = false; continue; }
    if (ch === '\\' && inString) { escape = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;

    if (ch === '{') braceDepth++;
    else if (ch === '}') {
      braceDepth--;
      // When we close an object at brace depth 1 (inside the top-level object),
      // this is likely a complete subtask object inside the array
      if (braceDepth === 1 && bracketDepth === 1) {
        lastGoodPos = i;
      }
    } else if (ch === '[') bracketDepth++;
    else if (ch === ']') bracketDepth--;
  }

  if (lastGoodPos === -1) return null;

  // Trim to last complete subtask object, then close the JSON structure
  let trimmed = jsonStr.slice(0, lastGoodPos + 1);
  // Remove trailing comma if present
  trimmed = trimmed.replace(/,\s*$/, '');
  // Close open brackets: we need to close the subtasks array and the root object
  // Count what's still open
  let openBraces = 0;
  let openBrackets = 0;
  inString = false;
  escape = false;
  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i];
    if (escape) { escape = false; continue; }
    if (ch === '\\' && inString) { escape = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;
    if (ch === '{') openBraces++;
    else if (ch === '}') openBraces--;
    else if (ch === '[') openBrackets++;
    else if (ch === ']') openBrackets--;
  }

  // Close remaining open structures
  for (let i = 0; i < openBrackets; i++) trimmed += ']';
  for (let i = 0; i < openBraces; i++) trimmed += '}';

  return trimmed;
}
