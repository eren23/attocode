---
sidebar_position: 1
title: Terminal UI
---

# Terminal UI

Attocode's primary interface is a rich Terminal UI (TUI) built with [Ink](https://github.com/vadimdemedes/ink), a React renderer for the terminal. The TUI lives in `src/tui/app.tsx` and is designed around flicker-free rendering and responsive keyboard input.

## Anti-Flicker Architecture

The TUI uses a deliberate rendering strategy to prevent the visual flickering that plagues naive terminal UIs:

- **`<Static>` for messages** -- Messages are rendered inside Ink's `<Static>` component. Once a message appears, it is never re-rendered. This means scrolling back through conversation history is always instant and stable.
- **Tool calls re-render on status changes** -- Active tool calls live outside `<Static>` and update their display as status changes (pending, running, complete, error).
- **Memoized components** -- `MessageItem`, `ToolCallItem`, and `MemoizedInputArea` are all wrapped with `React.memo` and custom comparators to skip renders when visual props have not changed.
- **Ref-based callbacks** -- All keyboard handler callbacks are stored in refs inside `MemoizedInputArea`. This prevents Ink's `useInput` hook from re-subscribing every time a parent re-renders.

## Single Input Hook

A critical design constraint: Ink allows only one `useInput` hook to be active without causing keyboard conflicts. Attocode solves this by placing a single `useInput` call inside `MemoizedInputArea`, which then dispatches to the appropriate handler based on context (normal input, command palette, approval dialog).

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+C` | Exit the application |
| `Ctrl+L` | Clear the screen |
| `Ctrl+P` | Open command palette |
| `ESC` | Cancel current operation |
| `Alt+T` | Toggle tool call details panel |
| `Alt+O` | Toggle thinking/reasoning display |
| `Alt+I` | Toggle transparency panel |
| `Alt+A` | Toggle active agents panel |
| `Alt+K` | Toggle tasks panel |
| `Alt+D` | Toggle debug panel |
| `Alt+W` | Toggle swarm status panel |
| `Alt+Y` | Toggle diagnostics panel |

**macOS note:** The Alt key on macOS produces Unicode characters rather than modifier key events. For example, `Alt+T` produces `†` and `Alt+O` produces `ø`. The input handler matches on these Unicode characters directly to support macOS keyboards.

## Toggle Panels

The TUI has 8 toggle panels that can be shown or hidden independently:

1. **Tool calls** (`Alt+T`) -- Shows full tool arguments and results in expanded view
2. **Thinking** (`Alt+O`) -- Displays the model's chain-of-thought reasoning
3. **Transparency** (`Alt+I`) -- Shows internal decision-making and routing state
4. **Active agents** (`Alt+A`) -- Lists running subagents with status and budget
5. **Tasks** (`Alt+K`) -- Shows task decomposition and progress
6. **Debug** (`Alt+D`) -- Raw debug output buffer
7. **Swarm** (`Alt+W`) -- Swarm orchestration status when running parallel agents
8. **Diagnostics** (`Alt+Y`) -- Type checker results, AST cache stats

## Approval Dialog

When the agent requests a potentially destructive operation, an approval dialog appears inline:

- **Y** -- Approve the operation
- **A** -- Always allow this pattern (stores in SQLite with prefix matching)
- **N** -- Deny the operation
- **D** -- Deny with a reason (enters text input mode for the reason)

The dialog uses risk-based coloring: low-risk operations show in the default theme color, medium-risk in yellow, and high-risk in red. The "always allow" patterns use smart matching -- for example, approving `bash:npm` covers all npm commands, and approving `write_file:src/api/` covers all writes under that directory.

## Status Bar

The bottom status bar displays real-time metrics:

- **Model** -- Active LLM model identifier
- **Tokens** -- Input/output token counts
- **Cost** -- Estimated USD cost for the session
- **Phase** -- Current agent phase (exploring, planning, acting, verifying)
- **Cache** -- Cache hit information when available

## Command Palette

Press `Ctrl+P` to open the command palette. It provides:

- Fuzzy search across all available commands
- Arrow key navigation through results
- Enter to execute the selected command
- ESC to close without executing

The palette indexes all slash commands, keyboard shortcuts, and active skills.

## Theme System

Three built-in themes are available, switchable via `/theme <name>`:

| Theme | Description |
|-------|-------------|
| `dark` | Default. One Dark-inspired color scheme with round borders |
| `light` | One Light-inspired scheme for bright terminals |
| `high-contrast` | Maximum contrast with bold borders, suitable for accessibility |

Each theme defines colors for text, backgrounds, semantic states (success, error, warning, info), message roles (user, assistant, system, tool), code highlighting, and component borders. The theme interface (`ThemeColors`) has 25+ color slots.

## Component Architecture

```
TUIApp
├── <Static> (messages rendered once)
│   └── MessageItem[] (memoized)
├── ToolCallItem[] (live, re-render on status)
├── [Toggle Panels]
│   ├── ActiveAgentsPanel
│   ├── TasksPanel
│   ├── SwarmStatusPanel
│   ├── DebugPanel
│   └── DiagnosticsPanel
├── ApprovalDialog (shown when permission needed)
├── CommandPalette (shown on Ctrl+P)
├── StatusBar
└── MemoizedInputArea (single useInput hook)
```

## Auto-Loop Recovery

The TUI integrates with the incomplete-action auto-loop system. When the agent's response describes future work instead of performing it (detected as `future_intent` or `incomplete_action`), the TUI automatically re-sends a recovery prompt up to 2 times. A retry indicator appears in the status area during recovery.

## Input History

The input area supports command history navigation with up/down arrow keys. History is persisted via `HistoryManager` backed by SQLite, so previous commands survive across sessions.
