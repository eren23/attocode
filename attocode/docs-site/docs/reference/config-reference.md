---
sidebar_position: 1
title: "Configuration Reference"
---

# Configuration Reference

Attocode is configured through `ProductionAgentConfig` in code, `.attocode/config.json` for project settings, and `~/.attocode/config.json` for global defaults.

## Environment Variables

| Variable | Provider | Required |
|----------|----------|----------|
| `ANTHROPIC_API_KEY` | Anthropic Claude | For Anthropic provider |
| `OPENROUTER_API_KEY` | OpenRouter | For OpenRouter provider |
| `OPENAI_API_KEY` | OpenAI | For OpenAI provider |
| `OPENROUTER_MODEL` | OpenRouter | Model override |

Provider detection priority: OpenRouter (0) > Anthropic (1) > OpenAI (2) > Mock (100).

## Core Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `provider` | `LLMProvider` | (required) | LLM provider instance |
| `tools` | `ToolDefinition[]` | (required) | Available tools |
| `systemPrompt` | `string` | Built-in | System prompt for the agent |
| `model` | `string` | Provider default | Model to use |
| `maxTokens` | `number` | Provider default | Max tokens per LLM response |
| `temperature` | `number` | Provider default | Sampling temperature |
| `maxIterations` | `number` | 100 | Maximum ReAct loop iterations |
| `maxContextTokens` | `number` | 200000 | Context window before compaction |
| `timeout` | `number` | 120000 | Request timeout in ms |
| `workingDirectory` | `string` | `process.cwd()` | Base directory for file operations |

## Feature Flags

Every feature can be set to `false` to explicitly disable it, or configured with an options object. Omitting the key uses defaults.

### Hooks (`hooks`)

```typescript
hooks?: HooksConfig | false;
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | true | Enable/disable hooks |
| `builtIn.logging` | boolean | true | Built-in logging hook |
| `builtIn.metrics` | boolean | true | Built-in metrics hook |
| `builtIn.timing` | boolean | true | Built-in timing hook |
| `custom` | Hook[] | [] | Custom hook handlers |
| `shell` | HookShellConfig | - | Shell hook configuration |

### Planning (`planning`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | true | Enable planning |
| `autoplan` | boolean | true | Auto-plan for complex tasks |
| `complexityThreshold` | number | 3 | Complexity score to trigger planning |
| `maxDepth` | number | 3 | Maximum plan nesting depth |
| `allowReplan` | boolean | true | Re-plan on failure |

### Sandbox (`sandbox`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | true | Enable sandboxing |
| `type` | string | Auto-detect | `seatbelt` (macOS), `landlock` (Linux), `docker`, `basic` |

### Routing (`routing`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | false | Enable model routing |
| `strategy` | string | `balanced` | `cost`, `quality`, `latency`, `balanced`, `rules` |
| `models` | ModelConfig[] | [] | Available models |
| `fallbackChain` | string[] | [] | Fallback model order |
| `circuitBreaker` | boolean | true | Enable circuit breaker |

### Observability (`observability`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tracing.enabled` | boolean | true | Enable tracing |
| `tracing.exporter` | string | `console` | `console`, `otlp`, `custom` |
| `metrics.collectTokens` | boolean | true | Track token usage |
| `metrics.collectCosts` | boolean | true | Track costs |
| `traceCapture.enabled` | boolean | false | Full trace capture to JSONL |
| `traceCapture.outputDir` | string | `.traces/` | Trace output directory |

### Subagent (`subagent`)

Controls subagent spawning behavior including timeout, iteration limits, and budget allocation.

### Provider Resilience (`providerResilience`)

Configures circuit breakers, fallback chains, and retry policies at the provider level.

### Other Features

| Config Key | Feature |
|------------|---------|
| `plugins` | Plugin system |
| `rules` | Rules/instructions loading |
| `memory` | Episodic/semantic/working memory |
| `reflection` | Self-critique after responses |
| `humanInLoop` | Approval dialogs |
| `multiAgent` | Multi-agent coordination |
| `react` | ReAct pattern configuration |
| `executionPolicy` | Tool execution policies |
| `policyEngine` | Unified policy engine |
| `threads` | Thread management (fork/switch) |
| `cancellation` | Graceful cancellation support |
| `resources` | Resource monitoring |
| `lsp` | Language Server Protocol |
| `semanticCache` | Embedding-based response cache |
| `skills` | Skill system |
| `codebaseContext` | Intelligent code selection |
| `interactivePlanning` | Conversational planning |
| `compaction` | Context compaction |
| `learningStore` | Cross-session learning |
| `resilience` | LLM empty response retry |
| `fileChangeTracker` | Undo capability |
| `swarm` | Swarm orchestration mode |

## Config File Format

`.attocode/config.json` (project-level):

```json
{
  "model": "claude-sonnet-4-20250514",
  "provider": "anthropic",
  "maxIterations": 50,
  "sandbox": { "type": "seatbelt" },
  "planning": { "autoplan": true }
}
```

`~/.attocode/config.json` follows the same schema but applies globally. Project config overrides global config.
