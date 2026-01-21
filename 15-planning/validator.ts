/**
 * Lesson 15: Plan Validator
 *
 * Validates plans for correctness before execution.
 * Checks for cycles, missing dependencies, and other issues.
 */

import type {
  Plan,
  Task,
  ValidationResult,
  ValidationError,
  DependencyGraph,
  TopologicalSortResult,
} from './types.js';

// =============================================================================
// PLAN VALIDATOR
// =============================================================================

/**
 * Validates plans for correctness.
 */
export class PlanValidator {
  /**
   * Validate a plan.
   */
  validate(plan: Plan): ValidationResult {
    const errors: ValidationError[] = [];
    const warnings: string[] = [];

    // Build dependency graph
    const graph = this.buildGraph(plan.tasks);

    // Check for missing dependencies
    errors.push(...this.checkMissingDependencies(plan.tasks, graph));

    // Check for circular dependencies
    const cycle = this.detectCycle(graph);
    if (cycle) {
      errors.push({
        type: 'circular_dependency',
        taskId: cycle[0],
        message: `Circular dependency: ${cycle.join(' -> ')}`,
      });
    }

    // Check for invalid tasks
    errors.push(...this.checkInvalidTasks(plan.tasks));

    // Check for unreachable tasks
    errors.push(...this.checkUnreachableTasks(plan.tasks, graph));

    // Warnings
    warnings.push(...this.getWarnings(plan));

    return {
      valid: errors.length === 0,
      errors,
      warnings,
    };
  }

  // =============================================================================
  // GRAPH BUILDING
  // =============================================================================

  /**
   * Build a dependency graph from tasks.
   */
  buildGraph(tasks: Task[]): DependencyGraph {
    const nodes = new Set(tasks.map((t) => t.id));
    const edges = new Map<string, Set<string>>();
    const reverseEdges = new Map<string, Set<string>>();

    for (const task of tasks) {
      edges.set(task.id, new Set());
      reverseEdges.set(task.id, new Set());
    }

    for (const task of tasks) {
      for (const depId of task.dependencies) {
        // Edge from dependency to task (task depends on depId)
        if (edges.has(depId)) {
          edges.get(depId)!.add(task.id);
        }
        reverseEdges.get(task.id)!.add(depId);
      }
    }

    return { nodes, edges, reverseEdges };
  }

  // =============================================================================
  // VALIDATION CHECKS
  // =============================================================================

  /**
   * Check for missing dependencies.
   */
  private checkMissingDependencies(
    tasks: Task[],
    graph: DependencyGraph
  ): ValidationError[] {
    const errors: ValidationError[] = [];

    for (const task of tasks) {
      for (const depId of task.dependencies) {
        if (!graph.nodes.has(depId)) {
          errors.push({
            type: 'missing_dependency',
            taskId: task.id,
            message: `Task "${task.id}" depends on non-existent task "${depId}"`,
          });
        }
      }
    }

    return errors;
  }

  /**
   * Check for invalid tasks.
   */
  private checkInvalidTasks(tasks: Task[]): ValidationError[] {
    const errors: ValidationError[] = [];

    for (const task of tasks) {
      if (!task.id) {
        errors.push({
          type: 'invalid_task',
          taskId: 'unknown',
          message: 'Task has no ID',
        });
      }

      if (!task.description || !task.description.trim()) {
        errors.push({
          type: 'invalid_task',
          taskId: task.id,
          message: `Task "${task.id}" has empty description`,
        });
      }

      if (task.dependencies.includes(task.id)) {
        errors.push({
          type: 'circular_dependency',
          taskId: task.id,
          message: `Task "${task.id}" depends on itself`,
        });
      }
    }

    return errors;
  }

  /**
   * Check for unreachable tasks.
   */
  private checkUnreachableTasks(
    tasks: Task[],
    graph: DependencyGraph
  ): ValidationError[] {
    const errors: ValidationError[] = [];

    // Tasks with no dependencies are always reachable
    const reachable = new Set(
      tasks.filter((t) => t.dependencies.length === 0).map((t) => t.id)
    );

    // BFS to find all reachable tasks
    let changed = true;
    while (changed) {
      changed = false;
      for (const task of tasks) {
        if (reachable.has(task.id)) continue;

        // Task is reachable if all dependencies are reachable
        if (task.dependencies.every((d) => reachable.has(d))) {
          reachable.add(task.id);
          changed = true;
        }
      }
    }

    // Find unreachable tasks
    for (const task of tasks) {
      if (!reachable.has(task.id)) {
        errors.push({
          type: 'unreachable_task',
          taskId: task.id,
          message: `Task "${task.id}" is unreachable`,
        });
      }
    }

    return errors;
  }

  /**
   * Generate warnings for potential issues.
   */
  private getWarnings(plan: Plan): string[] {
    const warnings: string[] = [];

    if (plan.tasks.length === 0) {
      warnings.push('Plan has no tasks');
    }

    if (plan.tasks.length > 50) {
      warnings.push(`Large plan with ${plan.tasks.length} tasks may be hard to track`);
    }

    // Check for long dependency chains
    const maxChain = this.findLongestChain(plan.tasks);
    if (maxChain > 10) {
      warnings.push(`Long dependency chain (${maxChain} tasks) may cause delays`);
    }

    // Check for tasks with many dependencies
    for (const task of plan.tasks) {
      if (task.dependencies.length > 5) {
        warnings.push(`Task "${task.id}" has ${task.dependencies.length} dependencies`);
      }
    }

    return warnings;
  }

  // =============================================================================
  // CYCLE DETECTION
  // =============================================================================

  /**
   * Detect cycles in the dependency graph.
   */
  detectCycle(graph: DependencyGraph): string[] | null {
    const visited = new Set<string>();
    const recStack = new Set<string>();
    const path: string[] = [];

    const dfs = (node: string): string[] | null => {
      visited.add(node);
      recStack.add(node);
      path.push(node);

      const neighbors = graph.edges.get(node) ?? new Set();
      for (const neighbor of neighbors) {
        if (!visited.has(neighbor)) {
          const cycle = dfs(neighbor);
          if (cycle) return cycle;
        } else if (recStack.has(neighbor)) {
          const cycleStart = path.indexOf(neighbor);
          return [...path.slice(cycleStart), neighbor];
        }
      }

      path.pop();
      recStack.delete(node);
      return null;
    };

    for (const node of graph.nodes) {
      if (!visited.has(node)) {
        const cycle = dfs(node);
        if (cycle) return cycle;
      }
    }

    return null;
  }

  // =============================================================================
  // TOPOLOGICAL SORT
  // =============================================================================

  /**
   * Topologically sort tasks.
   */
  topologicalSort(tasks: Task[]): TopologicalSortResult {
    const graph = this.buildGraph(tasks);
    const cycle = this.detectCycle(graph);

    if (cycle) {
      return { valid: false, cycle };
    }

    const sorted: string[] = [];
    const visited = new Set<string>();

    const dfs = (node: string) => {
      if (visited.has(node)) return;
      visited.add(node);

      // Visit dependencies first
      const task = tasks.find((t) => t.id === node);
      if (task) {
        for (const dep of task.dependencies) {
          dfs(dep);
        }
      }

      sorted.push(node);
    };

    for (const task of tasks) {
      dfs(task.id);
    }

    return { valid: true, order: sorted };
  }

  // =============================================================================
  // ANALYSIS
  // =============================================================================

  /**
   * Find the longest dependency chain.
   */
  findLongestChain(tasks: Task[]): number {
    const taskMap = new Map(tasks.map((t) => [t.id, t]));
    const memo = new Map<string, number>();
    const visiting = new Set<string>();

    const getChainLength = (taskId: string): number => {
      if (memo.has(taskId)) return memo.get(taskId)!;

      // Detect cycle - return 0 to avoid infinite recursion
      if (visiting.has(taskId)) return 0;

      const task = taskMap.get(taskId);
      if (!task || task.dependencies.length === 0) {
        memo.set(taskId, 1);
        return 1;
      }

      visiting.add(taskId);

      let maxDep = 0;
      for (const depId of task.dependencies) {
        maxDep = Math.max(maxDep, getChainLength(depId));
      }

      visiting.delete(taskId);

      const length = maxDep + 1;
      memo.set(taskId, length);
      return length;
    };

    let max = 0;
    for (const task of tasks) {
      max = Math.max(max, getChainLength(task.id));
    }

    return max;
  }

  /**
   * Find tasks that can be parallelized.
   */
  findParallelizable(tasks: Task[]): string[][] {
    const sortResult = this.topologicalSort(tasks);
    if (!sortResult.valid || !sortResult.order) {
      return [];
    }

    const taskMap = new Map(tasks.map((t) => [t.id, t]));
    const levels: string[][] = [];
    const taskLevel = new Map<string, number>();

    for (const taskId of sortResult.order) {
      const task = taskMap.get(taskId)!;
      let level = 0;

      for (const depId of task.dependencies) {
        const depLevel = taskLevel.get(depId) ?? 0;
        level = Math.max(level, depLevel + 1);
      }

      taskLevel.set(taskId, level);

      while (levels.length <= level) {
        levels.push([]);
      }
      levels[level].push(taskId);
    }

    return levels;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultValidator = new PlanValidator();
