# Isolation System

Filesystem isolation for running multiple eval tasks in parallel without cross-task contamination.

## Quick Start: 3 Tasks in Parallel

```bash
# Using convenience script (recommended)
./scripts/eval-golden.sh --quick

# Or manually (default model: z-ai/glm-4.7 via openrouter)
npm run eval -- run \
  --dataset golden \
  --task-ids fix-typo-001,fix-import-001,fix-type-error-001 \
  --parallelism 3 \
  --isolation worktree
```

This creates 3 git worktrees, runs an agent in each one simultaneously, grades results, and cleans up.

## Architecture

```
BatchOrchestrator
  |
  +-- IsolationProvider (interface)
  |     |
  |     +-- WorktreeProvider    <-- git worktree per task (primary)
  |     +-- DockerProvider      <-- container per task (stub, future)
  |     +-- NoneProvider        <-- no isolation (legacy sequential)
  |
  +-- PoolManager<T>            <-- generic warm pool
  |     acquire() -> slot
  |     release() -> recycle
  |     warmup()  -> pre-create slots
  |
  +-- Dispatch loop (Promise.race)
        fill slots up to --parallelism
        await fastest completion
        recycle slot, start next task
```

## Components

### IsolationProvider (interface)

```typescript
interface IsolationProvider {
  init(tasks: TaskDescriptor[]): Promise<void>;
  acquire(task: TaskDescriptor): Promise<TaskEnvironment>;
  reset(env: TaskEnvironment): Promise<void>;
  release(env: TaskEnvironment): Promise<void>;
  destroyAll(): Promise<void>;
  getStats(): PoolStats;
}
```

Every provider follows the same lifecycle:
1. `init()` — set up shared resources (bare clones, Docker images, etc.)
2. `acquire()` — get an isolated workspace for a task
3. Agent runs inside the workspace (`workingDirectory` on the agent config)
4. `reset()` + `release()` — clean the workspace and return it to the pool
5. `destroyAll()` — tear down everything (called on completion or SIGINT)

### WorktreeProvider

Primary isolation mode. Uses git worktrees for lightweight, fast filesystem isolation.

**How it works:**
1. Creates a bare clone of the repo (one per unique repo URL)
2. Pre-warms N worktree slots via `git worktree add`
3. On `acquire()`: checks out the task's base commit, runs setup commands/files
4. On `reset()`: runs `git reset --hard HEAD && git clean -fdx`
5. On `destroyAll()`: runs `git worktree remove --force` for all slots

**Performance:**
- Worktree creation: <100ms
- Reset (git clean): <50ms
- No Docker overhead, no VM boot time

### PoolManager\<T>

Generic resource pool used internally by WorktreeProvider. Not tied to git — can pool any resource type.

**Key behaviors:**
- `warmup(n)` — pre-create up to n slots (capped at maxSlots)
- `acquire()` — returns an available slot, or blocks until one is released
- `release(id)` — runs the reset callback, returns slot to the available queue
- `destroyAll()` — destroys all slots, rejects pending acquires

**Blocking:** When all slots are in use and a new `acquire()` is called, it queues the request and resolves when a slot is released. This naturally throttles concurrency to `--parallelism`.

### NoneProvider

Passthrough for legacy sequential mode. Returns a `TaskEnvironment` pointing at `process.cwd()` with no isolation. Used when `--isolation none` or `--parallelism 1` without explicit isolation flag.

### DockerProvider (stub)

Placeholder for future Docker-based isolation. Currently throws "not yet implemented". The plan is:
- `docker create` + `docker start` a persistent container per slot
- `docker exec` for each agent command
- Worktree mounted as `/workspace` volume inside the container

## How workingDirectory Works

The isolation system relies on `workingDirectory` — a field on `ProductionAgentConfig` that scopes all tool operations to a specific directory.

```
Agent created with workingDirectory = "/tmp/pool/wt-3"
  |
  +-- bash tool: default cwd = /tmp/pool/wt-3
  +-- read_file("src/main.ts") resolves to /tmp/pool/wt-3/src/main.ts
  +-- write_file("output.txt") resolves to /tmp/pool/wt-3/output.txt
  +-- grep(path: ".") resolves to /tmp/pool/wt-3
  +-- glob(path: ".") resolves to /tmp/pool/wt-3
```

Absolute paths are left untouched. Only relative paths are resolved against `workingDirectory`. When `workingDirectory` is not set, everything falls back to `process.cwd()` — backward compatible.

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--parallelism <n>` | `1` | Number of concurrent tasks |
| `--isolation <type>` | auto | `worktree`, `docker`, or `none`. Auto-selects `worktree` when parallelism > 1 |
| `--cost-limit <$>` | none | Stop the batch if total cost exceeds this amount |

## Testing

```bash
# Pool manager tests (13 tests)
npx vitest run tests/eval/pool-manager.test.ts

# basePath tool wrapping tests (9 tests)
npx vitest run tests/eval/basepath-tools.test.ts

# All eval-related tests
npx vitest run tests/eval/
```

## Files

| File | Purpose |
|------|---------|
| `types.ts` | `TaskEnvironment`, `IsolationProvider`, `BatchConfig`, `PoolStats` |
| `index.ts` | `createIsolationProvider()` factory + `NoneProvider` |
| `pool-manager.ts` | Generic `PoolManager<T>` with acquire/release/warmup |
| `worktree-provider.ts` | `WorktreeProvider` — git worktree isolation |
| `docker-provider.ts` | `DockerProvider` — stub for future Docker isolation |
