---
sidebar_position: 4
title: "Custom Agents"
---

# Custom Agents

Attocode supports user-defined agent types that can be spawned as subagents for specialized tasks. Agents are defined in YAML files and loaded by the `AgentRegistry`.

## Agent Definition

Create an `AGENT.yaml` file in a named directory:

```
.attocode/agents/security-auditor/
  AGENT.yaml
```

```yaml
name: security-auditor
description: Audits code for security vulnerabilities and compliance issues
systemPrompt: |
  You are a security auditor. Analyze code for:
  - Injection vulnerabilities (SQL, XSS, command injection)
  - Authentication and authorization flaws
  - Sensitive data exposure
  - Insecure dependencies
  Report findings with severity ratings (critical/high/medium/low).

model: quality
tools:
  - read_file
  - grep
  - glob
  - bash

capabilities:
  - security
  - audit
  - compliance

tags:
  - security
  - review

maxTokenBudget: 50000
maxIterations: 30
timeout: 120000

allowMcpTools: false
```

## YAML Schema

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique identifier |
| `description` | string | What this agent does |
| `systemPrompt` | string | System prompt injected into the agent |
| `model` | `fast`, `balanced`, `quality`, or model ID | Model selection |
| `tools` | string[] | Tool whitelist (all tools if omitted) |
| `capabilities` | string[] | Used for natural-language agent selection |
| `tags` | string[] | Additional metadata for discovery |
| `maxTokenBudget` | number | Token budget for the agent |
| `maxIterations` | number | Maximum ReAct loop iterations |
| `timeout` | number | Hard timeout in milliseconds |
| `allowMcpTools` | `true`, `false`, or string[] | MCP tool access control |
| `policyProfile` | string | Named execution policy profile |
| `taskType` | string | Hint for policy/tool resolution |
| `idleTimeout` | number | Kill agent after this many ms without tool calls |
| `economicsTuning` | object | Override doom loop/exploration thresholds |

## Built-in Agent Types

The registry ships with several built-in agents:

| Type | Purpose |
|------|---------|
| `researcher` | Explores codebases and gathers information |
| `coder` | Implements features and writes code |
| `reviewer` | Reviews code for quality and correctness |
| `architect` | Designs system architecture and structure |
| `debugger` | Diagnoses and fixes bugs |
| `documenter` | Writes documentation and comments |

## Spawning Agents

Agents can be spawned in two ways:

### Via the spawn_agent Tool

The LLM autonomously decides to delegate work:

```
spawn_agent(type: "security-auditor", task: "Audit the authentication module in src/auth/")
```

### Via the /spawn Command

The user explicitly spawns an agent:

```
/spawn security-auditor Audit src/auth/ for OWASP Top 10 vulnerabilities
```

The spawn result includes:

```typescript
interface SpawnResult {
  success: boolean;
  output: string;
  metrics: { tokens: number; duration: number; toolCalls: number };
  structured?: StructuredClosureReport;
  filesModified?: string[];
}
```

## Discovery Hierarchy

Agents are loaded from multiple directories with increasing priority:

1. **Built-in** -- hardcoded in `agent-registry.ts`
2. **User** (`~/.attocode/agents/`) -- user-global agents
3. **Project** (`.attocode/agents/`) -- project-specific agents

Project agents override user agents, which override built-in agents of the same name.

## Management Commands

```
/agents            # List all agents with models and sources
/agents new name   # Create agent scaffold
/agents info name  # Show detailed agent info
```

## Subagent Lifecycle

When a custom agent is spawned:

1. The `AgentRegistry` resolves the agent definition
2. A new `ProductionAgent` instance is created with the agent's config
3. The subagent inherits the parent's blackboard, file cache, and shared state
4. Budget constraints from the definition are applied
5. The subagent runs its ReAct loop until completion, timeout, or budget exhaustion
6. Graceful wrapup: the agent gets a warning before hard timeout, allowing it to produce a structured closure report
7. Results flow back to the parent agent

## Example: Creating a Test Writer Agent

```yaml
name: test-writer
description: Generates comprehensive test suites for existing code
systemPrompt: |
  You are a test writing specialist. Given source code:
  1. Analyze the code to identify testable units
  2. Write tests covering happy paths, edge cases, and error conditions
  3. Use the project's existing test framework and patterns
  4. Ensure tests are runnable with `npm test`

model: balanced
tools:
  - read_file
  - write_file
  - bash
  - grep
  - glob

capabilities:
  - testing
  - code-generation

maxIterations: 25
maxTokenBudget: 40000
```
