# Architecture

## Module Relationships

```mermaid
flowchart TB
    subgraph Entry["Entry Points"]
        CLI[cli.py<br/>Click CLI]
    end

    subgraph Core["Core"]
        Agent[ProductionAgent<br/>agent/agent.py]
        Builder[AgentBuilder<br/>agent/builder.py]
        Registry[ToolRegistry<br/>tools/registry.py]
        Loop[ExecutionLoop<br/>core/loop.py]
    end

    subgraph Providers["LLM Providers"]
        Anthropic[Anthropic]
        OpenRouter[OpenRouter]
        OpenAI[OpenAI]
        ZAI[ZAI]
    end

    subgraph Tools["Built-in Tools"]
        FileOps[File Operations]
        BashTool[Bash Executor]
        SearchTools[Search Tools]
        SpawnAgent[Spawn Agent]
    end

    subgraph Integrations["Integrations"]
        Session[SQLiteStore<br/>Session Persistence]
        MCP[MCPClient<br/>External Tools]
        Context[ContextEngineering<br/>Compaction]
        Perms[PolicyEngine<br/>Approval System]
        Budget[Economics<br/>Budget Management]
        Recording[SessionGraph<br/>Recording]
        Skills[SkillLoader<br/>Skills System]
    end

    subgraph TUI["TUI Layer"]
        TUIApp[AttocodeApp<br/>Textual App]
        Bridges[ApprovalBridge<br/>BudgetBridge]
    end

    CLI --> Builder
    Builder --> Agent
    CLI --> TUIApp
    Agent --> Loop
    Agent --> Registry
    Agent --> Providers
    Registry --> Tools
    Registry --> Perms
    Agent --> Integrations
    TUIApp --> Bridges
    Bridges --> Perms
    MCP --> Registry
```

## Data Flow

```mermaid
sequenceDiagram
    participant User
    participant TUI as AttocodeApp
    participant Agent as ProductionAgent
    participant LLM as LLM Provider
    participant Tools as ToolRegistry
    participant Perms as PolicyEngine
    participant Store as SessionStore

    User->>TUI: Enter prompt
    TUI->>Agent: run(prompt)
    Agent->>Store: create_session()
    Agent->>LLM: chat(messages)
    LLM-->>Agent: tool_calls[]

    loop For each tool call
        Agent->>Tools: execute(tool, args)
        Tools->>Perms: evaluate(tool, args)
        alt Needs approval
            Perms->>TUI: requestApproval()
            User-->>TUI: Y/N
            TUI-->>Perms: response
        end
        Tools-->>Agent: result
        Agent->>Store: record_tool_call()
    end

    Agent->>LLM: chat(messages + results)
    LLM-->>Agent: response
    Agent->>Store: save_checkpoint()
    Agent-->>TUI: AgentResult
    TUI-->>User: Display response
```

## Directory Structure

| Directory | Purpose | Key Files |
|-----------|---------|-----------|
| `agent/` | Agent core orchestration | agent.py, builder.py, context.py |
| `core/` | Execution engine | loop.py, subagent_spawner.py |
| `tools/` | Tool implementations | 12 tool modules |
| `providers/` | LLM adapters | base.py, adapters/ |
| `integrations/` | Feature modules | 12 subdirectories |
| `tui/` | Terminal UI | app.py, 52+ widgets |
| `tracing/` | Execution traces | JSONL event recording |
| `tricks/` | Context engineering | Recitation, failure tracking |
| `types/` | Shared type definitions | agent.py, messages.py |

## Integration Domains

| Domain | Module Count | Lines | Purpose |
|--------|-------------|-------|---------|
| `budget/` | 6 | ~2,200 | Token economics, loop detection |
| `context/` | 8 | ~3,500 | Compaction, codebase analysis |
| `safety/` | 8 | ~2,000 | Sandboxes, policies, validators |
| `persistence/` | 1 | ~1,100 | SQLite session store |
| `agents/` | 5 | ~1,500 | Multi-agent coordination |
| `tasks/` | 6 | ~2,000 | Planning, decomposition |
| `skills/` | 4 | ~450 | Skill loading, deps, state |
| `mcp/` | 4 | ~800 | MCP client integration |
| `recording/` | 5 | ~1,400 | Session graph, playback |
| `swarm/` | 12 | ~10,300 | Multi-agent orchestration |
| `utilities/` | 27 | ~4,000 | Helper modules |
| `streaming/` | 1 | ~300 | PTY shell |
