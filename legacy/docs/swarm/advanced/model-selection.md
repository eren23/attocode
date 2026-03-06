# Model Selection

This guide explains how swarm mode auto-detects worker models, how capability matching works, and how to override model selection.

## Auto-Detection

When you don't specify workers in your config, swarm mode auto-detects models from OpenRouter's API.

### How It Works

1. **Fetch model catalog**: Queries `https://openrouter.ai/api/v1/models` using your `OPENROUTER_API_KEY`
2. **Filter for usable models**: Applies these criteria:
   - Context window >= 8,192 tokens (configurable via `minContextWindow`)
   - Combined cost per million tokens <= $5.00 (configurable via `maxCostPerMillion`)
   - Must support `tools` in `supported_parameters` (tool/function calling)
   - If `paid_only`: excludes models with zero prompt+completion cost or `:free` suffix
3. **Sort by cost**: Cheapest models first
4. **Assign to roles**: Provider-diverse selection for rate limit headroom

### Role Assignment

The auto-detector picks models for each role using a provider-diversity algorithm:

```
Coders (up to 3):
  1st pass: Models with 'coder' or 'deepseek' in ID, different providers
  2nd pass: Fill remaining slots from general models, different providers

Researchers (up to 2):
  Sorted by largest context window, different providers from coders

Documenter (1):
  Cheapest remaining model

Reviewer (1):
  Always uses the orchestrator model (needs quality for judgment)
```

The diversity algorithm ensures workers use models from different providers (e.g., Mistral, Google, Qwen) to avoid sharing rate limit pools.

### Provider Diversity Example

```
Auto-detected workers:
  coder:        mistralai/mistral-large-2512      (Mistral pool)
  coder-alt:    z-ai/glm-4.7-flash               (Z-AI pool)
  coder-alt2:   allenai/olmo-3.1-32b-instruct    (AllenAI pool)
  researcher:   moonshotai/kimi-k2.5-0127         (Moonshot pool)
  documenter:   mistralai/ministral-14b-2512      (Mistral pool, low usage)
  reviewer:     [orchestrator model]
```

Each provider has its own rate limit pool, so workers from different providers don't compete for the same limits.

## Capability Matching

When a task needs execution, the orchestrator matches it to a worker by capability.

### Task Type → Capability Mapping

| Task Type | Capability | Typical Worker |
|-----------|-----------|---------------|
| `implement` | `code` | coder |
| `refactor` | `code` | coder |
| `integrate` | `code` | coder |
| `deploy` | `code` | coder |
| `merge` | `code` | coder |
| `research` | `research` | researcher |
| `analysis` | `research` | researcher |
| `design` | `research` | researcher |
| `test` | `test` | tester (or coder fallback) |
| `review` | `review` | reviewer |
| `document` | `document` | documenter |

### Selection Algorithm

```
1. Find all workers with the required capability
2. If health tracker is available:
   a. Filter to healthy models only
   b. Round-robin among healthy matches (by task index)
3. Otherwise: round-robin among all matches
4. Fallback: any code-capable worker (for test/code tasks)
5. Last resort: first worker in the list
```

Round-robin ensures load distribution across models. The task index determines which worker in the rotation gets each task.

## Health Tracking

The `ModelHealthTracker` monitors each model's reliability in real-time.

### Metrics Tracked

| Metric | Description |
|--------|-------------|
| `successes` | Total successful task completions |
| `failures` | Total failures (any type) |
| `rateLimits` | Count of 429/402 errors |
| `lastRateLimit` | Timestamp of most recent rate limit |
| `averageLatencyMs` | Exponential moving average of response time |
| `healthy` | Current health status (boolean) |

### Health Assessment Rules

A model is marked **unhealthy** when:
- 2+ rate limits within the last 60 seconds
- Failure rate > 50% across last 3+ attempts

Unhealthy models are deprioritized in capability matching but not completely excluded (they may be the only option for a capability).

### Latency Tracking

Average latency uses an exponential moving average:
```
new_average = old_average * 0.7 + new_latency * 0.3
```

This weights recent measurements more heavily while smoothing out spikes.

## Model Failover

When a task fails due to a rate limit (429/402), the orchestrator can automatically switch to a different model.

### Failover Flow

```
1. Task fails with 429 or 402 error
2. Record failure in health tracker
3. If enableModelFailover is true:
   a. Find an alternative model with the same capability
   b. Prefer healthy models from different providers
   c. Update the task's assigned model
   d. Task will be retried with the new model
4. If no alternative found:
   a. Retry with the same model (with backoff)
```

### Alternative Selection

```
Priority 1: Healthy model with same capability, different provider
Priority 2: Any model with same capability, different from failed model
Priority 3: Same model (rely on backoff/retry)
```

## Hardcoded Fallbacks

When OpenRouter API auto-detection fails (network error, no key, no suitable models), the system falls back to hardcoded models:

| Worker | Model | Capabilities |
|--------|-------|-------------|
| coder | `mistralai/mistral-large-2512` | code, test |
| coder-alt | `z-ai/glm-4.7-flash` | code, test |
| coder-alt2 | `allenai/olmo-3.1-32b-instruct` | code, test |
| researcher | `moonshotai/kimi-k2.5-0127` | research, review |
| documenter | `mistralai/ministral-14b-2512` | document |
| reviewer | [orchestrator model] | review |

These fallbacks are chosen for provider diversity and cost-effectiveness.

## Manual Model Configuration

For full control, define workers explicitly in your config:

```yaml
workers:
  - name: coder
    model: anthropic/claude-sonnet-4
    capabilities: [code, refactor, test]
    persona: "You are a senior TypeScript developer."
    maxTokens: 50000
  - name: researcher
    model: google/gemini-2.0-flash-001
    capabilities: [research, review]
    contextWindow: 1000000
  - name: documenter
    model: mistralai/ministral-14b-2512
    capabilities: [document]
```

### Tips for Manual Selection

1. **Use different providers per worker** to avoid rate limit contention
2. **Match context window to task complexity**: Large context for research, smaller for focused coding
3. **Code-capable models should support tools**: Check `supported_parameters` includes `tools`
4. **Assign personas for specialization**: Workers with clear instructions produce better output
5. **Include at least one reviewer**: Quality depends on having a capable review model

## See Also

- [Configuration Guide](../configuration-guide.md) — Worker and model config options
- [Architecture Deep Dive](architecture-deep-dive.md) — Throttle and circuit breaker internals
