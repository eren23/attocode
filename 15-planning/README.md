# Lesson 15: Planning & Decomposition

> Breaking complex goals into manageable, dependency-tracked tasks

## What You'll Learn

1. **Task Decomposition**: Breaking goals into smaller tasks
2. **Dependency Graphs**: Tracking which tasks depend on others
3. **Plan Validation**: Detecting cycles and invalid structures
4. **Execution Ordering**: Topological sorting for correct execution
5. **Progress Tracking**: Monitoring plan execution

## Why This Matters

Complex tasks like "refactor the authentication system" can't be done in one step. Planning enables:

- **Organization**: Clear structure for complex work
- **Parallelization**: Identify tasks that can run concurrently
- **Progress Tracking**: Know where you are in a long task
- **Failure Recovery**: Re-plan when things go wrong
- **Estimation**: Better predict time and resources

## Key Concepts

### Plan Structure

```typescript
interface Plan {
  id: string;
  goal: string;
  tasks: Task[];
  status: 'draft' | 'ready' | 'executing' | 'completed' | 'failed';
  estimatedSteps: number;
  actualSteps: number;
}

interface Task {
  id: string;
  description: string;
  status: TaskStatus;
  dependencies: string[];  // IDs of tasks that must complete first
  complexity?: number;     // 1-10 scale
  result?: TaskResult;
}
```

### Dependency Graph

```
Goal: Deploy application

    ┌─────────┐
    │  Setup  │  (no deps)
    └────┬────┘
         │
    ┌────▼────┐
    │  Build  │  (depends on Setup)
    └────┬────┘
         │
    ┌────┴────┐
    │         │
┌───▼───┐ ┌──▼──┐
│ Test  │ │Lint │  (both depend on Build)
└───┬───┘ └──┬──┘
    │        │
    └───┬────┘
        │
   ┌────▼────┐
   │ Deploy  │  (depends on Test AND Lint)
   └─────────┘
```

### Task Status Flow

```
pending ─► blocked ─► ready ─► in_progress ─► completed
                                     │
                                     ├───────► failed
                                     │
                                     └───────► skipped
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Plan, Task, and configuration types |
| `planner.ts` | Creates plans from goals |
| `decomposer.ts` | Breaks tasks into subtasks |
| `executor.ts` | Runs plans with dependency order |
| `validator.ts` | Validates plan structure |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:15
```

## Code Examples

### Creating a Plan

```typescript
import { Planner } from './planner.js';

const planner = new Planner({
  maxTasks: 20,
  validatePlans: true,
});

const plan = planner.createPlan(
  'Refactor the authentication module',
  {
    cwd: '/project',
    availableTools: ['read_file', 'write_file', 'search'],
  }
);

console.log('Tasks:', plan.tasks.length);
for (const task of plan.tasks) {
  console.log(`- ${task.description}`);
}
```

### Decomposing Tasks

```typescript
import { TaskDecomposer } from './decomposer.js';

const decomposer = new TaskDecomposer({
  strategy: 'hierarchical',
  maxSubtasks: 5,
});

const complexTask = {
  id: 'auth-1',
  description: 'Implement OAuth authentication',
  status: 'pending',
  dependencies: [],
  complexity: 8,
};

const result = decomposer.decompose(complexTask);

console.log('Strategy:', result.strategy);
for (const subtask of result.subtasks) {
  console.log(`- ${subtask.description}`);
}
```

### Validating Plans

```typescript
import { PlanValidator } from './validator.js';

const validator = new PlanValidator();
const result = validator.validate(plan);

if (!result.valid) {
  console.error('Validation errors:');
  for (const error of result.errors) {
    console.error(`  ${error.type}: ${error.message}`);
  }
}

if (result.warnings.length > 0) {
  console.warn('Warnings:', result.warnings);
}
```

### Executing Plans

```typescript
import { PlanExecutor } from './executor.js';

const executor = new PlanExecutor({
  concurrency: 2,  // Run up to 2 tasks at once
  stopOnFailure: false,
});

// Subscribe to events
executor.on((event) => {
  if (event.type === 'task.completed') {
    console.log(`✓ ${event.taskId} completed`);
  }
});

// Run the plan
const taskRunner = async (task) => {
  // Your task execution logic here
  return { success: true, output: 'Done', durationMs: 100 };
};

const executed = await executor.execute(plan, taskRunner);
console.log('Status:', executed.status);
```

## Decomposition Strategies

### Sequential

Tasks must be done in order:

```
Analyze → Plan → Implement → Test → Review
```

### Parallel

Independent tasks can run simultaneously:

```
┌──► Part 1 ──┐
│             │
├──► Part 2 ──┼──► Merge Results
│             │
└──► Part 3 ──┘
```

### Hierarchical

Complex tasks have nested subtasks:

```
Implement Feature
├── Analysis
│   ├── Review requirements
│   └── Identify dependencies
├── Implementation
│   ├── Write code
│   └── Add tests
└── Review
    └── Code review
```

## Validation Checks

The validator catches:

1. **Missing Dependencies**: Referencing non-existent tasks
2. **Circular Dependencies**: A → B → C → A
3. **Invalid Tasks**: Empty IDs or descriptions
4. **Unreachable Tasks**: Tasks blocked by cycles

## Topological Sort

Determines valid execution order:

```typescript
const sortResult = validator.topologicalSort(tasks);

if (sortResult.valid) {
  console.log('Execution order:', sortResult.order);
  // ['setup', 'config', 'build', 'test', 'deploy']
} else {
  console.log('Cycle detected:', sortResult.cycle);
}
```

## Parallel Execution Levels

Find tasks that can run concurrently:

```typescript
const levels = validator.findParallelizable(tasks);

// Level 0: [setup, config]     <- can run in parallel
// Level 1: [build]             <- must wait for level 0
// Level 2: [test, lint]        <- can run in parallel
// Level 3: [deploy]            <- must wait for level 2
```

## Re-Planning

When a task fails, revise the plan:

```typescript
if (task.status === 'failed') {
  const revisedPlan = planner.revisePlan(
    plan,
    'Task failed, adjusting approach'
  );

  // Re-execute with revised plan
  await executor.execute(revisedPlan, taskRunner);
}
```

## Best Practices

### Keep Tasks Atomic
Each task should do one thing well.

### Limit Dependencies
Tasks with 5+ dependencies are often too broad.

### Estimate Complexity
Helps with resource allocation and time estimation.

### Plan for Failure
Include fallback tasks or alternative approaches.

### Track Progress
Use events to monitor execution status.

## Next Steps

In **Lesson 16: Self-Reflection & Critique**, we'll add the ability for agents to evaluate and improve their own output. Combined with planning, this enables:

- Plan quality assessment
- Automatic plan revision
- Learning from failures
- Continuous improvement
