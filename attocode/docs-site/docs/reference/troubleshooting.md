---
sidebar_position: 4
title: "Troubleshooting"
---

# Troubleshooting

Common issues and their solutions when running Attocode.

## Provider Issues

### "No LLM provider configured"

The agent could not find any API key in the environment.

**Fix:** Set at least one provider key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENROUTER_API_KEY=sk-or-...
# or
export OPENAI_API_KEY=sk-...
```

### Provider timeout or rate limit

The LLM request timed out or was rate-limited.

**Fix:** The agent uses `resilient-fetch` with automatic retry (3 attempts, exponential backoff). If persistent, check your API plan limits or try a different provider. You can also configure `providerResilience` with a fallback chain.

### Wrong model being used

**Fix:** Check environment variables. If `OPENROUTER_MODEL` is set, it overrides the default. You can also set `model` in `.attocode/config.json`.

## TUI Issues

### TUI not rendering / garbled output

The TUI requires a terminal that supports Ink (React-based terminal rendering).

**Fix:**
- Ensure `process.stdout.isTTY` is true (not piped)
- Use a modern terminal emulator (iTerm2, Alacritty, Windows Terminal)
- If TUI fails, the agent falls back to REPL mode automatically

### Keyboard shortcuts not working

Some terminals intercept shortcuts like `Ctrl+P` or `Alt+T`.

**Fix:** Check your terminal's keyboard settings. Consider remapping conflicting shortcuts in your terminal emulator.

## Performance Issues

### Slow first parse

Tree-sitter language bindings load on first use per language. Initial parsing of a new language may take 1-2 seconds.

**Fix:** This is expected. Subsequent parses of the same language are fast.

### Large trace files filling disk

Trace files in `.traces/` grow without automatic rotation.

**Fix:** Manually clean old traces:

```bash
rm -rf .traces/*.jsonl
# or keep recent only
find .traces -name "*.jsonl" -mtime +7 -delete
```

### High memory usage

Long sessions accumulate context. The agent compacts automatically, but memory can still grow.

**Fix:** Start a new session for unrelated tasks. Use `/compact` to force context compaction.

## Session Issues

### Session resume fails

**Fix:**
- Verify `.agent/sessions/` directory exists and contains `sessions.db`
- Check file permissions on the SQLite database
- If the database is corrupted, remove it and start fresh (sessions will be lost)

### Checkpoints not saving

**Fix:** Ensure the SQLite store is initialized. Check disk space. The agent auto-checkpoints periodically; manual checkpoints use `/checkpoint`.

## Sandbox Issues

### "Sandbox not available"

Sandboxing is platform-specific:

| Platform | Sandbox | Requirement |
|----------|---------|-------------|
| macOS | Seatbelt | Built-in, no setup needed |
| Linux | Landlock | Kernel 5.13+ with Landlock enabled |
| Docker | Container | Docker daemon running |
| Windows | None | Not supported |

**Fix:** If your platform is not supported, the agent runs without sandboxing. Set `sandbox: false` to suppress the warning.

## Agent Behavior Issues

### Doom loop detected

The agent is repeating the same tool call with identical arguments 3+ times.

**Fix:** The economics system automatically injects nudges. If the agent remains stuck:
- Try rephrasing your task
- Use `/cancel` and restart with a different approach
- Break complex tasks into smaller pieces

### Budget exhausted

The agent hit its token or cost budget.

**Fix:**
- Use `/extend` to add more budget to the current session
- Start a new session
- Configure higher budgets in `ProductionAgentConfig.budget`

### Agent not using available tools

**Fix:**
- Check that tools are registered with `registry.list()`
- Verify tool descriptions are clear and specific
- Check if execution policy is blocking the tool (`policy.tool.blocked` events)
- For MCP tools, ensure the MCP server is running

## Build and Development Issues

### TypeScript compilation errors

**Fix:**
- Ensure Node.js 20+ is installed: `node --version`
- Run `npm install` to ensure dependencies are up to date
- Check `tsconfig.json` for correct settings

```bash
# Use the correct Node version
export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
npm run build
```

### Tests failing

**Fix:**
- Run `npm test` to see which tests fail
- 8 test files (41 tests) have known pre-existing failures -- see the [Known Issues](../internals/known-issues.md) page
- Ensure you are running Node.js 20+

### MCP server not connecting

MCP stdio communication has no health checking or automatic reconnection.

**Fix:**
- Verify the MCP server process is running
- Check the server's stderr output for errors
- Restart the agent to reinitialize MCP connections

## Getting Help

- Check `--debug` flag for verbose logging: `npx tsx src/main.ts --debug`
- Examine trace files in `.traces/` for detailed execution history
- Use the trace dashboard (`npm run dashboard`) for visual analysis
