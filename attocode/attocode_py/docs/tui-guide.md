# TUI Interface Guide

Attocode features a rich terminal user interface built with [Textual](https://textual.textualize.io/). The TUI provides real-time feedback on agent activity, interactive dialogs for tool approval, and multi-panel views for monitoring complex operations.

## Launching the TUI

```bash
# Default: TUI mode
attocode

# Force TUI mode
attocode --tui

# Force REPL fallback (no TUI)
attocode --no-tui

# Choose theme
attocode --theme dark
```

## Keyboard Shortcuts

| Shortcut | Action | Description |
|----------|--------|-------------|
| `Ctrl+C` | Quit | Exit the application (press twice to force quit) |
| `Ctrl+L` | Clear screen | Clear message log and tool panel |
| `Ctrl+P` | Command palette | Open searchable command picker |
| `Ctrl+Y` | Copy last response | Copy the last agent response to clipboard |
| `Ctrl+D` | Dashboard | Open the multi-tab trace analysis dashboard |
| `Ctrl+M` | Swarm monitor | Open the fleet-level swarm monitor |
| `Ctrl+T` | Toggle tools | Expand/collapse tool call details |
| `Ctrl+W` | Toggle swarm | Show/hide the swarm panel |
| `Ctrl+S` | Swarm dashboard | Open full-screen 8-tab swarm dashboard |
| `Ctrl+I` | Agent internals | Toggle budget, compaction, cache stats panel |
| `Escape` | Cancel | Cancel the current operation |

### Input Area

| Shortcut | Action |
|----------|--------|
| `Enter` | Submit prompt |
| `Ctrl+Z` | Undo |

## Panels

The TUI is composed of vertically stacked panels. Most panels are hidden by default and appear when relevant data is available.

### Welcome Banner

Shows the model name, git branch, version, and a usage tip. Disappears after the first interaction.

### Message Log

The primary conversation area. Displays user prompts, agent responses, system messages, and tool output. Messages are rendered with Rich markup for syntax highlighting.

### Streaming Buffer

Appears during LLM response generation. Shows the response as it streams in with an animated cursor.

### Thinking Panel

Displays the model's extended thinking output (for models that support it). Hidden by default.

### Tool Calls Panel

Shows active and completed tool calls with:

- Tool name and status spinner
- Full arguments (expandable with `Ctrl+T`)
- Execution result or error
- Timing information

### Plan Panel

Visible when the agent is executing a multi-step plan. Shows:

- Current goal
- Step list with completion status `[done/total]`
- Active step highlighted

### Tasks Panel

Shows active tasks with status icons and dependency counts. Useful for tracking decomposed work.

### Agents Panel

Lists active subagents with their task description, status, token usage, and iteration count.

### Swarm Panel

Visible during swarm mode operations. Shows:

- Swarm phase (planning, executing, completing)
- Wave progress
- Worker status
- Queue depth
- Budget consumption

### Agent Internals Panel

Toggle with `Ctrl+I`. Shows internal agent metrics:

- Budget usage percentage
- Compaction count and tokens saved
- Doom loop detection status
- KV-cache hit rate

### Status Bar

A 2-line bar at the bottom showing:

- Model name and provider
- Iteration count
- Token usage and estimated cost
- Context window usage (`ctx: X%`)
- Budget usage (`bud: X%`)
- Git branch
- File change count
- Cache hit rate

### Token Sparkline

A mini chart showing token usage per LLM call for the last ~20 calls. Mounted dynamically when token data is available.

## Themes

Three built-in themes are available:

| Theme | Description |
|-------|-------------|
| `dark` | Catppuccin Mocha-inspired dark theme (default) |
| `light` | Catppuccin Latte-inspired light theme |
| `high_contrast` | Pure black/white with neon accents for accessibility |

Switch themes at runtime:

```
/theme dark
/theme light
/theme high_contrast
```

Or set at launch:

```bash
attocode --theme light
```

## Command Palette

Press `Ctrl+P` to open the command palette. It provides a searchable list of all available slash commands with fuzzy matching on name and shortcut.

Type to filter, use arrow keys to navigate, and press Enter to execute.

## Dialogs

The TUI uses modal dialogs for interactive decisions.

### Approval Dialog

Appears when a tool requires user permission. Shows tool name, arguments, and danger level with color-coded borders:

- **Green border** — Safe tool
- **Yellow border** — Moderate danger
- **Red border** — High danger

| Key | Action |
|-----|--------|
| `Y` | Approve this call |
| `A` | Always allow this tool (session-scoped) |
| `N` | Deny |
| `Escape` | Deny |

### Budget Extension Dialog

Appears when the agent requests additional budget. Shows current budget, usage percentage, and the requested extension.

| Key | Action |
|-----|--------|
| `Y` | Approve extension |
| `N` | Deny |
| `Escape` | Deny |

### Learning Validation Dialog

Appears when the agent proposes a new learning (pattern, preference, etc.) for validation. Shows the learning type, description, evidence, and confidence score.

| Key | Action |
|-----|--------|
| `Y` | Approve learning |
| `N` | Reject |
| `S` | Skip |
| `Escape` | Skip |

### Setup Wizard

A 3-step wizard that runs on first launch:

1. **Provider selection** — Choose from Anthropic, OpenRouter, OpenAI, ZAI, Azure
2. **API key input** — Enter your API key (hidden input)
3. **Model selection** — Pick a model or enter a custom model ID

## Screens

### Dashboard Screen (`Ctrl+D`)

A multi-tab analysis view with 5 tabs:

| Tab | Key | Content |
|-----|-----|---------|
| Live | `1` | Real-time token, cache, tool, and budget metrics |
| Sessions | `2` | Browse past trace sessions |
| Detail | `3` | Deep-dive into a selected session (5 sub-views: summary, timeline, tree, tokens, issues) |
| Compare | `4` | Side-by-side A/B session comparison |
| Swarm | `5` | Multi-agent orchestration view |

### Swarm Dashboard (`Ctrl+S`)

A full-screen 8-tab dashboard for monitoring swarm operations:

| Tab | Key | Content |
|-----|-----|---------|
| Overview | `1` | Agent grid, task board, dependency DAG, timeline |
| Workers | `2` | Worker detail cards with output streams |
| Tasks | `3` | Task inspector with DataTable |
| Models | `4` | Model health: latency, cache, error rates |
| Decisions | `5` | Decision log and error summary |
| Files | `6` | File activity map, artifacts, conflicts |
| Quality | `7` | Quality gates, hollow detection, wave reviews |
| AST/BB | `8` | AST explorer and shared blackboard inspector |

### Swarm Monitor (`Ctrl+M`)

Fleet-level monitoring of all swarm runs in the workspace. Browse historical swarm sessions and stream live events from trace files.

## Tips

- Use `/status` to see a metrics table in a modal dialog
- Use `/budget` to check budget details in a modal dialog
- The typing indicator ("Agent is thinking...") shows animated dots while waiting for LLM responses
- Press `Ctrl+C` once to cancel, twice to force quit
- Most panels auto-show and auto-hide based on agent activity
