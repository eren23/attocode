/**
 * Lesson 15: Task Decomposer
 *
 * Breaks down complex tasks into smaller subtasks.
 * Supports different decomposition strategies.
 */

import type {
  Task,
  DecompositionOptions,
  DecompositionResult,
  DecompositionStrategy,
} from './types.js';

// =============================================================================
// DEFAULT OPTIONS
// =============================================================================

const DEFAULT_OPTIONS: DecompositionOptions = {
  granularity: 5,
  maxSubtasks: 5,
  flatten: false,
  strategy: 'adaptive',
};

// =============================================================================
// DECOMPOSER
// =============================================================================

/**
 * Breaks down tasks into smaller subtasks.
 */
export class TaskDecomposer {
  private options: DecompositionOptions;

  constructor(options: Partial<DecompositionOptions> = {}) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
  }

  // =============================================================================
  // DECOMPOSITION
  // =============================================================================

  /**
   * Decompose a task into subtasks.
   */
  decompose(task: Task): DecompositionResult {
    // Skip if already has subtasks
    if (task.subtasks && task.subtasks.length > 0) {
      return {
        original: task,
        subtasks: task.subtasks,
        strategy: 'hierarchical',
        dependencies: this.buildDependencyMap(task.subtasks),
      };
    }

    // Determine strategy
    const strategy = this.options.strategy === 'adaptive'
      ? this.determineStrategy(task)
      : this.options.strategy;

    // Decompose based on strategy
    let subtasks: Task[];
    switch (strategy) {
      case 'sequential':
        subtasks = this.decomposeSequential(task);
        break;
      case 'parallel':
        subtasks = this.decomposeParallel(task);
        break;
      case 'hierarchical':
        subtasks = this.decomposeHierarchical(task);
        break;
      default:
        subtasks = this.decomposeSequential(task);
    }

    // Limit subtasks
    if (subtasks.length > this.options.maxSubtasks) {
      subtasks = subtasks.slice(0, this.options.maxSubtasks);
    }

    // Flatten if requested
    if (this.options.flatten) {
      subtasks = this.flatten(subtasks);
    }

    return {
      original: task,
      subtasks,
      strategy,
      dependencies: this.buildDependencyMap(subtasks),
    };
  }

  /**
   * Determine the best strategy for a task.
   */
  private determineStrategy(task: Task): DecompositionStrategy {
    const description = task.description.toLowerCase();

    // Sequential for process-oriented tasks
    if (
      description.includes('then') ||
      description.includes('after') ||
      description.includes('first') ||
      description.includes('step')
    ) {
      return 'sequential';
    }

    // Parallel for independent tasks
    if (
      description.includes('all') ||
      description.includes('each') ||
      description.includes('multiple') ||
      description.includes('batch')
    ) {
      return 'parallel';
    }

    // Hierarchical for complex tasks
    if (
      (task.complexity ?? 0) > 5 ||
      description.includes('complex') ||
      description.includes('refactor')
    ) {
      return 'hierarchical';
    }

    // Default to sequential
    return 'sequential';
  }

  // =============================================================================
  // DECOMPOSITION STRATEGIES
  // =============================================================================

  /**
   * Decompose into sequential subtasks.
   */
  private decomposeSequential(task: Task): Task[] {
    const subtasks: Task[] = [];
    let counter = 0;
    const generateId = () => `${task.id}-sub-${++counter}`;

    // Standard sequential breakdown
    subtasks.push(
      {
        id: generateId(),
        description: `Prepare for: ${task.description}`,
        status: 'pending',
        dependencies: [],
        complexity: Math.max(1, (task.complexity ?? 3) - 2),
      },
      {
        id: generateId(),
        description: `Execute: ${task.description}`,
        status: 'blocked',
        dependencies: [subtasks[0]?.id].filter(Boolean),
        complexity: task.complexity ?? 3,
      },
      {
        id: generateId(),
        description: `Verify: ${task.description}`,
        status: 'blocked',
        dependencies: [subtasks[1]?.id].filter(Boolean),
        complexity: Math.max(1, (task.complexity ?? 3) - 1),
      }
    );

    return subtasks;
  }

  /**
   * Decompose into parallel subtasks.
   */
  private decomposeParallel(task: Task): Task[] {
    const subtasks: Task[] = [];
    let counter = 0;
    const generateId = () => `${task.id}-sub-${++counter}`;

    // Create independent subtasks
    const parts = this.splitIntoParts(task.description);
    const complexity = Math.ceil((task.complexity ?? 3) / parts.length);

    for (const part of parts) {
      subtasks.push({
        id: generateId(),
        description: part,
        status: 'ready', // All can start immediately
        dependencies: [],
        complexity,
      });
    }

    // Add a final merge task
    subtasks.push({
      id: generateId(),
      description: `Combine results of: ${task.description}`,
      status: 'blocked',
      dependencies: subtasks.slice(0, -1).map((t) => t.id),
      complexity: 2,
    });

    return subtasks;
  }

  /**
   * Decompose into hierarchical subtasks.
   */
  private decomposeHierarchical(task: Task): Task[] {
    const subtasks: Task[] = [];
    let counter = 0;
    const generateId = () => `${task.id}-sub-${++counter}`;

    // Phase 1: Analysis
    const analysisTask: Task = {
      id: generateId(),
      description: `Analyze requirements for: ${task.description}`,
      status: 'pending',
      dependencies: [],
      complexity: 2,
    };
    subtasks.push(analysisTask);

    // Phase 2: Planning
    const planningTask: Task = {
      id: generateId(),
      description: `Plan approach for: ${task.description}`,
      status: 'blocked',
      dependencies: [analysisTask.id],
      complexity: 3,
    };
    subtasks.push(planningTask);

    // Phase 3: Implementation (can be broken down further)
    const implTask: Task = {
      id: generateId(),
      description: `Implement: ${task.description}`,
      status: 'blocked',
      dependencies: [planningTask.id],
      complexity: task.complexity ?? 5,
    };
    subtasks.push(implTask);

    // Phase 4: Testing
    const testTask: Task = {
      id: generateId(),
      description: `Test: ${task.description}`,
      status: 'blocked',
      dependencies: [implTask.id],
      complexity: 2,
    };
    subtasks.push(testTask);

    // Phase 5: Finalization
    subtasks.push({
      id: generateId(),
      description: `Finalize: ${task.description}`,
      status: 'blocked',
      dependencies: [testTask.id],
      complexity: 1,
    });

    return subtasks;
  }

  /**
   * Split a task description into parts.
   */
  private splitIntoParts(description: string): string[] {
    // Try to find natural splits
    const connectors = ['and', ',', ';', 'also', 'additionally'];
    let parts: string[] = [description];

    for (const connector of connectors) {
      const regex = new RegExp(`\\s+${connector}\\s+`, 'gi');
      parts = parts.flatMap((p) => p.split(regex));
    }

    // Clean up and filter
    parts = parts
      .map((p) => p.trim())
      .filter((p) => p.length > 10);

    // If no good splits, create generic parts
    if (parts.length < 2) {
      parts = [
        `Part 1 of: ${description}`,
        `Part 2 of: ${description}`,
      ];
    }

    return parts.slice(0, this.options.maxSubtasks);
  }

  // =============================================================================
  // UTILITIES
  // =============================================================================

  /**
   * Flatten hierarchical subtasks into a single list.
   */
  private flatten(tasks: Task[]): Task[] {
    const flat: Task[] = [];

    const visit = (task: Task) => {
      flat.push({ ...task, subtasks: undefined });
      if (task.subtasks) {
        for (const subtask of task.subtasks) {
          visit(subtask);
        }
      }
    };

    for (const task of tasks) {
      visit(task);
    }

    return flat;
  }

  /**
   * Build a dependency map from tasks.
   */
  private buildDependencyMap(tasks: Task[]): Map<string, string[]> {
    const deps = new Map<string, string[]>();

    for (const task of tasks) {
      deps.set(task.id, task.dependencies);
    }

    return deps;
  }

  /**
   * Merge subtasks back into their parent.
   */
  merge(original: Task, subtasks: Task[]): Task {
    return {
      ...original,
      subtasks,
      // Roll up complexity
      complexity: subtasks.reduce((sum, t) => sum + (t.complexity ?? 3), 0),
    };
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultDecomposer = new TaskDecomposer();
