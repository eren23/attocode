# Budget & Economics System

## Overview

The economics system in `src/attocode/integrations/budget/` manages token budgets, cost tracking, and execution health.

## Components

| Module | Purpose |
|--------|---------|
| `economics.py` | `ExecutionEconomicsManager` - main budget tracker |
| `loop_detector.py` | Doom loop detection (3+ identical tool calls) |
| `phase_tracker.py` | Phase tracking (exploration → planning → acting → verifying) |
| `dynamic_budget.py` | Dynamic budget allocation for subagents |
| `budget_pool.py` | Shared budget pool for parallel agents |

## Budget Configuration

```json
{
  "budget_max_tokens": 1000000,
  "budget_max_cost": 10.0,
  "budget_max_duration": 7200
}
```

Or via CLI:

```bash
attocode --max-iterations 50
```

## Budget Extension

When budget is nearly exhausted, the TUI shows a budget extension dialog:
- User can grant additional tokens/cost
- Wired via `BudgetExtensionDialog` in TUI

## Doom Loop Detection

The loop detector identifies when the agent is stuck:
- Same tool called 3+ times with identical arguments
- Triggers a nudge message instead of hard stop
- Configurable thresholds

## Phase Tracking

The agent progresses through phases:
1. **Exploration** - Reading files, searching code
2. **Planning** - Forming a plan of action
3. **Acting** - Making edits, running commands
4. **Verifying** - Running tests, checking results

Exploration saturation nudge activates after 10+ file reads without edits.

## Token Accounting

- Input tokens, output tokens, cache read/write tracked per LLM call
- Cumulative tracking across runs via `_total_tokens_all_runs`
- Baseline set after first LLM call for incremental accounting
- Usage logged to SQLite `usage_logs` table
