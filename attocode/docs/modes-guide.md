# Execution Modes Guide

Attocode supports 5 execution modes. This guide covers what each mode can and cannot do, how to activate it, and when to use it.

## Overview

| Mode | Activation | Best For | Limitations |
|------|-----------|----------|-------------|
| **Normal (TUI)** | `attocode` (default) | Interactive coding, conversation | Single-model, sequential execution |
| **Legacy (REPL)** | `--legacy` or `--no-tui` | CI/CD, piped input, non-TTY | No visual features, no keyboard shortcuts |
| **Plan** | Automatic (agent-initiated) | Complex tasks requiring design upfront | Read-only, no file writes or destructive ops |
| **Subagent** | `/spawn` or LLM-initiated | Delegating specialized subtasks | No direct user interaction, depth-limited |
| **Swarm** | `--swarm` | Parallel multi-model execution | No interactive iteration, batch-only |

---

## 1. Normal Mode (TUI)

The default interactive mode, built with Ink (React for terminals).

### Activation

```bash
attocode              # Default — starts TUI
attocode --tui        # Explicitly force TUI mode
```

### What You CAN Do

- **Interactive chat** — Multi-turn conversation with full context
- **File operations** — Read, write, edit, search files
- **Bash execution** — Run commands with permission checks
- **MCP tools** — Use external tools via Model Context Protocol
- **Slash commands** — `/help`, `/save`, `/load`, `/compact`, `/checkpoint`, `/undo`, etc.
- **Skills & agents** — `/spawn`, `/skills`, `/agents`
- **Thread management** — Fork, switch, merge conversation branches
- **Keyboard shortcuts** — See table below

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+C` | Exit attocode |
| `Ctrl+L` | Clear screen |
| `Ctrl+P` | Command palette / help |
| `ESC` | Cancel current operation |
| `Alt+T` | Toggle tool call detail display |
| `Alt+O` | Toggle thinking/reasoning display |
| `Alt+W` | Toggle swarm status panel |

### What You CANNOT Do

- **Parallel task execution** — Use swarm mode for that
- **Resume across restarts** — Use `/save` to persist, `/load` to restore

---

## 2. Legacy / REPL Mode

A simpler readline-based interface for environments where the TUI isn't suitable.

### Activation

```bash
attocode --legacy     # Force legacy mode
attocode --no-tui     # Same as --legacy
```

Also activates automatically when:
- Standard input is not a TTY (piped input)
- The `TERM` environment variable indicates a dumb terminal

### When to Use

- **CI/CD pipelines** — Non-interactive task execution
- **Piped input** — `echo "Fix the bug" | attocode --legacy`
- **Remote/minimal terminals** — When Ink rendering doesn't work

### Differences from TUI

- Same agent capabilities (file ops, bash, MCP, etc.)
- No keyboard shortcuts (Ctrl+P, Alt+T, etc.)
- No visual panels (swarm status, debug, tasks)
- No approval dialogs — uses simple Y/N prompts
- No command palette

---

## 3. Plan Mode

A restricted mode where the agent can explore and design but not make changes. The agent enters plan mode autonomously when it determines a task needs upfront design.

### How It Activates

The agent enters plan mode based on task complexity signals:
- Multi-file changes likely needed
- Architectural decisions required
- Ambiguous requirements that need exploration first

The agent can also be instructed to plan: "Plan how you would implement X."

### What You CAN Do

- **Read files** — `read_file`, `glob`, `grep`, `search_files`, `search_code`
- **Safe bash commands** — Commands matching a strict allowlist:

| Safe Patterns | Examples |
|--------------|----------|
| File inspection | `ls`, `cat`, `head`, `tail`, `wc`, `file`, `stat`, `du` |
| Git read-only | `git status`, `git log`, `git diff`, `git branch` |
| Search | `find`, `grep`, `rg` |
| Package info | `npm list`, `npm info` |

- **Plan output** — Write structured plans with steps, dependencies, and rationale

### What You CANNOT Do

- **Write or edit files** — `write_file`, `edit_file` are blocked
- **Destructive bash** — `rm`, `mv`, `git commit`, `git push`, `npm install`, etc.
- **Piped commands with dangerous suffixes** — `find ... -exec rm`, `cat | bash`, etc.
- **Create commits or push** — All git write operations are blocked

### How to Exit

1. The agent calls `ExitPlanMode` when the plan is ready
2. You review and approve or reject the plan
3. If approved, the agent switches to action mode and executes the plan

---

## 4. Subagent Mode

Delegated execution where the main agent spawns specialized child agents for focused tasks.

### Activation

```bash
# Manual — via slash command
/spawn researcher "Find all API endpoints and document their signatures"
/spawn coder "Implement the authentication middleware"
/spawn reviewer "Review the changes in src/auth/"

# Automatic — the LLM decides to delegate
# (The agent has a spawn_agent tool and uses it autonomously)
```

### Agent Types

**Built-in agents:**

| Type | Specialization | Default Timeout |
|------|---------------|-----------------|
| `coder` | Code implementation | 300s |
| `researcher` | Information gathering, analysis | 420s |
| `reviewer` | Code review, quality assessment | 180s |
| `tester` | Test writing, verification | 300s |

**Custom agents:** Define in `.attocode/agents/<name>/AGENT.yaml` or `~/.attocode/agents/`.

### What Subagents CAN Do

- **Full tool access** — Filtered by agent type (e.g., researchers get search tools, coders get file ops)
- **Independent context** — Own conversation history, separate from parent
- **MCP tools** — Access to connected MCP servers (configurable via `allowMcpTools`)
- **Auto-compaction** — Subagents compact their own context at 80% of 80K tokens

### What Subagents CANNOT Do

- **Interact with the user** — No approval prompts, no questions
- **Unlimited spawning** — Depth-limited to prevent runaway recursion
- **Exceed budget** — Tokens drawn from a shared pool bounded by the parent's budget

### Budget & Lifecycle

- **Shared budget pool** — Parent reserves 25% for synthesis; remaining 75% shared across children
- **Graceful timeout** — Warning at 80% of time limit, wrapup requested, then force-stopped
- **Results** — Returned to parent as structured reports with findings, actions, and failures

---

## 5. Swarm Mode

Parallel multi-model orchestration where one orchestrator decomposes tasks into a DAG of subtasks, dispatches them across waves of cheap/free worker models, validates via quality gates, and synthesizes results.

### Activation

```bash
# Auto-detect worker models from OpenRouter
attocode --swarm "Build a parser with tests"

# Use a custom config file
attocode --swarm .attocode/swarm.yaml "Refactor auth module"

# Paid models only (higher rate limits, better quality)
attocode --swarm --paid-only "Implement login"

# Resume a previous swarm session
attocode --swarm-resume <session-id>
```

### What You CAN Do

- **Parallel multi-model execution** — Multiple workers running simultaneously
- **Quality gates** — Automated validation of worker outputs
- **Wave-based ordering** — Dependency-aware task scheduling
- **Manager review** — Post-wave review with fix-up task injection
- **Integration verification** — Automated bash-based integration tests
- **Resume** — Continue from last checkpoint on failure

### What You CANNOT Do

- **Interactive iteration** — No mid-run conversation or steering
- **Mid-run changes** — Task decomposition is fixed after the planning phase
- **Fine-grained control** — Individual worker outputs aren't editable during execution

### Key Flags

| Flag | Description |
|------|-------------|
| `--swarm [CONFIG]` | Enable swarm mode, optionally with a config file path |
| `--swarm-resume ID` | Resume a previous swarm session from checkpoint |
| `--paid-only` | Exclude free-tier models from auto-detection |
| `--permission MODE` | Set permission mode (`auto-safe` recommended for swarm) |
| `--trace` | Capture execution trace for dashboard visualization |

For full configuration details, see the [Swarm Configuration Guide](swarm/configuration-guide.md).

---

## Combining Modes with Flags

These flags can be combined with any execution mode:

| Flag | Effect | Works With |
|------|--------|-----------|
| `--debug` | Verbose logging (LLM calls, tool args, timing) | All modes |
| `--trace` | Capture execution trace to `.traces/` | All modes |
| `--model MODEL` | Override the default model | All modes |
| `--permission MODE` | Set permission level | All modes |
| `--max-iterations N` | Cap agent iterations | All modes |
| `--theme THEME` | UI theme (dark, light, auto) | TUI only |

### Valid Combinations

```bash
# TUI + debug + trace
attocode --debug --trace

# Swarm + paid models + tracing + auto-safe permissions
attocode --swarm --paid-only --trace --permission auto-safe "task"

# Legacy + specific model + strict permissions
attocode --legacy -m anthropic/claude-opus-4 --permission strict "task"

# Swarm resume + debug
attocode --swarm-resume abc123 --debug
```

### Trace Dashboard

When `--trace` is enabled in any mode, you can visualize execution in the web dashboard:

```bash
# Terminal 1: Run with tracing
attocode --trace

# Terminal 2: Start the dashboard
cd tools/trace-dashboard && npm run dashboard
```

The dashboard provides session timelines, token flow charts, issue detection, and (in swarm mode) task DAG visualization and worker timelines.
