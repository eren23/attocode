---
sidebar_position: 3
title: Configuration
---

# Configuration

Attocode uses a layered configuration system with project-level and user-level settings, custom rules, skills, and agents.

## The `.attocode/` Directory

Configuration lives in an `.attocode/` directory. There are two levels:

| Level | Path | Scope |
|---------|------------------|---------------------------------|
| User | `~/.attocode/` | Global defaults for all projects |
| Project | `.attocode/` | Project-specific overrides |

**Priority hierarchy:** `built-in defaults < ~/.attocode/ < .attocode/`

Project-level settings always override user-level settings, which override built-in defaults.

### Directory Structure

```
.attocode/                      # Project-level
├── config.json                 # Project configuration
├── rules.md                    # Project-specific rules
├── skills/                     # Project-specific skills
│   └── my-skill/
│       └── SKILL.md
└── agents/                     # Project-specific agents
    └── my-agent/
        └── AGENT.yaml

~/.attocode/                    # User-level (global)
├── config.json                 # User defaults
├── rules.md                    # User rules
├── skills/                     # User-defined skills
└── agents/                     # User-defined agents
```

### Initialize with `/init`

Run the `init` command to scaffold the directory structure:

```bash
npx tsx src/main.ts init
```

This creates the `.attocode/` directory with starter files in your current project.

## config.json

The `config.json` file controls agent behavior. Both `~/.attocode/config.json` (user) and `.attocode/config.json` (project) are loaded and deep-merged.

### Core Options

```json
{
  "model": "anthropic/claude-sonnet-4",
  "maxIterations": 50,
  "timeout": 300000,
  "maxTokens": 8192,
  "temperature": 0.7
}
```

| Key | Type | Description |
|-----|------|-------------|
| `model` | string | Default model identifier |
| `maxIterations` | number | Maximum ReAct loop iterations |
| `timeout` | number | Request timeout in milliseconds |
| `maxTokens` | number | Max tokens per LLM response |
| `temperature` | number | Sampling temperature (0--2) |

### Feature Sections

Each feature can be configured with an object or disabled entirely with `false`:

```json
{
  "planning": {
    "enabled": true,
    "autoplan": true,
    "complexityThreshold": 3
  },
  "sandbox": {
    "mode": "seatbelt"
  },
  "compaction": {
    "enabled": true,
    "tokenThreshold": 80000,
    "mode": "auto"
  },
  "humanInLoop": {
    "riskThreshold": "moderate"
  },
  "observability": false
}
```

Available feature sections: `planning`, `memory`, `sandbox`, `policyEngine`, `humanInLoop`, `subagent`, `observability`, `cancellation`, `resources`, `compaction`, `resilience`, `hooks`.

### Provider Selection

```json
{
  "providers": {
    "default": "openrouter"
  }
}
```

## rules.md

Place a `rules.md` file at either level to inject persistent instructions into the agent's system prompt. These rules are included in every conversation.

**Project-level** (`.attocode/rules.md`):

```markdown
# Project Rules

- Always use TypeScript strict mode
- Run tests after modifying source files
- Follow the existing code style in this repo
```

**User-level** (`~/.attocode/rules.md`):

```markdown
# My Rules

- Prefer concise explanations
- Always show file paths in responses
```

## Skills

Skills are reusable prompt templates that extend the agent's capabilities. Place them in the `skills/` directory:

```
.attocode/skills/
└── deploy/
    └── SKILL.md
```

Manage skills with interactive commands:

| Command | Description |
|---------|-------------|
| `/skills` | List all available skills |
| `/skills new <name>` | Create a new skill scaffold |
| `/skills info <name>` | Show detailed skill information |

## Agents

Custom agent definitions specify model, tools, and behavior for specialized roles:

```
.attocode/agents/
└── reviewer/
    └── AGENT.yaml
```

Manage agents with interactive commands:

| Command | Description |
|---------|-------------|
| `/agents` | List all available agents |
| `/agents new <name>` | Create a new agent scaffold |
| `/agents info <name>` | Show detailed agent information |

## Legacy Paths

For backward compatibility, Attocode also checks these legacy locations:

- `.agent/` -- older project-level config
- `.agents/` -- older agents directory

These still work but `.attocode/` is preferred for new projects.

## Next Steps

- [CLI Reference](./cli-reference.md) -- all command-line flags and environment variables
