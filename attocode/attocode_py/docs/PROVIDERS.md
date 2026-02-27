# LLM Provider Reference

## Supported Providers

| Provider | Env Variable | Default Model | Status |
|----------|-------------|---------------|--------|
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 | Primary |
| OpenRouter | `OPENROUTER_API_KEY` | anthropic/claude-sonnet-4 | Full support |
| OpenAI | `OPENAI_API_KEY` | gpt-4o | Full support |
| ZAI | `ZAI_API_KEY` | glm-5 | Basic support |

## Configuration

### Environment Variables

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENROUTER_API_KEY=sk-or-...
export OPENAI_API_KEY=sk-...
```

### Config File (`.attocode/config.json`)

```json
{
  "provider": "anthropic",
  "api_key": "sk-ant-...",
  "model": "claude-sonnet-4-20250514"
}
```

### CLI Flags

```bash
attocode --provider anthropic --model claude-opus-4-20250514
```

## Provider Priority

1. CLI flags (highest)
2. Environment variables
3. Project config (`.attocode/config.json`)
4. User config (`~/.attocode/config.json`)
5. Defaults (lowest)

## Adding a Provider

1. Create adapter in `src/attocode/providers/adapters/`
2. Implement `LLMProvider` base class from `providers/base.py`
3. Register in `providers/registry.py`
4. Add model defaults in `config.py`

## Model Context Windows

Context windows are fetched from the model cache at startup. Override with:

```json
{
  "maxContextTokens": 200000
}
```
