# Swarm Dashboard

The trace dashboard includes a real-time swarm visualization page that shows task execution, budget consumption, quality metrics, and event streams as your swarm runs.

## Starting the Dashboard

```bash
# Terminal 1: Run swarm with tracing enabled
attocode --swarm --trace "Build a feature"

# Terminal 2: Start the dashboard
cd tools/trace-dashboard
npm run dashboard
```

The dashboard starts two servers:
- **API server** (Hono): Serves swarm state via REST and SSE
- **Frontend** (Vite + React): The visual dashboard

Open the URL shown in the terminal (typically `http://localhost:5173`).

## Dashboard Panels

The swarm dashboard page is composed of several panels, each showing a different aspect of execution.

### Header

Shows the current swarm phase, session ID, and connection status. Phases include:
- **decomposing** — Breaking the task into subtasks
- **planning** — Creating acceptance criteria
- **scheduling** — Organizing tasks into waves
- **executing** — Workers running tasks
- **reviewing** — Manager reviewing wave outputs
- **verifying** — Running integration tests
- **synthesizing** — Merging outputs
- **completed** / **failed** — Terminal states

### Metrics Strip

A horizontal strip of key numbers:
- Total tasks (completed / total)
- Current wave (current / total)
- Active workers count
- Tokens used
- Cost consumed
- Duration

### Wave Progress Strip

Visual progress bar showing each wave's completion status. Color-coded:
- Green: completed
- Yellow: in progress
- Red: failed
- Gray: pending

### Task DAG Panel

An interactive directed acyclic graph showing:
- Each task as a node with status coloring
- Dependency edges between tasks
- Click a task node to open the Task Inspector

Task nodes show:
- Task ID and abbreviated description
- Assigned model
- Quality score (if available)
- Duration

### Task Inspector

Click any task in the DAG to see full details:
- Description and type
- Assigned worker and model
- Output content
- Quality gate score and feedback
- Token usage and cost
- Files modified
- Duration

### Worker Timeline Panel

A Gantt-style timeline showing:
- Each worker as a horizontal lane
- Task execution blocks with duration
- Parallel execution visible as overlapping blocks
- Gaps between tasks (idle time, rate limit waits)

This is useful for identifying bottlenecks — if one worker lane is much longer than others, that model may be too slow.

### Budget Panel

Radial gauges showing:
- **Token budget**: Used vs. total (percentage)
- **Cost budget**: Spent vs. cap

Color transitions from green (healthy) to yellow (caution) to red (near limit).

### Model Distribution Panel

Pie/bar chart showing:
- How many tasks each model executed
- Token consumption per model
- Cost per model

Useful for understanding which models are doing the most work and whether the distribution is balanced.

### Quality Heatmap Panel

Grid showing quality gate scores per task:
- Score 1-2: Red (poor)
- Score 3: Yellow (acceptable)
- Score 4-5: Green (good)

Tasks without quality scores (skipped gates) show as gray.

### Hierarchy Panel

Shows the role hierarchy activity:
- Manager actions (planning, wave review)
- Judge actions (quality gates, verification)
- Which models are assigned to each role

### Event Feed Panel

A scrolling log of all swarm events in chronological order. Each event row shows:
- Timestamp
- Event type (color-coded by category)
- Event details

You can filter events by category (task, wave, quality, budget, etc.).

## Real-Time Architecture

The dashboard uses Server-Sent Events (SSE) for real-time updates:

```
SwarmOrchestrator
  └─► SwarmEventBridge (writes events to JSONL file)
       └─► swarm-watcher.ts (polls JSONL for new entries)
            └─► /api/swarm/live (SSE endpoint)
                 └─► useSwarmStream() hook (React client)
                      └─► Dashboard state updates
```

The `useSwarmStream` hook:
1. Connects to the SSE endpoint
2. Processes incoming events to update UI state
3. Handles reconnection on disconnect
4. Shows an idle state when no swarm is active

The dashboard auto-connects when a swarm starts and shows an idle placeholder otherwise.

## Expanding Panels

Each panel has an expand button that toggles between compact and full views:
- **Compact**: Shows summary information, suitable for an overview
- **Expanded**: Shows full detail, useful for debugging

The Task DAG and Event Feed panels benefit most from expansion.

## Starting Without an Active Swarm

If you open the dashboard before starting a swarm, you'll see:
```
No active swarm
Start a swarm task with --swarm flag to see live visualization.
```

The dashboard will auto-connect when a swarm starts. You can also click "Refresh" to reconnect manually.

## Swarm History

The dashboard also has a history page (`/swarm/history`) that lists previous swarm sessions from the trace files. You can review completed swarm runs, compare sessions, and analyze patterns.

## Commands

```bash
# Start development servers (API + Vite with hot reload)
npm run dashboard

# Build for production
npm run dashboard:build

# Run production build
npm run dashboard:start
```

## See Also

- [Architecture Deep Dive](architecture-deep-dive.md) — Event bridge and persistence internals
- [Getting Started](../getting-started.md) — Running your first swarm with tracing
