# Troubleshooting

Common issues and how to resolve them.

## API Key Errors

**Symptom:** `ProviderError: Authentication failed` or `401 Unauthorized`

**Fix:**

```bash
# Check your API key is set
echo $ANTHROPIC_API_KEY

# Set it if missing
export ANTHROPIC_API_KEY="sk-ant-..."

# For other providers
export OPENROUTER_API_KEY="sk-or-..."
export OPENAI_API_KEY="sk-..."
export ZAI_API_KEY="..."
```

Or run the setup wizard:

```
/setup
```

## Rate Limits

**Symptom:** `ProviderError: Rate limit exceeded` or `429 Too Many Requests`

**Causes:**

- Too many API calls in a short period
- Exceeding token-per-minute limits
- Multiple concurrent sessions

**Fixes:**

1. Wait and retry — Attocode has built-in retry with exponential backoff
2. Use a different model — Switch to a less congested model
3. Enable the resilient provider — Automatic retry + circuit breaker

```bash
# Switch model mid-session
/model claude-haiku-4-5-20251001
```

## Budget Exhaustion

**Symptom:** Agent stops working, message says "Budget exhausted"

**Causes:**

- Token budget exceeded
- Cost limit reached
- Duration limit exceeded

**Fixes:**

```
/budget                  # Check current budget status
/extend                  # Request a budget extension
/extend 100000           # Request specific token amount
```

Budget presets for reference:

| Preset | Max Tokens | Max Cost | Duration |
|--------|-----------|----------|----------|
| QUICK | 50K | $0.50 | 5 min |
| STANDARD | 200K | $2.00 | 30 min |
| DEEP | 500K | $5.00 | 60 min |
| LARGE | 1M | $10.00 | 120 min |

## Doom Loop Detection

**Symptom:** Warning message "Doom loop detected" or "Same tool called 3+ times with identical args"

**What's happening:** The agent is calling the same tool with the same arguments repeatedly without making progress.

**Fixes:**

1. **The agent should self-correct** — The doom loop detector injects a nudge prompting a different approach
2. **Manual intervention** — Press `Escape` to cancel, then give the agent different instructions
3. **Check the task** — The task may be impossible or need clarification

```
# Cancel current operation
[Press Escape]

# Give new direction
"Try a different approach. Instead of X, do Y."
```

## Context Overflow

**Symptom:** Messages about "context overflow" or "emergency truncation", or the agent seems to forget earlier context

**Causes:**

- Very long sessions with many tool calls
- Large file reads consuming context space
- No compaction triggered

**Fixes:**

```
/compact                 # Manually trigger compaction
/status                  # Check context usage percentage
```

The auto-compaction system should handle this automatically:

- Warning at 70% context usage
- Auto-compact at 80%
- Emergency truncation if needed

If compaction isn't working, check that it's enabled:

```bash
attocode --debug "task"   # Check debug logs for compaction events
```

See [Context Engineering](context-engineering.md) for details on how compaction works.

## Sandbox Permission Errors

**Symptom:** `ToolError: Permission denied` when running bash commands, or commands silently fail

**Causes:**

- Sandbox blocking the command
- Write path not in allowed list
- Network access blocked

**Fixes:**

```
/sandbox                 # Check current sandbox configuration
```

If a command is being incorrectly blocked:

```bash
# Run with more permissive sandbox
attocode --permission auto-safe "task"

# Or check sandbox mode
# .attocode/config.json
{
  "sandbox": {
    "mode": "auto",
    "writable_paths": ["."],
    "readable_paths": ["/"],
    "network_allowed": false
  }
}
```

Platform-specific sandbox implementations:

| Platform | Sandbox | Notes |
|----------|---------|-------|
| macOS | Seatbelt | Uses `sandbox-exec` profiles |
| Linux 5.13+ | Landlock | Kernel-level filesystem restrictions |
| Any | Docker | Full container isolation |
| Fallback | Basic | Allowlist/blocklist validation |

## Agent Stuck Patterns

### Agent keeps reading the same file

The agent is likely confused about the file contents or looking for something specific.

**Fix:** Give explicit direction:

```
"Stop reading that file. The function you're looking for is in src/auth/handlers.py at line 42."
```

### Agent not making progress after many iterations

Check the iteration count and phase:

```
/status
```

If the agent has done 10+ iterations of exploration without edits, it may need a nudge:

```
"You've explored enough. Start implementing the changes now."
```

### Agent producing empty or malformed responses

**Causes:**

- Context window too full
- Model hitting output limits
- Network issues

**Fixes:**

```
/compact                 # Free up context space
/model claude-sonnet-4-20250514   # Switch to a different model
```

## Debug Mode

Enable detailed logging to diagnose issues:

```bash
attocode --debug "task description"
```

Debug mode outputs:

- LLM request/response details
- Tool execution timing
- Budget calculations
- Context engineering decisions
- Permission checks

## Tracing for Post-Hoc Analysis

Enable tracing to capture everything for later analysis:

```bash
attocode --trace "task description"
```

Then analyze the trace:

```python
from attocode.tracing.analysis import SessionAnalyzer, InefficiencyDetector

# Load and analyze
analyzer = SessionAnalyzer(trace_session)
issues = InefficiencyDetector(trace_session).detect()

for issue in issues:
    print(f"[{issue.severity}] {issue.title}: {issue.suggestion}")
```

Or use the built-in dashboard (`Ctrl+D` in TUI mode) to browse traces visually.

See [Tracing Guide](tracing-guide.md) for full details.

## Common Error Types

| Error | Category | Retryable | Description |
|-------|----------|-----------|-------------|
| `LLMError` | LLM | Sometimes | Empty or malformed LLM response |
| `ProviderError` | Provider | Yes | Rate limit, network, auth issues |
| `ToolError` | Tool | No | Tool execution failure |
| `ToolNotFoundError` | Tool | No | Unknown tool name |
| `ToolTimeoutError` | Tool | Sometimes | Tool exceeded timeout |
| `BudgetExhaustedError` | Budget | No | Token/cost/time budget exceeded |
| `CancellationError` | Cancellation | No | User cancelled operation |
| `PermissionDeniedError` | Permission | No | Tool access denied |
| `ConfigurationError` | Config | No | Invalid configuration |

## Getting Help

```
/help                    # Show available commands
/powers                  # Show agent capabilities
/status                  # Current session metrics
/budget                  # Budget details
/audit                   # Permission audit log
/grants                  # View active permission grants
```

## Related Pages

- [TUI Interface](tui-guide.md) — Keyboard shortcuts and panels
- [Budget System](BUDGET.md) — Budget management details
- [Sandbox](SANDBOX.md) — Sandbox configuration
- [Context Engineering](context-engineering.md) — Context management
