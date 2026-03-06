---
sidebar_position: 2
title: "Event Catalog"
---

# Event Catalog

The `AgentEvent` union type in `src/types.ts` defines all events emitted by the agent. Subscribe with `agent.on(listener)` or use the hooks system.

## Lifecycle Events

| Event | Key Fields | When |
|-------|------------|------|
| `run.before` | `task` | Before the agent starts processing |
| `run.after` | `success`, `reason`, `details` | After the agent completes |
| `iteration.before` | `iteration` | Before each ReAct loop iteration |
| `iteration.after` | `iteration`, `hadToolCalls`, `completionCandidate` | After each iteration |
| `completion.before` | `reason`, `attempt`, `maxAttempts` | Before completing (may be blocked) |
| `completion.after` | `success`, `reason`, `details` | After completion decision |
| `completion.blocked` | `reasons`, `openTasks`, `diagnostics` | When completion is blocked |
| `recovery.before` | `reason`, `attempt`, `maxAttempts` | Before recovery attempt |
| `recovery.after` | `reason`, `recovered`, `attempts` | After recovery attempt |

## Core Events

| Event | Key Fields | When |
|-------|------------|------|
| `start` | `task`, `traceId` | Agent run begins |
| `complete` | `result` | Agent run finishes |
| `error` | `error`, `subagent?` | An error occurs |
| `planning` | `plan` | Plan generated |
| `task.start` | `task` | Plan task begins |
| `task.complete` | `task` | Plan task finishes |
| `llm.start` | `model`, `subagent?` | LLM request starts |
| `llm.chunk` | `content`, `subagent?` | Streaming chunk received |
| `llm.complete` | `response`, `subagent?` | LLM response received |
| `tool.start` | `tool`, `args`, `subagent?` | Tool execution starts |
| `tool.complete` | `tool`, `result` | Tool execution finishes |
| `tool.blocked` | `tool`, `reason` | Tool execution blocked by policy |
| `approval.required` | `request` | User approval needed |
| `approval.received` | `response` | User responded to approval |
| `reflection` | `attempt`, `satisfied` | Self-critique evaluation |
| `memory.retrieved` | `count` | Memories loaded |
| `memory.stored` | `memoryType` | Memory persisted |

## ReAct Events

| Event | Key Fields | When |
|-------|------------|------|
| `react.thought` | `step`, `thought` | Agent reasoning step |
| `react.action` | `step`, `action`, `input` | Agent decides to act |
| `react.observation` | `step`, `observation` | Tool result observed |
| `react.answer` | `answer` | Final answer produced |

## Multi-Agent Events

| Event | Key Fields | When |
|-------|------------|------|
| `multiagent.spawn` | `agentId`, `role` | Subagent spawned |
| `multiagent.complete` | `agentId`, `success` | Subagent finished |
| `consensus.start` | `strategy` | Consensus process begins |
| `consensus.reached` | `agreed`, `result` | Consensus resolved |
| `agent.spawn` | `agentId`, `name`, `task` | Agent registry spawn |
| `agent.complete` | `agentId`, `agentType`, `success`, `output` | Agent finished |
| `agent.error` | `agentId`, `agentType`, `error` | Agent failed |
| `agent.pending_plan` | `agentId`, `changes` | Subagent proposes plan |
| `parallel.spawn.start` | `count`, `agents` | Parallel spawn begins |
| `parallel.spawn.complete` | `count`, `successCount`, `results` | Parallel spawn finished |

## Policy Events

| Event | Key Fields | When |
|-------|------------|------|
| `policy.evaluated` | `tool`, `policy`, `reason` | Policy rule evaluated |
| `intent.classified` | `tool`, `intent`, `confidence` | Tool intent classified |
| `grant.created` | `grantId`, `tool` | Permission grant created |
| `grant.used` | `grantId` | Permission grant consumed |
| `policy.profile.resolved` | `profile`, `context` | Policy profile selected |
| `policy.tool.auto-allowed` | `tool`, `reason` | Tool auto-approved |
| `policy.tool.blocked` | `tool`, `profile`, `reason` | Tool blocked by policy |
| `policy.bash.blocked` | `command`, `profile`, `reason` | Bash command blocked |
| `decision.routing` | `model`, `reason`, `alternatives` | Model routing decision |
| `decision.tool` | `tool`, `decision`, `policyMatch` | Tool permission decision |

## Subagent Visibility Events

| Event | Key Fields | When |
|-------|------------|------|
| `subagent.iteration` | `agentId`, `iteration`, `maxIterations` | Subagent loop progress |
| `subagent.phase` | `agentId`, `phase` | Phase change (exploring/planning/executing/completing) |
| `subagent.wrapup.started` | `agentId`, `agentType`, `reason` | Graceful shutdown begins |
| `subagent.wrapup.completed` | `agentId`, `agentType`, `elapsedMs` | Graceful shutdown done |
| `subagent.timeout.hard_kill` | `agentId`, `agentType`, `reason` | Hard timeout reached |

## Context and Compaction Events

| Event | Key Fields | When |
|-------|------------|------|
| `compaction.auto` | `tokensBefore`, `tokensAfter`, `messagesCompacted` | Auto-compaction ran |
| `compaction.warning` | `currentTokens`, `threshold` | Approaching context limit |
| `context.health` | `currentTokens`, `maxTokens`, `percentUsed` | Context health check |

## Resilience Events

| Event | Key Fields | When |
|-------|------------|------|
| `resilience.retry` | `reason`, `attempt`, `maxAttempts` | LLM call retry |
| `resilience.recovered` | `reason`, `attempts` | Recovery succeeded |
| `resilience.continue` | `reason`, `continuation`, `accumulatedLength` | Continuation of truncated response |
| `resilience.failed` | `reason`, `emptyRetries`, `continuations` | All retries exhausted |
| `resilience.truncated_tool_call` | `toolNames` | Tool call was truncated |

## Insight Events

| Event | Key Fields | When |
|-------|------------|------|
| `insight.tokens` | `inputTokens`, `outputTokens`, `cost`, `model` | Token usage report |
| `insight.context` | `currentTokens`, `maxTokens`, `percentUsed` | Context utilization |
| `insight.tool` | `tool`, `summary`, `durationMs`, `success` | Tool execution summary |
| `insight.routing` | `model`, `reason`, `complexity` | Model routing info |

## Other Events

| Event | Key Fields | When |
|-------|------------|------|
| `cancellation.requested` | `reason` | User cancelled |
| `cancellation.completed` | `cleanupDuration` | Cleanup finished |
| `cache.hit` / `cache.miss` / `cache.set` | `query`, `similarity` | Semantic cache |
| `learning.proposed` / `validated` / `applied` | `learningId` | Learning store |
| `mode.changed` | `from`, `to` | Agent mode switch |
| `plan.change.queued` / `approved` / `rejected` | varies | Plan mode events |
| `task.created` / `task.updated` / `task.deleted` | `task` or `taskId` | Task system |
| `safeguard.*` | varies | Tool call explosion defense |
| `diagnostics.syntax-error` | `file`, `line`, `message` | AST parse errors |
| `diagnostics.tsc-check` | `errorCount`, `duration`, `trigger` | TypeScript check |
