---
sidebar_position: 7
title: Data Flow
---

# Data Flow

This page traces the complete flow of data through the system, from user input to final response, including the permission and event subsystems.

## Main Request Flow

```mermaid
sequenceDiagram
    participant User
    participant TUI as TUIApp (Ink/React)
    participant Agent as ProductionAgent
    participant MB as Message Builder
    participant EL as Execution Loop
    participant LLM as LLM Provider
    participant TR as Tool Registry
    participant TE as Tool Executor

    User->>TUI: Enter prompt
    TUI->>Agent: run(prompt)
    Agent->>MB: buildMessages(task)
    MB-->>Agent: Message[] with system prompt

    Agent->>EL: executeDirectly(task, messages, ctx, mutators)

    loop ReAct Loop
        Note over EL: Pre-flight checks
        Note over EL: Context injection (recitation, failures)

        EL->>LLM: callLLM(messages)
        LLM-->>EL: ChatResponse

        Note over EL: Record budget usage

        alt Response has tool_calls[]
            EL->>TE: executeToolCalls(toolCalls, ctx)

            loop For each batch
                TE->>TR: registry.execute(tool, args)
                TR-->>TE: ToolResult
            end

            TE-->>EL: ToolResult[]
            Note over EL: Append results to messages
        else Text response (no tools)
            Note over EL: Completion checks
            EL-->>Agent: ExecutionLoopResult
        end
    end

    Agent-->>TUI: AgentResult
    TUI-->>User: Display response
```

## System Prompt Assembly

The `buildMessages()` function assembles the system prompt from multiple sources, ordered for optimal KV-cache reuse:

```mermaid
flowchart LR
    subgraph Static["Static Content (cached)"]
        SP["Base System Prompt"]
        Rules["Rules\n(.attocode/rules.md)"]
        Tools["Tool Descriptions\n(all registered tools)"]
        Skills["Active Skills Prompt"]
    end

    subgraph SemiStatic["Semi-Static Content"]
        Memory["Memory Context\n(episodic + semantic)"]
        Learnings["Cross-Session Learnings\n(up to 5)"]
        Codebase["Codebase Context\n(selected code snippets)"]
    end

    subgraph Dynamic["Dynamic Content"]
        Env["Environment Facts\n(OS, cwd, date)"]
        Scale["Scaling Guidance\n(model-specific)"]
        Complex["Complexity Assessment"]
    end

    Static --> Msg["System Message\nwith cache_control markers"]
    SemiStatic --> Msg
    Dynamic --> Msg
    Msg --> Messages["messages[0]"]
```

Static content uses `cache_control: { type: 'ephemeral' }` markers so the Anthropic API can reuse the KV-cache across conversation turns. The order matters: static content first, dynamic content last, to maximize cache prefix hits.

## Tool Execution Pipeline

Each tool call passes through a multi-stage pipeline:

```mermaid
flowchart TB
    TC["Tool Call\nfrom LLM response"]
    PM{{"Plan Mode?"}}
    TC --> PM

    PM -- Yes --> Queue["Queue for Approval\n(plan.change.queued event)"]
    PM -- No --> EP["Execution Policy Check"]

    EP --> Safety["Safety Validation\n(sandbox + danger level)"]
    Safety --> Perm{{"Needs Approval?"}}

    Perm -- Yes --> PermReq["Permission Request\n(approval.required event)"]
    PermReq --> TUI["TUI Permission Dialog"]
    TUI --> PermResp["Permission Response"]
    PermResp -- Granted --> BB
    PermResp -- Denied --> Blocked["Tool Blocked\n(tool.blocked event)"]

    Perm -- No --> BB["Blackboard\nFile Claim"]
    BB --> Cache{{"File Cache Hit?"}}

    Cache -- Yes --> CacheResult["Return Cached Result"]
    Cache -- No --> Exec["Execute Tool\ntool.execute(args)"]

    Exec --> Record["Record Result\n- Economics\n- Observability\n- File Cache\n- Failure Evidence"]
    Record --> Result["ToolResult"]
```

## Permission Flow

When a tool requires user approval, the request flows through the permission system:

```mermaid
sequenceDiagram
    participant TE as Tool Executor
    participant PC as PermissionChecker
    participant AB as ApprovalBridge
    participant TUI as TUI Dialog
    participant User

    TE->>PC: check(tool, args, dangerLevel)

    alt Already approved (session scope)
        PC-->>TE: granted
    else Needs approval
        PC->>AB: requestApproval(request)
        AB->>TUI: Show approval dialog
        TUI->>User: "Allow [tool]? (y/n/a)"

        alt User approves
            User->>TUI: y (once) or a (always)
            TUI->>AB: { granted: true, scope }
            AB->>PC: resolve(response)

            alt Scope is 'session'
                PC->>PC: Cache approval for session
            end

            PC-->>TE: granted
        else User denies
            User->>TUI: n
            TUI->>AB: { granted: false }
            AB->>PC: resolve(response)
            PC-->>TE: denied
        end
    end
```

Permission scope levels:
- **`once`**: Approval valid for this single tool call only
- **`session`**: Approval cached for the rest of the session (same tool + similar args)
- **`always`**: Persisted across sessions (stored in config)

## Event Flow

The agent emits events at every significant step. The TUI subscribes to these events to update its display:

```mermaid
flowchart LR
    subgraph Agent["ProductionAgent"]
        Emit["emit(event)"]
    end

    subgraph Listeners["Event Consumers"]
        TUI["TUI\nhandleAgentEvent()"]
        Obs["ObservabilityManager\nlog + trace"]
        Trace["TraceCollector\nJSONL recording"]
    end

    subgraph TUIState["TUI State Updates"]
        Msgs["Messages List\n(llm.complete, tool.complete)"]
        ToolUI["Tool Status\n(tool.start, tool.complete)"]
        AgentUI["Subagent Status\n(agent.spawn, agent.complete)"]
        TaskUI["Task Progress\n(task.start, task.complete)"]
        Tokens["Token Metrics\n(insight.tokens, insight.context)"]
        Status["Status Bar\n(mode.changed, compaction.*)"]
    end

    Emit --> TUI & Obs & Trace
    TUI --> Msgs & ToolUI & AgentUI & TaskUI & Tokens & Status
```

### Key Event Sequences

**Normal tool execution:**
1. `iteration.before` -- loop starts new iteration
2. `llm.start` -- calling the LLM
3. `llm.complete` -- response received with tool calls
4. `tool.start` -- beginning tool execution (one per tool)
5. `insight.tool` -- tool completed with duration and result summary
6. `tool.complete` -- tool finished
7. `insight.tokens` -- token usage for the LLM call
8. `iteration.after` -- iteration complete

**Subagent delegation:**
1. `agent.spawn` -- subagent created with task
2. `tool.start` (spawn_agent) -- the spawn tool is executing
3. (subagent runs its own event stream internally)
4. `agent.complete` -- subagent finished with result
5. `tool.complete` (spawn_agent) -- spawn tool returns result

**Budget warning flow:**
1. `insight.context` -- context usage approaching limit
2. `compaction.warning` -- token threshold crossed
3. `compaction.auto` -- automatic compaction triggered
4. `resilience.retry` -- budget recovery attempted
5. `resilience.recovered` or `error` -- recovery result

## Subagent Data Inheritance

When a subagent is spawned, it inherits shared state from its parent:

```mermaid
flowchart TB
    Parent["Parent Agent"]
    Child["Subagent"]

    Parent -- "SharedBlackboard\n(file claims, findings)" --> Child
    Parent -- "SharedFileCache\n(read deduplication)" --> Child
    Parent -- "SharedBudgetPool\n(token accounting)" --> Child
    Parent -- "TraceCollector\n(unified tracing)" --> Child
    Parent -- "CancellationToken\n(linked to parent)" --> Child
    Parent -- "ApprovalScope\n(inherited permissions)" --> Child
    Parent -- "SharedContextState\n(failure learning)" --> Child
    Parent -- "SharedEconomicsState\n(doom loop agg.)" --> Child
```

The subagent receives constrained budgets (`SUBAGENT_BUDGET`) and a linked cancellation token that fires when either the parent cancels or the subagent's own timeout expires. The graceful timeout system provides a wrapup phase before hard cancellation.

## Session Persistence Flow

Sessions are persisted to SQLite for resume capability:

```mermaid
sequenceDiagram
    participant Agent as ProductionAgent
    participant API as Session API
    participant Store as SQLiteStore
    participant DB as SQLite DB

    Note over Agent: Session ends or checkpoint triggered

    Agent->>API: getSerializableState()
    API-->>Agent: { messages, plan, metrics, ... }

    Agent->>Store: saveSession(sessionId, state)
    Store->>DB: INSERT INTO sessions

    Note over Agent: Later: resume session

    Agent->>Store: loadSession(sessionId)
    Store->>DB: SELECT FROM sessions
    Store-->>Agent: serialized state

    Agent->>API: loadState(state)
    API-->>Agent: Agent state restored
    Note over Agent: Continue from where we left off
```

Key tables:
- `sessions` -- session metadata (ID, creation time, status)
- `checkpoints` -- checkpoint data with full message arrays
- `learnings` -- cross-session learnings from failures
- `goals` -- goal tracking for multi-session work
