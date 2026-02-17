---
sidebar_position: 6
title: Skills & Agents
---

# Skills & Agents

Attocode supports user-defined skills and agents through the `.attocode/` directory system. Skills provide specialized capabilities via markdown instructions, while agents are spawnable subagent definitions with custom models, tools, and prompts.

## Directory Structure

```
~/.attocode/                    # User-level (global)
├── skills/
│   └── my-skill/
│       └── SKILL.md
└── agents/
    └── my-agent/
        └── AGENT.yaml

.attocode/                      # Project-level (overrides user-level)
├── skills/
│   └── project-skill/
│       └── SKILL.md
└── agents/
    └── project-agent/
        └── AGENT.yaml
```

### Priority Hierarchy

Later sources override earlier ones:

1. **Built-in** (lowest) -- Ships with Attocode in `src/skills/`
2. **User-level** -- `~/.attocode/skills/` and `~/.attocode/agents/`
3. **Project-level** (highest) -- `.attocode/skills/` and `.attocode/agents/`
4. **Legacy paths** -- `.agent/skills/` and `.agent/agents/` still work for backward compatibility

## Skills

Skills are markdown files with YAML frontmatter that provide specialized instructions for the agent. They live in `<dir>/skills/<name>/SKILL.md` (or `skill.md`).

### Skill Definition

```markdown
---
name: code-review
description: Thorough code review with security focus
tools: [read_file, search_files, search_content]
tags: [review, security]
invokable: true
arguments:
  - name: file
    description: File to review
    type: file
    required: true
  - name: focus
    description: Review focus area
    type: string
    default: general
triggers:
  - type: keyword
    pattern: review
---

Review the specified file for security vulnerabilities,
error handling gaps, and performance issues.
```

### Skill Types

| Type | Behavior |
|------|----------|
| **Invokable** | Triggered via `/skillname` command. Arguments are parsed from the command line. |
| **Passive** | Always loaded into the agent's context when active. No explicit invocation needed. |
| **Available** | Loaded but not active. Can be activated with `/skills enable <name>`. |

### Skill Triggers

Skills can auto-activate based on context:

| Trigger Type | Example | When |
|-------------|---------|------|
| `keyword` | `pattern: "review"` | User message contains the keyword |
| `file_pattern` | `pattern: "*.test.ts"` | File matching the glob is referenced |
| `context` | `pattern: "security"` | Context contains the pattern |

### Execution Modes

- **Prompt injection** (default) -- The skill's markdown content is injected into the agent's next prompt, steering behavior without taking over execution
- **Workflow** -- Multi-step execution where each step runs sequentially with checkpoint support

### Skill Commands

```
/skills                    # List all skills with source and status
/skills new review         # Create scaffold at .attocode/skills/review/SKILL.md
/skills info review        # Show metadata, arguments, triggers
/skills enable review      # Activate the skill
/skills disable review     # Deactivate the skill
```

### SkillExecutor

When an invokable skill is triggered via `/skillname`, the `SkillExecutor` handles:

1. **Argument parsing** -- Flags (`--file src/main.ts`) and positional args are parsed into named/positional buckets
2. **Validation** -- Required arguments checked, types verified
3. **Template substitution** -- `{{file}}` placeholders in the skill content are replaced with argument values
4. **Execution** -- The processed content is injected as a prompt or executed as a workflow

## Agents

Agents are spawnable subagent definitions written in YAML. They live in `<dir>/agents/<name>/AGENT.yaml`.

### Agent Definition

```yaml
name: architect
description: System architecture analysis and design
model: quality
systemPrompt: |
  You are a senior software architect. Analyze codebases
  for structural issues and propose improvements.
tools: [read_file, search_files, list_files]
capabilities: [architecture, design-patterns, refactoring]
maxTokenBudget: 100000
timeout: 300000
allowMcpTools: false
```

### Agent Schema

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique agent identifier |
| `description` | string | What the agent does |
| `model` | string | `fast`, `balanced`, `quality`, or a specific model ID |
| `systemPrompt` | string | Custom system instructions |
| `tools` | string[] | Whitelist of tool names (all tools if omitted) |
| `capabilities` | string[] | Used for natural language agent matching |
| `tags` | string[] | Additional discovery tags |
| `maxTokenBudget` | number | Token budget for the agent |
| `maxIterations` | number | Maximum ReAct loop iterations |
| `timeout` | number | Timeout in milliseconds |
| `allowMcpTools` | boolean or string[] | `true` = all MCP tools, `false` = none, or specific names |
| `policyProfile` | string | Named execution policy profile |
| `idleTimeout` | number | Time without tool calls before kill (ms) |
| `economicsTuning` | object | Override doom loop and exploration thresholds |

### Built-in Agents

Attocode ships with several built-in agents:

- **researcher** -- Explores codebases and gathers information
- **coder** -- Implements features and fixes bugs
- **reviewer** -- Reviews code for quality and issues
- **architect** -- Analyzes system design and structure

### Agent Commands

```
/agents                    # List all agents with source and model
/agents new deployer       # Create scaffold at .attocode/agents/deployer/AGENT.yaml
/agents info architect     # Show full definition and capabilities
/spawn architect "analyze the auth module"   # Spawn the agent with a task
/find security             # Search agents by keyword
/suggest "add caching"     # AI-powered agent suggestion
/auto "fix the login bug"  # Auto-route to best agent
```

### Agent Lifecycle

When spawned, the `AgentRegistry` looks up the definition and creates a subagent session (`sessionType: 'subagent'`). The subagent runs with its own token budget, tool whitelist, and system prompt. On completion, a `StructuredClosureReport` is returned with findings, actions taken, failures, and remaining work. Output is stored in `SubagentOutputStore` for later retrieval.

## Source Files

| File | Purpose |
|------|---------|
| `src/integrations/skills/skills.ts` | SkillManager, Skill type, directory discovery |
| `src/integrations/skills/skill-executor.ts` | SkillExecutor, argument parsing, template substitution |
| `src/integrations/agents/agent-registry.ts` | AgentRegistry, AgentDefinition, spawn/discovery |
| `src/commands/skills-commands.ts` | `/skills` command handlers |
| `src/commands/agents-commands.ts` | `/agents` command handlers |
