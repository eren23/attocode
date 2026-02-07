# Architecture Deep Dive

This document covers the internal mechanics of swarm mode for power users who want to understand what's happening under the hood.

## Event System

The swarm orchestrator emits events throughout execution for observability. These events drive the TUI status panel, the web dashboard, and trace logging.

### Event Categories

**Lifecycle events** (start/complete):
- `swarm.start` — Swarm execution begins, includes task count, wave count, and config
- `swarm.complete` — Execution finished, includes final stats and errors
- `swarm.error` — Non-recoverable error with phase context

**Task events**:
- `swarm.tasks.loaded` — All tasks loaded with dependency graph
- `swarm.task.dispatched` — Task assigned to a worker model
- `swarm.task.completed` — Task finished (success or failure)
- `swarm.task.failed` — Task failed with attempt count and retry info
- `swarm.task.skipped` — Task skipped due to dependency failure

**Wave events**:
- `swarm.wave.start` — Wave begins, includes task count
- `swarm.wave.complete` — Wave finished with completed/failed/skipped counts

**Quality events**:
- `swarm.quality.rejected` — Quality gate rejected output (score 1-5)

**Budget events**:
- `swarm.budget.update` — Token and cost usage update
- `swarm.status` — Full status snapshot for TUI

**Planning/review events** (V2):
- `swarm.plan.complete` — Acceptance criteria and integration plan created
- `swarm.review.start` — Wave review begins
- `swarm.review.complete` — Wave review finished with assessment
- `swarm.verify.start` — Integration verification begins
- `swarm.verify.step` — Individual verification step result
- `swarm.verify.complete` — All verification steps done
- `swarm.fixup.spawned` — Fix-up task created by review

**Model health events**:
- `swarm.model.health` — Model health record update
- `swarm.model.failover` — Model switched due to rate limit
- `swarm.worker.stuck` — Worker detected as stuck (repeated tool calls)

**Persistence events**:
- `swarm.state.checkpoint` — State checkpointed after wave
- `swarm.state.resume` — Execution resumed from checkpoint

**Circuit breaker events**:
- `swarm.circuit.open` — Circuit breaker tripped, dispatch paused
- `swarm.circuit.closed` — Circuit breaker recovered, dispatch resumed

**Hierarchy events** (V3):
- `swarm.role.action` — Manager/judge role activity with model and action type

### Event Flow

```
swarm.start
  └─► swarm.tasks.loaded
       └─► swarm.wave.start (wave 1)
            ├─► swarm.task.dispatched (task A)
            ├─► swarm.task.dispatched (task B)
            ├─► swarm.role.action (judge, quality-gate)
            ├─► swarm.task.completed (task A)
            ├─► swarm.quality.rejected (task B)
            ├─► swarm.task.dispatched (task B, retry)
            ├─► swarm.task.completed (task B)
            ├─► swarm.budget.update
            └─► swarm.wave.complete
                 └─► swarm.role.action (manager, review)
                      └─► swarm.review.complete
                           └─► swarm.state.checkpoint
                                └─► swarm.wave.start (wave 2)
                                     └─► ... (repeat)
                                          └─► swarm.verify.start
                                               └─► swarm.verify.complete
                                                    └─► swarm.complete
```

## Budget Pool Math

### Split

The total token budget is split between orchestrator and workers:

```
Total Budget: 5,000,000 tokens (default)
  ├─ Orchestrator Reserve (15%): 750,000 tokens
  │   Used for: decomposition, planning, quality gates, wave review, synthesis
  └─ Worker Pool (85%): 4,250,000 tokens
      Shared among all workers with per-worker caps
```

The reserve ratio is configurable via `orchestratorReserveRatio` (default: 0.15).

### Per-Worker Caps

Each worker has a maximum token allowance:

```
maxTokensPerWorker: 50,000 (default)
```

Workers are terminated if they exceed their individual limit. The per-worker cost cap is calculated as:

```
maxCostPerWorker = maxCost / max(5, maxConcurrency * 3)
```

This ensures no single worker consumes a disproportionate share of the cost budget.

### Budget Tracking

Budget is tracked in real-time across waves. If early waves consume less than expected, the surplus carries forward to later waves. The `swarm.budget.update` event is emitted after each task completion.

## Circuit Breaker

The circuit breaker prevents cascading rate limit failures by pausing all dispatch when too many 429/402 errors occur in a short window.

### Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Window | 30 seconds | Time window for counting rate limits |
| Threshold | 3 | Number of rate limits to trigger the breaker |
| Pause | 15 seconds | How long to pause dispatch |

### State Machine

```
CLOSED (normal operation)
  │
  ├─ Rate limit hit → record timestamp
  │   └─ 3+ rate limits in 30s window?
  │       ├─ No  → stay CLOSED
  │       └─ Yes → transition to OPEN
  │
OPEN (dispatch paused)
  │
  └─ 15 seconds elapsed → transition to CLOSED
```

### Interaction with Throttle

The circuit breaker operates at the orchestrator level (dispatch decisions), while the throttle operates at the provider level (individual API calls). They complement each other:

- **Throttle**: Prevents sending requests too fast (proactive)
- **Circuit breaker**: Halts all dispatch after repeated failures (reactive)

When the circuit breaker is active, quality gates are also skipped to avoid adding more API calls.

## Token Bucket Throttling

The `SwarmThrottle` class implements a token bucket with minimum spacing and adaptive backoff.

### How It Works

```
Token Bucket:
  Capacity: maxConcurrent (2 for free, 5 for paid)
  Refill rate: refillRatePerSecond (0.5 for free, 2.0 for paid)
  Min spacing: minSpacingMs between consecutive requests (1500ms free, 200ms paid)

Request flow:
  1. acquire() called
  2. Wait in FIFO queue if no tokens available
  3. Wait for minSpacing since last acquire
  4. Consume one token
  5. Proceed with API call
```

Tokens refill passively based on elapsed wall-clock time. Long LLM calls naturally allow tokens to refill.

### Adaptive Backoff

On rate limit errors, the throttle backs off:

```
Level 0 (normal):     maxConcurrent=2, minSpacing=1500ms, refill=0.5/s
Level 1 (1st backoff): maxConcurrent=1, minSpacing=3000ms, refill=0.25/s
Level 2 (2nd backoff): maxConcurrent=1, minSpacing=5000ms, refill=0.125/s
Level 3 (max backoff): maxConcurrent=1, minSpacing=5000ms, refill=0.1/s
```

Recovery happens after 10 seconds of sustained success, stepping back one level at a time.

### Rate Limit Header Feedback

The throttle can proactively adjust based on rate limit headers from API responses:

- If `remainingRequests < 5`: preemptive backoff
- If `resetSeconds < 2` and `remainingRequests <= 1`: increase minSpacing to match reset

## State Persistence

### Checkpoint Format

After each wave, the orchestrator saves a checkpoint:

```typescript
interface SwarmCheckpoint {
  sessionId: string;           // Unique session identifier
  timestamp: number;           // Checkpoint time
  phase: string;               // Current pipeline phase
  plan?: SwarmPlan;            // Acceptance criteria + integration plan
  taskStates: Array<{          // Per-task state
    id: string;
    status: SwarmTaskStatus;
    result?: SwarmTaskResult;
    attempts: number;
    wave: number;
    assignedModel?: string;
  }>;
  waves: string[][];           // Wave composition (task IDs per wave)
  currentWave: number;         // Next wave to execute
  stats: {                     // Cumulative stats
    totalTokens: number;
    totalCost: number;
    qualityRejections: number;
    retries: number;
  };
  modelHealth: ModelHealthRecord[];  // Per-model health state
  decisions: OrchestratorDecision[]; // Decision log
  errors: SwarmError[];              // Error log
}
```

### Storage Location

Checkpoints are stored in the `stateDir` directory (default: `.agent/swarm-state/`). Each checkpoint is a JSON file named by session ID and wave.

### Resume Flow

When resuming with `--swarm-resume <session-id>`:

1. Load the latest checkpoint for the given session
2. Restore the plan, task states, model health, and stats
3. Restore the task queue to the saved wave position
4. Continue executing from the next incomplete wave
5. Run verification and synthesis as normal

If no checkpoint is found, execution starts fresh.

## Event Bridge Pipeline

Events flow from the orchestrator to external consumers through a pipeline:

```
SwarmOrchestrator
  └─► emit(event)
       └─► Event Listeners (in-process)
            ├─► SwarmEventBridge → filesystem (JSONL)
            │                       └─► swarm-watcher (file polling)
            │                            └─► SSE endpoint (/api/swarm/live)
            │                                 └─► Dashboard (useSwarmStream hook)
            └─► TUI SwarmStatusPanel (direct subscription)
```

1. **Orchestrator** emits typed events
2. **Event Bridge** serializes events to JSONL on disk
3. **Swarm Watcher** (dashboard backend) polls the JSONL file for new events
4. **SSE Endpoint** streams events to connected dashboard clients
5. **Dashboard** processes events into visual state (DAG, timeline, gauges)

This architecture means the dashboard works even if started after swarm execution begins — it catches up by reading the JSONL file.

## Orchestrator Decision Logging

Every significant decision is logged with reasoning:

```typescript
interface OrchestratorDecision {
  timestamp: number;
  phase: string;        // 'planning', 'review', 'failover', 'circuit-breaker', etc.
  decision: string;     // What was decided
  reasoning: string;    // Why
}
```

Decisions are:
- Included in checkpoints for resume debugging
- Emitted as `swarm.orchestrator.decision` events
- Visible in the dashboard event feed

## Key Source Files

| File | Purpose |
|------|---------|
| `src/integrations/swarm/swarm-orchestrator.ts` | Main orchestration loop |
| `src/integrations/swarm/types.ts` | All type definitions and defaults |
| `src/integrations/swarm/task-queue.ts` | Wave-based task scheduling |
| `src/integrations/swarm/worker-pool.ts` | Concurrent worker dispatch |
| `src/integrations/swarm/swarm-budget.ts` | Budget pool management |
| `src/integrations/swarm/swarm-quality-gate.ts` | Output quality evaluation |
| `src/integrations/swarm/model-selector.ts` | Auto-detection and health tracking |
| `src/integrations/swarm/request-throttle.ts` | Token bucket rate limiting |
| `src/integrations/swarm/swarm-state-store.ts` | Checkpoint persistence |
| `src/integrations/swarm/swarm-events.ts` | Event type definitions |
| `src/integrations/swarm/swarm-event-bridge.ts` | Event → filesystem bridge |
| `src/integrations/swarm/swarm-config-loader.ts` | YAML config parsing and merge |
