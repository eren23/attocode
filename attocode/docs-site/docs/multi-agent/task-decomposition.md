---
sidebar_position: 3
title: Task Decomposition
---

# Task Decomposition

Task decomposition breaks a high-level prompt into structured subtasks with dependencies, complexity estimates, and resource annotations. The system is split across three modules: `SmartDecomposer` (990 lines), `task-splitter.ts` (560 lines), and `dependency-analyzer.ts` (288 lines).

## SmartDecomposer

The `SmartDecomposer` is the entry point. It uses LLM-assisted semantic analysis rather than keyword-based splitting, which means it understands that "implement auth" implicitly requires "design schema" even if the user never mentioned it.

```mermaid
flowchart LR
    prompt[User Prompt] --> DP[createDecompositionPrompt]
    DP --> LLM[LLM Call]
    LLM --> parse[parseDecompositionResponse]
    parse --> validate[validateDecomposition]
    validate --> graph[buildDependencyGraph]
    graph --> result[SmartDecompositionResult]
```

### SmartSubtask

Each subtask carries rich metadata:

```typescript
interface SmartSubtask {
  id: string;
  description: string;
  status: SubtaskStatus;       // pending | ready | blocked | in_progress | completed | failed | skipped
  dependencies: string[];      // IDs of prerequisite tasks
  complexity: number;          // 1-10 scale
  estimatedTokens?: number;    // Budget estimate
  relevantFiles?: string[];    // Files likely involved
  relevantSymbols?: string[];  // Functions/classes involved
  type: SubtaskType;           // research | analysis | design | implement | test | ...
  parallelizable: boolean;
  modifies?: string[];         // Resources this task writes
  reads?: string[];            // Resources this task reads
  suggestedRole?: string;      // Preferred worker type
}
```

### Built-in Task Types

| Type | Capability | Requires Tool Calls | Prompt Template |
|------|-----------|---------------------|-----------------|
| `research` | research | No | research |
| `analysis` | research | No | research |
| `design` | research | No | research |
| `implement` | code | Yes | code |
| `test` | test | Yes | code |
| `refactor` | code | Yes | code |
| `review` | review | No | research |
| `document` | document | Yes | document |
| `integrate` | code | Yes | code |
| `deploy` | code | Yes | code |
| `merge` | write | No | synthesis |

Custom types can be added via `swarmConfig.taskTypes` and fall back to `implement` defaults.

## Task Splitter

The `task-splitter.ts` module handles the LLM interaction:

1. **Prompt construction** (`createDecompositionPrompt`): Builds a structured prompt with the task description, codebase context (repo map, top files), and a JSON schema for the expected output.
2. **Response parsing** (`parseDecompositionResponse`): Extracts JSON from the LLM response with fallback to natural language extraction via `extractSubtasksFromNaturalLanguage`.
3. **Validation** (`validateDecomposition`): Ensures all dependency references are valid, complexity values are in range, and IDs are unique. Repairs common JSON issues via `repairJSON`.

## Dependency Analyzer

The `dependency-analyzer.ts` module provides graph algorithms:

### Core Functions

| Function | Purpose |
|----------|---------|
| `buildDependencyGraph` | Constructs the full dependency graph from subtasks |
| `detectCycles` | DFS-based cycle detection; returns cycle paths |
| `topologicalSort` | Kahn's algorithm for execution ordering |
| `calculateParallelGroups` | Groups tasks into waves where all tasks in a wave can run concurrently |
| `detectConflicts` | Identifies resource contention (two tasks modifying the same file) |

### Execution Recommendation

The analyzer produces an `ExecutionRecommendation` based on the dependency structure:

- **Sequential**: High dependency density, nearly linear chain.
- **Parallel**: Many independent tasks with few cross-dependencies.
- **Multi-agent**: Complex graph with multiple parallel groups and resource conflicts.

## Foundation Tasks

Tasks with 3 or more dependents are marked `isFoundation = true`. Foundation tasks receive special treatment:

| Property | Foundation | Regular |
|----------|-----------|---------|
| Token budget | Max of `tokenBudgetRange` | Scaled by complexity |
| Timeout | 2.5x base timeout | 1x base timeout |
| Retries | +1 extra retry | Standard count |
| Quality threshold | -1 (relaxed) | Standard threshold |

This reduces cascade failures: if a foundation task fails, all downstream tasks are blocked.

## Partial Dependency Threshold

When a task has some failed dependencies but others succeeded, the `partialDependencyThreshold` (default 0.5) determines whether to proceed. If the ratio of completed dependencies exceeds the threshold, the task runs with partial context rather than being skipped entirely.

## Resource Contention

The decomposer detects when multiple tasks modify the same files. Conflicting tasks are placed in separate waves to avoid concurrent write conflicts. The `ResourceConflict` type records which tasks conflict and on which resources.

## Key Files

| File | Lines | Description |
|------|-------|-------------|
| `src/integrations/tasks/smart-decomposer.ts` | ~990 | Core class, types, heuristics, factory |
| `src/integrations/tasks/task-splitter.ts` | ~560 | LLM prompt construction and response parsing |
| `src/integrations/tasks/dependency-analyzer.ts` | ~288 | Graph building, topological sort, conflict detection |
