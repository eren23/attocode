# Troubleshooting Guide

Common issues and their solutions.

## API Key Issues

### "Provider not configured" or "API key not found"

**Symptoms:** Agent fails to start or returns authentication errors.

**Solution:** Ensure your API key is set in the environment:

```bash
# Check if key is set
echo $ANTHROPIC_API_KEY
echo $OPENROUTER_API_KEY
echo $OPENAI_API_KEY

# Set for current session
export ANTHROPIC_API_KEY="sk-ant-..."

# Add to shell profile for persistence
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
source ~/.zshrc
```

### "Authentication failed" (401 errors)

**Symptoms:** API calls fail with 401 status.

**Causes:**
- Invalid API key
- Expired API key
- Wrong key format

**Solution:** Verify your key at the provider's dashboard:
- Anthropic: https://console.anthropic.com/
- OpenRouter: https://openrouter.ai/keys
- OpenAI: https://platform.openai.com/api-keys

## Context Length Issues

### "Context length exceeded" errors

**Symptoms:** Agent fails mid-session with context errors.

**Solutions:**

1. **Use `/compact` command** to reduce context:
   ```
   /compact
   ```

2. **Start a new session** if context is too large:
   ```
   /clear
   ```

3. **Check context status:**
   ```
   /status
   ```

## MCP Server Issues

### MCP servers not connecting

**Symptoms:** MCP tools not appearing in `/mcp tools`.

**Check:**

1. **Verify config file syntax:**
   ```bash
   cat .mcp.json
   # or
   cat ~/.config/attocode/mcp.json
   ```

2. **Ensure valid JSON:**
   ```bash
   npx jsonlint .mcp.json
   ```

3. **Check server process can run:**
   ```bash
   npx -y @anthropic/mcp-server-filesystem /tmp
   ```

### Environment variables not expanding

**Symptoms:** `${VAR_NAME}` appears literally instead of value.

**Solution:** Ensure variables are exported:
```bash
export GITHUB_TOKEN="your-token"
```

## TUI Issues

### TUI not rendering correctly

**Symptoms:** Display corruption, missing elements.

**Solutions:**

1. **Use legacy mode:**
   ```bash
   attocode --legacy
   ```

2. **Check terminal size:**
   The TUI requires minimum width. Resize your terminal.

3. **Reset terminal:**
   ```bash
   reset
   ```

### Keyboard shortcuts not working

**Symptoms:** Alt+T, Alt+O don't respond.

**Note:** Alt shortcuts may conflict with terminal or OS settings. On macOS, Terminal.app may intercept Option key. Try:
- iTerm2 with "Option as Meta" enabled
- Or use the command equivalents instead

### Run shows `[INCOMPLETE]` or stops early

**Symptoms:** You see `[INCOMPLETE]` / `[RUN FAILED]` after model says "I will fix this..." without actually doing it.

**How it works:**
- TUI can auto-retry these outcomes with bounded loops.
- After retry cap, terminal incomplete is expected.

**Config keys:**

```json
{
  "resilience": {
    "incompleteActionAutoLoop": true,
    "maxIncompleteAutoLoops": 2,
    "autoLoopPromptStyle": "strict"
  }
}
```

Increase `maxIncompleteAutoLoops` for more retries, or disable `incompleteActionAutoLoop` for immediate manual control.

### Run fails with open tasks (`open_tasks`)

**Symptoms:** Run ends with open pending/in-progress tasks even though no visible worker is active.

**What happens now:**
- Core run boundaries reconcile stale `in_progress` tasks back to `pending`.
- This prevents orphaned ownership from permanently blocking completion.

**Tuning key:**

```json
{
  "resilience": {
    "taskLeaseStaleMs": 300000
  }
}
```

Lower `taskLeaseStaleMs` to recover faster, raise it for longer-running tasks.

### Swarm appears stalled with dispatched tasks

**Symptoms:** Swarm has tasks in `dispatched` but no active workers after interruption/retry.

**What happens now:**
- Swarm reconciles stale `dispatched` tasks back to `ready` when no active worker owns them.

**Tuning key (`swarm.yaml`):**

```yaml
resilience:
  dispatchLeaseStaleMs: 300000
```

### Hook scripts fail or time out

**Symptoms:** Expected automation does not trigger, or logs mention hook execution errors.

**Checks:**

1. Verify command exists and is executable.
2. Keep hook scripts under `timeoutMs`.
3. Ensure required env vars are listed in `hooks.shell.envAllowlist`.
4. Test script manually:
   ```bash
   echo '{"event":"run.after","payload":{}}' | node ./scripts/hook.js
   ```

**Minimal hook config:**

```json
{
  "hooks": {
    "shell": {
      "enabled": true,
      "defaultTimeoutMs": 5000,
      "envAllowlist": ["SLACK_WEBHOOK_URL"],
      "commands": [
        { "event": "run.after", "command": "node", "args": ["./scripts/hook.js"] }
      ]
    }
  }
}
```

## Build Issues

### TypeScript compilation errors

**Symptoms:** `npm run build` fails.

**Solutions:**

1. **Clean and rebuild:**
   ```bash
   rm -rf dist/
   npm run build
   ```

2. **Reinstall dependencies:**
   ```bash
   rm -rf node_modules/
   npm install
   npm run build
   ```

3. **Check Node.js version:**
   ```bash
   node --version  # Should be 20+
   ```

### Tests failing

**Symptoms:** `npm test` shows failures.

**Solutions:**

1. **Run specific test to isolate:**
   ```bash
   npx vitest run tests/specific.test.ts
   ```

2. **Check for environment-specific issues:**
   Some tests require specific setup or may have timing issues.

## Performance Issues

### Agent running slowly

**Symptoms:** Long delays between responses.

**Possible causes:**
- Network latency to API
- Large context size
- Model selection

**Solutions:**

1. **Check network:**
   ```bash
   curl -I https://api.anthropic.com/
   ```

2. **Use a faster model:**
   ```bash
   attocode -m anthropic/claude-3-5-haiku-latest
   ```

3. **Compact context:**
   ```
   /compact
   ```

### High token usage

**Symptoms:** Unexpectedly high API costs.

**Solutions:**

1. **Check session metrics:**
   ```
   /status
   ```

2. **Use compaction for long sessions:**
   ```
   /compact
   ```

3. **Set iteration limits:**
   ```bash
   attocode -i 20  # Limit to 20 iterations
   ```

## Session Issues

### Cannot restore session

**Symptoms:** `/load` fails or session data missing.

**Check:**
- Sessions are stored in `~/.local/share/attocode/sessions.db`
- The SQLite database may be corrupted

**Solution:** If database is corrupted, remove and let it recreate:
```bash
rm ~/.local/share/attocode/sessions.db
```

### Checkpoints not saving

**Symptoms:** `/checkpoint` succeeds but data not available.

**Check:** Ensure the sessions directory exists:
```bash
mkdir -p ~/.local/share/attocode
```

## Getting Help

If your issue isn't covered here:

1. **Enable debug logging:**
   ```bash
   attocode --debug
   ```

2. **Check the logs** for error details

3. **Open an issue** at https://github.com/eren23/attocode/issues with:
   - Steps to reproduce
   - Error messages
   - Environment details (OS, Node version)
