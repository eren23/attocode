/**
 * Lesson 15: Planner
 *
 * Creates plans from goals by breaking them into tasks.
 * This is where the "thinking" happens before execution.
 */

import type {
  Plan,
  Task,
  TaskStatus,
  PlannerConfig,
  PlanningContext,
  ValidationResult,
  ValidationError,
  DEFAULT_PLANNER_CONFIG,
} from './types.js';

// =============================================================================
// PLANNER
// =============================================================================

/**
 * Creates execution plans from goals.
 */
export class Planner {
  private config: PlannerConfig;

  constructor(config: Partial<PlannerConfig> = {}) {
    this.config = {
      maxTasks: config.maxTasks ?? 20,
      maxDepth: config.maxDepth ?? 3,
      validatePlans: config.validatePlans ?? true,
      estimateComplexity: config.estimateComplexity ?? true,
      defaultTimeout: config.defaultTimeout ?? 60000,
    };
  }

  // =============================================================================
  // PLAN CREATION
  // =============================================================================

  /**
   * Create a plan from a goal.
   *
   * In a real implementation, this would call an LLM to generate
   * the plan. Here we demonstrate the structure and concepts.
   *
   * @param goal - The goal to achieve
   * @param context - Planning context
   * @returns Generated plan
   */
  createPlan(goal: string, context: PlanningContext): Plan {
    // Generate unique ID
    const planId = `plan-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

    // Analyze the goal to determine tasks
    const tasks = this.analyzeGoal(goal, context);

    // Estimate total steps
    const estimatedSteps = this.estimateSteps(tasks);

    // Build the plan
    const plan: Plan = {
      id: planId,
      goal,
      tasks,
      status: 'draft',
      createdAt: new Date(),
      estimatedSteps,
      actualSteps: 0,
      metadata: {
        revision: 1,
        context: JSON.stringify(context),
      },
    };

    // Validate if configured
    if (this.config.validatePlans) {
      const validation = this.validatePlan(plan);
      if (!validation.valid) {
        throw new Error(
          `Invalid plan: ${validation.errors.map((e) => e.message).join(', ')}`
        );
      }
    }

    plan.status = 'ready';
    return plan;
  }

  /**
   * Analyze a goal and break it into tasks.
   */
  private analyzeGoal(goal: string, context: PlanningContext): Task[] {
    // This is a simplified heuristic-based analysis.
    // In production, you'd use an LLM to generate tasks.

    const tasks: Task[] = [];
    let taskCounter = 0;
    const generateId = () => `task-${++taskCounter}`;

    // Detect common patterns in goals
    const patterns = [
      { regex: /find|search|locate/i, type: 'search' },
      { regex: /read|get|fetch/i, type: 'read' },
      { regex: /write|create|add/i, type: 'write' },
      { regex: /modify|update|change|edit/i, type: 'modify' },
      { regex: /delete|remove/i, type: 'delete' },
      { regex: /analyze|review|check/i, type: 'analyze' },
      { regex: /test|verify/i, type: 'test' },
      { regex: /refactor|improve/i, type: 'refactor' },
    ];

    // Determine primary action type
    let primaryType = 'generic';
    for (const { regex, type } of patterns) {
      if (regex.test(goal)) {
        primaryType = type;
        break;
      }
    }

    // Generate tasks based on type
    switch (primaryType) {
      case 'search':
        tasks.push(
          this.createTask(generateId(), 'Identify search criteria from goal', []),
          this.createTask(generateId(), 'Search codebase for matches', [tasks[0]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Analyze search results', [tasks[1]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Compile findings', [tasks[2]?.id].filter(Boolean))
        );
        break;

      case 'read':
        tasks.push(
          this.createTask(generateId(), 'Locate target file(s)', []),
          this.createTask(generateId(), 'Read file contents', [tasks[0]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Extract relevant information', [tasks[1]?.id].filter(Boolean))
        );
        break;

      case 'write':
        tasks.push(
          this.createTask(generateId(), 'Determine file location and name', []),
          this.createTask(generateId(), 'Prepare content to write', [tasks[0]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Write the file', [tasks[1]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Verify file was created correctly', [tasks[2]?.id].filter(Boolean))
        );
        break;

      case 'modify':
        tasks.push(
          this.createTask(generateId(), 'Locate file(s) to modify', []),
          this.createTask(generateId(), 'Read current content', [tasks[0]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Plan modifications', [tasks[1]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Apply changes', [tasks[2]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Verify changes', [tasks[3]?.id].filter(Boolean))
        );
        break;

      case 'analyze':
        tasks.push(
          this.createTask(generateId(), 'Identify what to analyze', []),
          this.createTask(generateId(), 'Gather relevant information', [tasks[0]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Perform analysis', [tasks[1]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Summarize findings', [tasks[2]?.id].filter(Boolean))
        );
        break;

      case 'test':
        tasks.push(
          this.createTask(generateId(), 'Identify what to test', []),
          this.createTask(generateId(), 'Prepare test cases', [tasks[0]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Run tests', [tasks[1]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Analyze test results', [tasks[2]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Report findings', [tasks[3]?.id].filter(Boolean))
        );
        break;

      case 'refactor':
        tasks.push(
          this.createTask(generateId(), 'Understand current implementation', []),
          this.createTask(generateId(), 'Identify refactoring opportunities', [tasks[0]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Plan refactoring steps', [tasks[1]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Apply refactoring changes', [tasks[2]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Run tests to verify', [tasks[3]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Review final result', [tasks[4]?.id].filter(Boolean))
        );
        break;

      default:
        // Generic task breakdown
        tasks.push(
          this.createTask(generateId(), 'Understand the goal', []),
          this.createTask(generateId(), 'Gather necessary information', [tasks[0]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Execute main action', [tasks[1]?.id].filter(Boolean)),
          this.createTask(generateId(), 'Verify completion', [tasks[2]?.id].filter(Boolean))
        );
    }

    // Estimate complexity if configured
    if (this.config.estimateComplexity) {
      for (const task of tasks) {
        task.complexity = this.estimateTaskComplexity(task);
      }
    }

    return tasks;
  }

  /**
   * Create a task with default values.
   */
  private createTask(
    id: string,
    description: string,
    dependencies: string[]
  ): Task {
    return {
      id,
      description,
      status: dependencies.length > 0 ? 'blocked' : 'ready',
      dependencies,
    };
  }

  /**
   * Estimate complexity of a task.
   */
  private estimateTaskComplexity(task: Task): number {
    const description = task.description.toLowerCase();

    // Simple heuristics for complexity
    let complexity = 3; // Default medium

    if (description.includes('simple') || description.includes('basic')) {
      complexity = 1;
    } else if (description.includes('complex') || description.includes('refactor')) {
      complexity = 7;
    } else if (description.includes('understand') || description.includes('plan')) {
      complexity = 4;
    } else if (description.includes('verify') || description.includes('review')) {
      complexity = 2;
    }

    // Adjust based on dependencies
    complexity += Math.min(task.dependencies.length, 3);

    return Math.min(complexity, 10);
  }

  /**
   * Estimate total steps from tasks.
   */
  private estimateSteps(tasks: Task[]): number {
    let steps = tasks.length;

    // Add subtask steps
    for (const task of tasks) {
      if (task.subtasks) {
        steps += this.estimateSteps(task.subtasks);
      }
    }

    return steps;
  }

  // =============================================================================
  // PLAN REVISION
  // =============================================================================

  /**
   * Revise a plan based on feedback or failures.
   */
  revisePlan(plan: Plan, feedback: string): Plan {
    const revisedPlan: Plan = {
      ...plan,
      id: `${plan.id}-r${(plan.metadata?.revision ?? 0) + 1}`,
      status: 'revised',
      revisedAt: new Date(),
      metadata: {
        ...plan.metadata,
        revision: (plan.metadata?.revision ?? 0) + 1,
        reason: feedback,
      },
    };

    // Mark failed tasks for retry
    for (const task of revisedPlan.tasks) {
      if (task.status === 'failed') {
        task.status = 'pending';
        task.result = undefined;
      }
    }

    // Re-validate
    if (this.config.validatePlans) {
      this.validatePlan(revisedPlan);
    }

    revisedPlan.status = 'ready';
    return revisedPlan;
  }

  // =============================================================================
  // VALIDATION
  // =============================================================================

  /**
   * Validate a plan for correctness.
   */
  validatePlan(plan: Plan): ValidationResult {
    const errors: ValidationError[] = [];
    const warnings: string[] = [];
    const taskIds = new Set(plan.tasks.map((t) => t.id));

    // Check each task
    for (const task of plan.tasks) {
      // Check for missing dependencies
      for (const depId of task.dependencies) {
        if (!taskIds.has(depId)) {
          errors.push({
            type: 'missing_dependency',
            taskId: task.id,
            message: `Task "${task.id}" depends on non-existent task "${depId}"`,
          });
        }
      }

      // Check for self-dependency
      if (task.dependencies.includes(task.id)) {
        errors.push({
          type: 'circular_dependency',
          taskId: task.id,
          message: `Task "${task.id}" depends on itself`,
        });
      }

      // Check for empty description
      if (!task.description.trim()) {
        errors.push({
          type: 'invalid_task',
          taskId: task.id,
          message: `Task "${task.id}" has empty description`,
        });
      }
    }

    // Check for circular dependencies
    const cycle = this.detectCycle(plan.tasks);
    if (cycle) {
      errors.push({
        type: 'circular_dependency',
        taskId: cycle[0],
        message: `Circular dependency detected: ${cycle.join(' -> ')}`,
      });
    }

    // Check for unreachable tasks
    const reachable = this.findReachableTasks(plan.tasks);
    for (const task of plan.tasks) {
      if (!reachable.has(task.id) && task.dependencies.length > 0) {
        errors.push({
          type: 'unreachable_task',
          taskId: task.id,
          message: `Task "${task.id}" is unreachable (blocked by circular dependencies)`,
        });
      }
    }

    // Warnings
    if (plan.tasks.length > this.config.maxTasks) {
      warnings.push(
        `Plan has ${plan.tasks.length} tasks, exceeding recommended max of ${this.config.maxTasks}`
      );
    }

    return {
      valid: errors.length === 0,
      errors,
      warnings,
    };
  }

  /**
   * Detect circular dependencies.
   */
  private detectCycle(tasks: Task[]): string[] | null {
    const taskMap = new Map(tasks.map((t) => [t.id, t]));
    const visited = new Set<string>();
    const recStack = new Set<string>();
    const path: string[] = [];

    const dfs = (taskId: string): string[] | null => {
      visited.add(taskId);
      recStack.add(taskId);
      path.push(taskId);

      const task = taskMap.get(taskId);
      if (task) {
        for (const depId of task.dependencies) {
          if (!visited.has(depId)) {
            const cycle = dfs(depId);
            if (cycle) return cycle;
          } else if (recStack.has(depId)) {
            const cycleStart = path.indexOf(depId);
            return [...path.slice(cycleStart), depId];
          }
        }
      }

      path.pop();
      recStack.delete(taskId);
      return null;
    };

    for (const task of tasks) {
      if (!visited.has(task.id)) {
        const cycle = dfs(task.id);
        if (cycle) return cycle;
      }
    }

    return null;
  }

  /**
   * Find all reachable tasks (not blocked by cycles).
   */
  private findReachableTasks(tasks: Task[]): Set<string> {
    const reachable = new Set<string>();
    const taskMap = new Map(tasks.map((t) => [t.id, t]));

    // Start with tasks that have no dependencies
    const queue = tasks.filter((t) => t.dependencies.length === 0).map((t) => t.id);

    while (queue.length > 0) {
      const taskId = queue.shift()!;
      if (reachable.has(taskId)) continue;

      reachable.add(taskId);

      // Find tasks that depend on this one
      for (const task of tasks) {
        if (task.dependencies.includes(taskId)) {
          // Check if all dependencies are reachable
          if (task.dependencies.every((d) => reachable.has(d))) {
            queue.push(task.id);
          }
        }
      }
    }

    return reachable;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultPlanner = new Planner();
