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

export type SubtaskType =
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
}

/**
 * Events emitted by the smart decomposer.
 */
export type SmartDecomposerEvent =
  | { type: 'decomposition.started'; task: string }
  | { type: 'decomposition.completed'; result: SmartDecompositionResult }
  | { type: 'llm.called'; task: string }
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

    let subtasks: SmartSubtask[];
    let strategy: DecompositionStrategy;
    let llmAssisted = false;

    // Try LLM-assisted decomposition first
    if (this.config.useLLM && this.config.llmProvider) {
      try {
        this.emit({ type: 'llm.called', task });
        const llmResult = await this.config.llmProvider(task, context);
        subtasks = this.convertLLMResult(llmResult);
        strategy = llmResult.strategy;
        llmAssisted = true;

        // C2: Fall back to heuristic if LLM returned 0 subtasks
        if (subtasks.length === 0) {
          const heuristicResult = this.decomposeHeuristic(task, context);
          subtasks = heuristicResult.subtasks;
          strategy = heuristicResult.strategy;
          llmAssisted = false;
        }
      } catch {
        // Fall back to heuristic decomposition
        const heuristicResult = this.decomposeHeuristic(task, context);
        subtasks = heuristicResult.subtasks;
        strategy = heuristicResult.strategy;
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

    // First pass: create IDs
    return llmResult.subtasks.map((s, index) => {
      const id = `task-${++this.taskCounter}`;
      idMap.set(s.description, id);
      idMap.set(String(index), id);

      return {
        id,
        description: s.description,
        status: 'pending' as SubtaskStatus,
        dependencies: [] as string[], // Will be resolved in second pass
        complexity: s.complexity,
        type: s.type,
        parallelizable: s.parallelizable,
        relevantFiles: s.relevantFiles,
        suggestedRole: s.suggestedRole,
      };
    }).map((subtask, index) => {
      // Second pass: resolve dependencies
      const original = llmResult.subtasks[index];
      subtask.dependencies = original.dependencies
        .map((dep) => idMap.get(dep) ?? dep)
        .filter((dep) => dep !== subtask.id);

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
        return 'sequential';
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
 * Parse LLM response into decomposition result.
 */
export function parseDecompositionResponse(response: string): LLMDecomposeResult {
  try {
    // Try to extract JSON from the response
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error('No JSON found in response');
    }

    const parsed = JSON.parse(jsonMatch[0]);

    return {
      subtasks: (parsed.subtasks || []).map((s: any) => ({
        description: s.description || '',
        type: s.type || 'implement',
        complexity: s.complexity || 3,
        dependencies: s.dependencies || [],
        parallelizable: s.parallelizable ?? true,
        relevantFiles: s.relevantFiles,
        suggestedRole: s.suggestedRole,
      })),
      strategy: parsed.strategy || 'adaptive',
      reasoning: parsed.reasoning || '',
    };
  } catch {
    // Return default if parsing fails
    return {
      subtasks: [],
      strategy: 'adaptive',
      reasoning: 'Failed to parse LLM response',
    };
  }
}
