---
sidebar_position: 4
title: Plan Mode
---

# Plan Mode

Plan mode is a controlled execution workflow where write operations are intercepted, queued as proposed changes, and only applied after explicit user approval. This gives you full visibility and control over what the agent modifies.

## Activating Plan Mode

```
/plan              # Toggle plan mode on/off
/mode plan         # Switch directly to plan mode
```

When plan mode is active, the status bar shows a blue "Plan" indicator and the system prompt is augmented with detailed instructions for the LLM about queuing behavior.

## The Approval Workflow

### 1. Exploration

In plan mode, the agent can freely read files, search code, run read-only bash commands, and spawn research subagents. These operations execute immediately with no interception.

### 2. Proposed Changes

When the agent calls a write tool (`write_file`, `edit_file`, `delete_file`, or `bash` with side effects), the operation is intercepted by the `PendingPlanManager`. Instead of executing, the change is recorded as a `ProposedChange`:

```typescript
interface ProposedChange {
  id: string;            // Unique change ID
  tool: string;          // Tool that would be called
  args: Record<string, unknown>;  // Tool arguments
  reason: string;        // LLM's explanation of why
  order: number;         // Execution order
  proposedAt: string;    // Timestamp
  toolCallId?: string;   // Original tool call ID
}
```

The agent receives a confirmation message like `[PLAN MODE] Change queued for approval` and is instructed to move on to the next task rather than retrying or verifying the change.

### 3. Review

Use `/show-plan` to display all pending changes:

```
/show-plan
```

This shows each proposed change with its tool, arguments, reason, and order. You can review exactly what files will be created or modified and what commands will run.

### 4. Approve or Reject

```
/approve           # Execute all pending changes
/approve 3         # Execute only the first 3 changes
/reject            # Discard all pending changes
```

Partial approval (`/approve <n>`) executes changes in order up to `n` and leaves the rest pending. This is useful when you want to accept some changes but not others.

## Plan Status Lifecycle

Each pending plan has a status that tracks its progress:

| Status | Meaning |
|--------|---------|
| `pending` | Changes proposed, awaiting user decision |
| `approved` | User approved, changes being executed |
| `rejected` | User rejected, changes discarded |
| `partially_approved` | Some changes approved, others remain pending |

## Pending Plan Structure

The `PendingPlan` object groups all proposed changes for a task:

```typescript
interface PendingPlan {
  id: string;
  task: string;                    // Original task/prompt
  createdAt: string;
  updatedAt: string;
  proposedChanges: ProposedChange[];
  explorationSummary: string;      // What was explored before proposing
  status: PlanStatus;
  sessionId?: string;
}
```

## Interactive Planning

Beyond the basic propose-approve cycle, Attocode supports conversational plan refinement via `src/integrations/tasks/interactive-planning.ts`. The interactive planner follows a **Draft, Discuss, Execute, Checkpoint** cycle:

### Draft

The agent generates a structured plan with numbered steps, each having a description, dependencies, estimated complexity, and optional decision points.

### Discuss

You can refine the plan using natural language:

```
"add rate limiting after step 3"
"skip the testing step for now"
"move step 5 before step 2"
```

The planner parses these edit commands and restructures the plan accordingly.

### Execute

Once approved, each step executes in order. Before each step, an automatic checkpoint is created for rollback capability.

### Decision Points

Steps can be marked as decision points where the agent pauses for user input. The step defines a set of options, and the agent waits for you to choose before continuing.

### Plan Step Schema

```typescript
interface PlanStep {
  id: string;
  number: number;            // 1-indexed for display
  description: string;
  dependencies: string[];    // Step IDs that must complete first
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';
  checkpointId?: string;     // Created before execution
  isDecisionPoint?: boolean;
  decisionOptions?: string[];
  complexity?: number;       // 1-5
}
```

## Crash Recovery

Pending plans are persisted to SQLite via the session store. If Attocode crashes or is interrupted while a plan is pending, the plan is recovered on the next session resume. You can then `/show-plan` and `/approve` or `/reject` to continue.

## Subagent Behavior

Subagents spawned in plan mode inherit the mode and queue their writes into the parent's pending plan. Key rules enforced by the system prompt:

- When a subagent reports that changes were queued, the parent should not re-attempt the same work
- The parent cannot verify queued files (they do not exist on disk yet)
- Research/exploration subagents run normally since they only use read operations

## Write Detection

Plan mode intercepts operations identified as writes by two mechanisms:

1. **Static tool list:** `write_file`, `edit_file`, `delete_file`, `bash`, `run_tests`, `execute_code`
2. **MCP write patterns:** Regex matching on `mcp_` prefixed tools for action verbs like `create`, `update`, `delete`, `push`, `commit`
3. **Bash command analysis:** Read-only bash commands are allowlisted; everything else is intercepted

## Source Files

| File | Purpose |
|------|---------|
| `src/integrations/tasks/pending-plan.ts` | PendingPlanManager, ProposedChange, PlanApprovalResult |
| `src/integrations/tasks/interactive-planning.ts` | Interactive planner with edit commands and decision points |
| `src/modes.ts` | Mode definitions, write tool detection, ModeManager |
| `src/commands/handler.ts` | `/plan`, `/show-plan`, `/approve`, `/reject` command handlers |
