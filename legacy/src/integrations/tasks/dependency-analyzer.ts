/**
 * Dependency Analyzer — Graph building, topological sort, and conflict detection.
 *
 * Extracted from smart-decomposer.ts (Phase 3e).
 * All functions are standalone and take subtasks as input.
 */

import type { SmartSubtask, DependencyGraph, ResourceConflict } from './smart-decomposer.js';

// =============================================================================
// DEPENDENCY GRAPH CONSTRUCTION
// =============================================================================

/**
 * Build a dependency graph from subtasks.
 */
export function buildDependencyGraph(subtasks: SmartSubtask[]): DependencyGraph {
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
  const cycles = detectCycles(subtasks, dependencies);

  // Calculate execution order (topological sort)
  const executionOrder = topologicalSort(subtasks, dependencies);

  // Calculate parallel groups
  const parallelGroups = calculateParallelGroups(subtasks, dependencies);

  return {
    dependencies,
    dependents,
    executionOrder,
    parallelGroups,
    cycles,
  };
}

// =============================================================================
// CYCLE DETECTION
// =============================================================================

/**
 * Detect cycles in dependency graph using DFS.
 */
export function detectCycles(
  subtasks: SmartSubtask[],
  dependencies: Map<string, string[]>,
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

// =============================================================================
// TOPOLOGICAL SORT
// =============================================================================

/**
 * Topological sort of tasks (Kahn-style via DFS post-order).
 */
export function topologicalSort(
  subtasks: SmartSubtask[],
  dependencies: Map<string, string[]>,
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

// =============================================================================
// PARALLEL GROUPS
// =============================================================================

/**
 * Calculate groups of tasks that can run in parallel.
 *
 * Tasks are grouped into waves: a task enters the earliest wave
 * where all its dependencies are already completed.
 */
export function calculateParallelGroups(
  subtasks: SmartSubtask[],
  dependencies: Map<string, string[]>,
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
      // No progress — circular dependency detected.
      // Force remaining tasks into sequential single-task groups
      // so they still reach the task queue instead of silently vanishing.
      for (const id of remaining) {
        groups.push([id]);
        completed.add(id);
      }
      remaining.clear();
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

// =============================================================================
// CONFLICT DETECTION
// =============================================================================

/**
 * Detect resource conflicts between subtasks.
 *
 * Finds write-write and read-write conflicts among tasks
 * that could potentially run in parallel.
 */
export function detectConflicts(subtasks: SmartSubtask[]): ResourceConflict[] {
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
      const parallelConflict = areInParallel(taskIds, subtasks);
      if (parallelConflict) {
        conflicts.push({
          resource,
          taskIds,
          type: 'write-write',
          severity: 'error',
          suggestion:
            `Tasks ${taskIds.join(', ')} both write to ${resource}. ` +
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
        if (writeId !== readId && areInParallel([writeId, readId], subtasks)) {
          conflicts.push({
            resource,
            taskIds: [writeId, readId],
            type: 'read-write',
            severity: 'warning',
            suggestion:
              `Task ${writeId} writes to ${resource} while ${readId} reads it. ` +
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
function areInParallel(taskIds: string[], subtasks: SmartSubtask[]): boolean {
  const taskMap = new Map(subtasks.map((s) => [s.id, s]));

  for (let i = 0; i < taskIds.length; i++) {
    for (let j = i + 1; j < taskIds.length; j++) {
      const task1 = taskMap.get(taskIds[i]);
      const task2 = taskMap.get(taskIds[j]);

      if (task1 && task2) {
        // Check if either depends on the other
        if (!task1.dependencies.includes(task2.id) && !task2.dependencies.includes(task1.id)) {
          return true; // Can run in parallel
        }
      }
    }
  }

  return false;
}
