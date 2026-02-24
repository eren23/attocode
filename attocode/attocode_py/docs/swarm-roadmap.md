# Swarm Roadmap

Known gaps and planned improvements for the `attoswarm` hybrid swarm orchestrator, organized by priority.

## Tier 1: Interpretability (highest ROI)

- **Per-agent execution trace streaming** — stream tool calls, cost deltas, and reasoning from each agent into TUI; currently only terminal events (heartbeat/done/failed) are visible
- **Merge conflict visualization** — show which files conflicted, merge strategy attempted, merger's resolution in TUI events table
- **Task output preview** — when a task completes, show a summary of what files were created/modified and key content (first N lines of new files)
- **Budget projection** — extrapolate remaining budget vs estimated tasks; warn at 80%, graceful shutdown at 95%
- **Failure attribution chain** — when a task fails, trace the root cause: was it timeout, cost, agent crash, dependency failure, or coordination error?

## Tier 2: Cross-Worktree Communication

- **Context propagation for dependent tasks** — when task t0 finishes in worktree-1, sync its file changes into worktree-2 before starting t1 (which depends on t0)
- **Shared read-only context directory** — broadcast completed task outputs to a shared `.agent/hybrid-swarm/<run>/shared/` directory that all agents can read
- **Inter-agent message channel** — allow agents to post structured messages (e.g., "I created `api.py` with these exports") that dependent agents receive as context
- **Incremental index updates** — re-run `CodeIndex.build()` after each task completion and make the updated snapshot available to subsequent agents

## Tier 3: Robustness & Merge Quality

- **Merge conflict detection** — before assigning merge task, run `git merge --no-commit` to check for conflicts and report them
- **Auto-rebase fallback** — if merge fails, try `git rebase` before marking as failed
- **Quality gate unit tests** — test judge/critic quorum logic, threshold computation, rejection/retry loops (currently only roundtrip serialization tested)
- **Budget enforcement tests** — test hard-limit shutdown, reserve ratio, cost-based termination
- **Cascade failure detection** — if t0 fails, immediately mark t1 (depends on t0) as blocked instead of letting it wait indefinitely
- **Agent crash recovery tests** — test watchdog restart + task reassignment end-to-end

## Tier 4: Better Test Scenarios

- **Multi-file conflict smoke test** — two workers edit the same file in parallel, verify merge handles it
- **Budget exhaustion test** — set very low budget, verify swarm terminates gracefully with proper state
- **Timeout cascade test** — one agent hangs past `task_silence_timeout`, verify cleanup + retry
- **Mixed backend test** — Claude worker + Codex judge, verify cross-backend protocol works
- **Large DAG test** — 10+ tasks with complex dependency graph, verify ordering and parallel dispatch
- **Resume fidelity test** — run halfway, kill, resume, verify no duplicate work or lost state
- **Worktree isolation test** — verify agents can't see each other's uncommitted changes

## Tier 5: Adaptive Orchestration (future)

- **LLM-based task decomposition** — use the orchestrator model to decompose goals into concrete tasks (currently falls back to `parallel`)
- **Dynamic task splitting** — if a task is too large mid-execution, split it into subtasks
- **Cost-aware scheduling** — assign cheaper models to simple tasks, expensive models to complex ones
- **Agent capability matching** — match tasks to agents by capability, not just role
