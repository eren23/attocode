# Recording & Visual Replay

Attocode can record full agent sessions as structured graphs, then replay them frame-by-frame for debugging and analysis. The recording system captures tool calls, LLM interactions, file exploration paths, budget events, and more.

## Enabling Recording

```bash
# Record a session
attocode --record "Refactor the authentication module"

# Recording is also available via config
# .attocode/config.json
{
  "record": true
}
```

Recordings are saved to `.attocode/recordings/{session_id}/` and include JSON metadata, exploration graphs, session graphs, and an HTML gallery.

## What Gets Recorded

### Session Graph

The `SessionGraph` is a unified directed acyclic graph (DAG) capturing every significant event during a session.

**11 Node Kinds:**

| NodeKind | Description |
|----------|-------------|
| `MESSAGE` | User or assistant message |
| `LLM_CALL` | LLM API request (with model, tokens, cost) |
| `TOOL_CALL` | Tool execution (with name, args, result) |
| `DECISION` | Agent decision point |
| `FILE_VISIT` | File access event |
| `SUBAGENT_SPAWN` | Subagent creation |
| `SUBAGENT_COMPLETE` | Subagent finish |
| `SWARM_TASK` | Swarm task event |
| `BUDGET_EVENT` | Budget check or warning |
| `COMPACTION_EVENT` | Context compaction (tokens saved, messages removed) |
| `ERROR` | Error occurrence |

**9 Edge Kinds:**

| EdgeKind | Description |
|----------|-------------|
| `SEQUENTIAL` | Time-ordered flow (auto-created) |
| `CAUSES` | Causal relationship |
| `RESPONSE_TO` | LLM response to a prompt |
| `IMPORT_FOLLOW` | Following an import chain |
| `SEARCH_RESULT` | File found via search |
| `EDIT_CHAIN` | Sequential edits to same file |
| `SPAWNS` | Parent spawns subagent |
| `DELEGATES` | Task delegation |
| `COMPACTS` | Compaction relationship |

Each node records timestamps, agent ID, iteration number, and metadata specific to its kind (tokens, cost, file paths, tool args, etc.).

### Auto-Sequencing

When a node is added, a `SEQUENTIAL` edge is automatically created from the previous node in that agent's path. In multi-agent sessions, each agent has its own sequential path overlaid on the shared graph.

## Exploration Graph

The `ExplorationGraph` tracks the agent's navigation through the codebase as a separate DAG focused on file visits.

### Node Actions

| Action | Triggered By |
|--------|-------------|
| `read` | `read_file` |
| `search` | `grep`, `glob`, `bash` |
| `edit` | `edit_file`, `write_file` |
| `overview` | `get_repo_map`, `get_tree_view` |

### Outcome Marking

Each file visit can be marked with an outcome:

| Outcome | Meaning |
|---------|---------|
| `useful` | File provided valuable information (default) |
| `dead_end` | Exploration cul-de-sac, file wasn't helpful |
| `key_finding` | Important discovery that influenced decisions |

Outcomes are used in Mermaid exports for visual styling: key findings in green, dead ends in red, edits in blue.

### Per-Agent Paths

In multi-agent sessions, `get_agent_path(agent_id)` isolates a single agent's file navigation history, making it easy to trace what each worker explored.

## Recording Configuration

```python
@dataclass
class RecordingConfig:
    output_dir: str = ".attocode/recordings"
    capture_granularity: str = "tool_call"
    capture_screenshots: bool = True
    max_frames: int = 500
    debounce_ms: float = 200.0
```

### Capture Granularity

| Level | What Gets Captured |
|-------|--------------------|
| `iteration` | Only iteration-level and subagent events |
| `tool_call` (default) | Tool calls, iterations, and subagent events |
| `event` | All events (finest granularity) |

Critical events (`tool.error`, `subagent.spawn`, `subagent.complete`) are always captured regardless of granularity or debounce settings.

### Output Directory Layout

```
.attocode/recordings/{session_id}/
├── recording.json           # Session metadata
├── exploration_graph.json   # File navigation DAG
├── session_graph.json       # Full event graph
├── exploration.mmd          # Mermaid diagram
├── session.mmd              # Mermaid diagram
├── frames/
│   ├── frame-0001.json      # Per-frame sidecar
│   ├── frame-0002.json
│   └── ...
└── gallery.html             # Self-contained visual report
```

## Playback Engine

The `PlaybackEngine` provides frame-by-frame navigation over a `SessionGraph`:

### Navigation

| Method | Description |
|--------|-------------|
| `step_forward()` | Advance one frame |
| `step_backward()` | Go back one frame |
| `jump_to(index)` | Jump to specific frame |
| `jump_to_start()` | Jump to first frame |
| `jump_to_end()` | Jump to last frame |
| `jump_to_timestamp(ts)` | Jump to frame closest to a timestamp |

### Filtering

```python
engine = PlaybackEngine(session_graph)

# Filter to only tool calls
engine.set_filter(kind=NodeKind.TOOL_CALL)

# Filter to a specific agent
engine.set_filter(agent_id="worker-1")

# Combine filters
engine.set_filter(agent_id="worker-1", kind=[NodeKind.TOOL_CALL, NodeKind.LLM_CALL])

# Remove filters
engine.clear_filters()
```

Filtering is non-destructive --- the underlying timeline stays intact and filters are re-applied on each query.

### Cumulative State

At any playback position, `get_state()` returns a `PlaybackState` snapshot with cumulative statistics computed from the start of the timeline up to the current frame:

```python
state = engine.get_state()
# state.total_tokens      — Cumulative tokens used
# state.total_cost        — Cumulative cost
# state.tool_calls        — Number of tool calls so far
# state.messages          — Number of messages so far
# state.errors            — Number of errors so far
# state.files_visited     — Set of unique files accessed
# state.elapsed_seconds   — Time elapsed from first to current frame
```

## Export Formats

### Mermaid Diagrams

Both the session graph and exploration graph export as Mermaid diagrams:

```python
# Session graph
mermaid_text = session_graph.to_mermaid(max_nodes=50)

# Exploration graph
mermaid_text = exploration_graph.to_mermaid(agent_id="main")
```

The session graph Mermaid export uses styled CSS classes: `msg` (messages), `llm` (LLM calls), `tool` (tool calls), `file` (file visits), `agent` (subagent events), `budget` (budget events), `error` (errors).

### ASCII DAG

The exploration graph can render as an ASCII tree:

```python
ascii_text = exploration_graph.to_ascii_dag(agent_id="main")
```

```
├── src/main.py (read)
│   ├── src/auth/login.py (read) [KEY]
│   │   └── src/auth/config.py (read)
│   └── src/api/routes.py (read) [DEAD END]
└── src/utils/helpers.py (edit)
```

Outcome badges (`[KEY]`, `[DEAD END]`) are included for marked nodes.

### HTML Gallery

The `export()` method generates a self-contained HTML gallery:

```python
manager.export(format="html")
# Creates .attocode/recordings/{session_id}/gallery.html
```

The gallery includes:

- **Header** --- Session metadata (ID, frame count, duration, agents)
- **Filmstrip** --- Horizontally scrollable frame cards (click to expand)
- **Exploration graph** --- Mermaid diagram with collapsible ASCII DAG
- **Frame details** --- Per-frame metadata, annotations, and screenshots

The HTML is fully self-contained (all CSS and JavaScript inlined) with a dark theme. No external dependencies required to view.

### JSON Export

Both graphs support JSON serialization:

```python
data = session_graph.to_dict()   # JSON-safe dict (content truncated to 200 chars)
restored = SessionGraph.from_dict(data)

data = exploration_graph.to_dict()
restored = ExplorationGraph.from_dict(data)
```

## Related Pages

- [Tracing](tracing-guide.md) --- JSONL execution traces (complementary to recording)
- [Sessions & Persistence](sessions-guide.md) --- Session storage and checkpoints
- [Architecture](ARCHITECTURE.md) --- Overall system design
