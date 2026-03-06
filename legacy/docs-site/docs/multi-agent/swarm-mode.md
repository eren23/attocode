---
sidebar_position: 2
title: Swarm Mode
---

# Swarm Mode

Swarm mode coordinates multiple small specialist worker models under a single orchestrator. The `SwarmOrchestrator` (1,100 lines) delegates to three extracted modules: `swarm-lifecycle.ts` (1,069 lines), `swarm-execution.ts` (1,233 lines), and `swarm-recovery.ts` (668 lines).

## Five-Phase Pipeline

```mermaid
flowchart TB
    subgraph Phase1["1. DECOMPOSE"]
        SD[SmartDecomposer] --> subtasks[SmartSubtask[]]
    end

    subgraph Phase2["2. PLAN"]
        subtasks --> AC[Acceptance Criteria]
        AC --> TS[Topological Sort]
        TS --> waves[Wave Schedule]
    end

    subgraph Phase3["3. DISPATCH WAVES"]
        waves --> W1[Wave 1: parallel tasks]
        W1 --> review1[Wave Review]
        review1 --> W2[Wave 2: parallel tasks]
        W2 --> review2[Wave Review]
        review2 --> WN[Wave N...]
    end

    subgraph Phase4["4. REVIEW & FIXUP"]
        WN --> QG[QualityGate scoring]
        QG --> FC[FailureClassifier]
        FC -->|retry| Phase3
        FC -->|fixup| fixup[Generate fixup tasks]
        fixup --> Phase3
    end

    subgraph Phase5["5. VERIFY & SYNTHESIZE"]
        QG -->|all pass| VR[Integration Verification]
        VR --> RS[ResultSynthesizer]
        RS --> output[SwarmExecutionResult]
    end
```

### Phase 1: Decompose

The `SmartDecomposer` uses LLM-assisted semantic analysis to break the prompt into `SmartSubtask` objects with dependencies, complexity estimates (1-10), relevant files, and suggested agent roles. An emergency deterministic fallback produces scaffold/implement/verify tasks if the LLM call fails.

### Phase 2: Plan

The orchestrator generates acceptance criteria for each subtask and builds a `SwarmPlan`. The `DependencyAnalyzer` performs topological sort to produce `parallelGroups` -- sets of tasks that can run concurrently within a wave, while respecting inter-wave dependencies.

### Phase 3: Dispatch Waves

Waves execute sequentially. Within each wave, tasks are dispatched in parallel up to `maxConcurrency`. Each worker is a subagent spawned via the `SwarmWorkerPool`. After each wave completes, a wave review evaluates results and may generate fixup tasks injected into subsequent waves.

### Phase 4: Review and Fixup

The `QualityGate` scores each worker output 1-5. Scores below the threshold (default 3) trigger rejection. The `FailureClassifier` categorizes failures (timeout, rate-limit, policy-blocked, hollow completion, etc.) to determine retry strategy. Fixup tasks are generated for recoverable failures and added to the task queue.

### Phase 5: Verify and Synthesize

After all waves complete, integration verification runs optional bash commands (e.g., `npm test`) to validate the combined output. The `ResultSynthesizer` merges individual worker outputs into a single `SwarmExecutionResult` with summary, stats, and artifact inventory.

## Cross-Cutting Concerns

| Component | Purpose |
|-----------|---------|
| **SharedBlackboard** | Real-time finding sharing between workers (see [Shared State](./shared-state)) |
| **SharedBudgetPool** | Token budget partitioning -- 85% workers, 15% orchestrator reserve |
| **SharedEconomicsState** | Global doom loop detection across all workers |
| **EventBridge** | File-based streaming of swarm events for TUI display |
| **ModelHealthTracker** | Per-model success/failure tracking with automatic failover |
| **SwarmStateStore** | Checkpoint and resume support for long-running swarms |
| **SwarmThrottle** | Token bucket rate limiting (free tier: 2 concurrent, paid: 5) |

## SwarmConfig

Key configuration fields loaded from `.attocode/swarm.yaml` or CLI defaults:

```typescript
interface SwarmConfig {
  enabled: boolean;
  orchestratorModel: string;       // e.g. 'thudm/glm-4-32b'
  workers: SwarmWorkerSpec[];      // Worker model definitions
  maxConcurrency: number;          // Default: 5
  totalBudget: number;             // Default: 2,000,000 tokens
  maxCost: number;                 // Default: $1.00
  orchestratorReserveRatio: number; // Default: 0.15
  maxTokensPerWorker: number;      // Default: 20,000
  workerTimeout: number;           // Default: 120,000ms
  workerRetries: number;           // Max retry count per task
  qualityThreshold: number;        // Min score 1-5 (default: 3)
  partialDependencyThreshold: number; // Default: 0.5
  enablePersistence: boolean;      // Checkpoint support
  taskTypes: Record<string, TaskTypeConfig>; // Per-type overrides
}
```

## Recovery and Resilience

The `swarm-recovery.ts` module provides:

- **Circuit breaker**: Pauses all dispatch for 15s after 3 rate limits within 30s.
- **Adaptive stagger**: Increases delay between dispatches on rate limits, decreases on success.
- **Mid-swarm re-planning**: One-time re-decomposition when too many tasks fail.
- **Final rescue pass**: Last-resort attempt for critical failed tasks.
- **Per-model quality gate bypass**: Disables quality gate for models that consistently fail it (to avoid infinite retry loops).

## Key Files

| File | Lines | Description |
|------|-------|-------------|
| `src/integrations/swarm/swarm-orchestrator.ts` | ~1,100 | Main orchestrator class and `OrchestratorInternals` |
| `src/integrations/swarm/swarm-lifecycle.ts` | ~1,069 | Decomposition, planning, verification, synthesis |
| `src/integrations/swarm/swarm-execution.ts` | ~1,233 | Wave dispatch loop, task completion handling |
| `src/integrations/swarm/swarm-recovery.ts` | ~668 | Error recovery, circuit breaker, adaptive stagger |
| `src/integrations/swarm/types.ts` | -- | SwarmConfig, SwarmTask, TaskTypeConfig definitions |
| `src/integrations/swarm/swarm-helpers.ts` | -- | Hollow completion detection, utility functions |
| `src/integrations/swarm/swarm-events.ts` | -- | Event type definitions for TUI streaming |
| `src/integrations/swarm/swarm-state-store.ts` | -- | Checkpoint persistence for resume |
