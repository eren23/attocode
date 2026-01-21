/**
 * Lesson 15: Planning & Decomposition
 *
 * This lesson demonstrates how to break complex tasks into
 * smaller, manageable steps with dependency tracking.
 *
 * Key concepts:
 * 1. Task decomposition strategies
 * 2. Dependency graphs
 * 3. Plan validation
 * 4. Execution ordering
 *
 * Run: npm run lesson:15
 */

import chalk from 'chalk';
import { Planner } from './planner.js';
import { TaskDecomposer } from './decomposer.js';
import { PlanExecutor, createMockRunner } from './executor.js';
import { PlanValidator } from './validator.js';
import type { Plan, Task, PlanningContext, ExecutionProgress } from './types.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 15: Planning & Decomposition                  ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: UNDERSTANDING PLANS
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Understanding Plans'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nA plan consists of:'));
console.log(chalk.gray(`
  Plan {
    id: "plan-123"
    goal: "Refactor authentication module"
    tasks: [
      { id: "task-1", description: "Analyze current code", dependencies: [] }
      { id: "task-2", description: "Design new structure", dependencies: ["task-1"] }
      { id: "task-3", description: "Implement changes", dependencies: ["task-2"] }
      { id: "task-4", description: "Run tests", dependencies: ["task-3"] }
    ]
    status: "ready" | "executing" | "completed" | "failed"
  }
`));

console.log(chalk.white('\nTask statuses:'));
console.log(chalk.gray('  pending   - Not yet started'));
console.log(chalk.gray('  blocked   - Waiting on dependencies'));
console.log(chalk.gray('  ready     - Dependencies met, can start'));
console.log(chalk.gray('  in_progress - Currently executing'));
console.log(chalk.gray('  completed - Successfully finished'));
console.log(chalk.gray('  failed    - Failed to complete'));
console.log(chalk.gray('  skipped   - Skipped due to upstream failure'));

// =============================================================================
// PART 2: CREATING A PLAN
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Creating a Plan'));
console.log(chalk.gray('─'.repeat(60)));

const planner = new Planner({
  maxTasks: 20,
  validatePlans: true,
  estimateComplexity: true,
});

const context: PlanningContext = {
  cwd: '/project',
  availableTools: ['read_file', 'write_file', 'search', 'bash'],
};

const goals = [
  'Search for all TODO comments in the codebase',
  'Refactor the authentication module',
  'Analyze the performance of API endpoints',
];

for (const goal of goals) {
  console.log(chalk.green(`\nGoal: "${goal}"`));

  const plan = planner.createPlan(goal, context);

  console.log(chalk.white(`  Plan ID: ${plan.id}`));
  console.log(chalk.white(`  Tasks: ${plan.tasks.length}`));
  console.log(chalk.white(`  Estimated steps: ${plan.estimatedSteps}`));

  console.log(chalk.gray('\n  Task breakdown:'));
  for (const task of plan.tasks) {
    const deps = task.dependencies.length > 0
      ? ` (depends on: ${task.dependencies.join(', ')})`
      : ' (no dependencies)';
    const complexity = task.complexity ? ` [complexity: ${task.complexity}]` : '';
    console.log(chalk.gray(`    ${task.id}: ${task.description}${deps}${complexity}`));
  }
}

// =============================================================================
// PART 3: TASK DECOMPOSITION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Task Decomposition'));
console.log(chalk.gray('─'.repeat(60)));

const decomposer = new TaskDecomposer({
  granularity: 5,
  maxSubtasks: 5,
});

const complexTask: Task = {
  id: 'complex-1',
  description: 'Implement user authentication with OAuth support',
  status: 'pending',
  dependencies: [],
  complexity: 8,
};

console.log(chalk.green(`\nDecomposing: "${complexTask.description}"`));
console.log(chalk.gray(`  Original complexity: ${complexTask.complexity}`));

const decomposed = decomposer.decompose(complexTask);

console.log(chalk.white(`\n  Strategy used: ${decomposed.strategy}`));
console.log(chalk.white(`  Subtasks: ${decomposed.subtasks.length}`));

console.log(chalk.gray('\n  Subtask breakdown:'));
for (const subtask of decomposed.subtasks) {
  const deps = subtask.dependencies.length > 0
    ? ` -> ${subtask.dependencies.join(', ')}`
    : '';
  console.log(chalk.gray(`    ${subtask.id}: ${subtask.description}${deps}`));
}

// =============================================================================
// PART 4: PLAN VALIDATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Plan Validation'));
console.log(chalk.gray('─'.repeat(60)));

const validator = new PlanValidator();

// Valid plan
const validPlan: Plan = {
  id: 'valid-plan',
  goal: 'Test validation',
  tasks: [
    { id: 't1', description: 'Task 1', status: 'pending', dependencies: [] },
    { id: 't2', description: 'Task 2', status: 'pending', dependencies: ['t1'] },
    { id: 't3', description: 'Task 3', status: 'pending', dependencies: ['t1'] },
    { id: 't4', description: 'Task 4', status: 'pending', dependencies: ['t2', 't3'] },
  ],
  status: 'draft',
  createdAt: new Date(),
  estimatedSteps: 4,
  actualSteps: 0,
};

console.log(chalk.green('\nValidating well-formed plan:'));
const validResult = validator.validate(validPlan);
console.log(chalk.white(`  Valid: ${validResult.valid ? chalk.green('Yes') : chalk.red('No')}`));
console.log(chalk.gray(`  Errors: ${validResult.errors.length}`));
console.log(chalk.gray(`  Warnings: ${validResult.warnings.length}`));

// Invalid plan with cycle
const invalidPlan: Plan = {
  id: 'invalid-plan',
  goal: 'Test cycle detection',
  tasks: [
    { id: 't1', description: 'Task 1', status: 'pending', dependencies: ['t3'] }, // Cycle!
    { id: 't2', description: 'Task 2', status: 'pending', dependencies: ['t1'] },
    { id: 't3', description: 'Task 3', status: 'pending', dependencies: ['t2'] },
  ],
  status: 'draft',
  createdAt: new Date(),
  estimatedSteps: 3,
  actualSteps: 0,
};

console.log(chalk.green('\nValidating plan with circular dependency:'));
const invalidResult = validator.validate(invalidPlan);
console.log(chalk.white(`  Valid: ${invalidResult.valid ? chalk.green('Yes') : chalk.red('No')}`));
if (invalidResult.errors.length > 0) {
  console.log(chalk.red(`  Error: ${invalidResult.errors[0].message}`));
}

// =============================================================================
// PART 5: TOPOLOGICAL SORTING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Execution Order (Topological Sort)'));
console.log(chalk.gray('─'.repeat(60)));

const sortResult = validator.topologicalSort(validPlan.tasks);

console.log(chalk.green('\nValid plan execution order:'));
if (sortResult.valid && sortResult.order) {
  console.log(chalk.white(`  ${sortResult.order.join(' -> ')}`));
} else {
  console.log(chalk.red(`  Cannot sort: cycle at ${sortResult.cycle?.join(' -> ')}`));
}

// Find parallelizable tasks
const parallelGroups = validator.findParallelizable(validPlan.tasks);
console.log(chalk.green('\nTasks that can run in parallel (by level):'));
for (let i = 0; i < parallelGroups.length; i++) {
  console.log(chalk.gray(`  Level ${i}: [${parallelGroups[i].join(', ')}]`));
}

// =============================================================================
// PART 6: PLAN EXECUTION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Plan Execution'));
console.log(chalk.gray('─'.repeat(60)));

const executor = new PlanExecutor({
  concurrency: 1,
  stopOnFailure: false,
  timeout: 5000,
});

// Subscribe to events
executor.on((event) => {
  switch (event.type) {
    case 'task.started':
      console.log(chalk.blue(`  ▶ Started: ${event.taskId}`));
      break;
    case 'task.completed':
      console.log(chalk.green(`  ✓ Completed: ${event.taskId} (${event.result.durationMs.toFixed(0)}ms)`));
      break;
    case 'task.failed':
      console.log(chalk.red(`  ✗ Failed: ${event.taskId}`));
      break;
    case 'task.skipped':
      console.log(chalk.yellow(`  ⊘ Skipped: ${event.taskId} (${event.reason})`));
      break;
  }
});

// Create a test plan
const executionPlan: Plan = {
  id: 'exec-plan',
  goal: 'Test execution',
  tasks: [
    { id: 'e1', description: 'First task', status: 'ready', dependencies: [] },
    { id: 'e2', description: 'Second task', status: 'blocked', dependencies: ['e1'] },
    { id: 'e3', description: 'Third task', status: 'blocked', dependencies: ['e2'] },
  ],
  status: 'ready',
  createdAt: new Date(),
  estimatedSteps: 3,
  actualSteps: 0,
};

console.log(chalk.green('\nExecuting plan...'));
const mockRunner = createMockRunner(50, 0); // 50ms delay, 0% failure rate
const executedPlan = await executor.execute(executionPlan, mockRunner);

console.log(chalk.white(`\nExecution complete!`));
console.log(chalk.gray(`  Status: ${executedPlan.status}`));
console.log(chalk.gray(`  Steps taken: ${executedPlan.actualSteps}`));

const progress = executor.getProgress(executedPlan);
console.log(chalk.gray(`  Progress: ${progress.completed}/${progress.total} tasks (${progress.percentage}%)`));

// =============================================================================
// PART 7: DEPENDENCY VISUALIZATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Dependency Visualization'));
console.log(chalk.gray('─'.repeat(60)));

const complexPlan: Plan = {
  id: 'viz-plan',
  goal: 'Demonstrate dependencies',
  tasks: [
    { id: 'A', description: 'Setup', status: 'pending', dependencies: [] },
    { id: 'B', description: 'Config', status: 'pending', dependencies: [] },
    { id: 'C', description: 'Build', status: 'pending', dependencies: ['A', 'B'] },
    { id: 'D', description: 'Test', status: 'pending', dependencies: ['C'] },
    { id: 'E', description: 'Lint', status: 'pending', dependencies: ['C'] },
    { id: 'F', description: 'Deploy', status: 'pending', dependencies: ['D', 'E'] },
  ],
  status: 'ready',
  createdAt: new Date(),
  estimatedSteps: 6,
  actualSteps: 0,
};

console.log(chalk.green('\nDependency graph:'));
console.log(chalk.gray(`
    A ──┐
        ├──► C ──┬──► D ──┐
    B ──┘       │        ├──► F
                └──► E ──┘
`));

console.log(chalk.white('Execution levels:'));
const levels = validator.findParallelizable(complexPlan.tasks);
for (let i = 0; i < levels.length; i++) {
  const tasksAtLevel = levels[i].map((id) =>
    complexPlan.tasks.find((t) => t.id === id)?.description
  );
  console.log(chalk.gray(`  ${i + 1}. [${tasksAtLevel.join(', ')}]`));
}

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. Plans break goals into tasks with dependencies'));
console.log(chalk.gray('  2. Tasks can be decomposed into smaller subtasks'));
console.log(chalk.gray('  3. Validation catches cycles and invalid references'));
console.log(chalk.gray('  4. Topological sort determines execution order'));
console.log(chalk.gray('  5. Parallel execution is possible at each level'));
console.log();
console.log(chalk.white('Planning benefits:'));
console.log(chalk.gray('  - Organized approach to complex tasks'));
console.log(chalk.gray('  - Clear dependency tracking'));
console.log(chalk.gray('  - Parallel execution opportunities'));
console.log(chalk.gray('  - Progress visibility'));
console.log(chalk.gray('  - Failure recovery paths'));
console.log();
console.log(chalk.bold.green('Next: Lesson 16 - Self-Reflection & Critique'));
console.log(chalk.gray('Make agents that improve their own output!'));
console.log();
