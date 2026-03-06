# Skills and Agents Guide

This guide covers how to create and manage custom skills and agents in Attocode using the unified `.attocode/` directory system.

## Table of Contents

- [Quick Start](#quick-start)
- [Directory Structure](#directory-structure)
- [Skills](#skills)
  - [What are Skills?](#what-are-skills)
  - [Creating a Skill](#creating-a-skill)
  - [Skill File Format](#skill-file-format)
  - [Invokable vs Passive Skills](#invokable-vs-passive-skills)
  - [Skill Arguments](#skill-arguments)
  - [Template Variables](#template-variables)
- [Agents](#agents)
  - [What are Agents?](#what-are-agents)
  - [Creating an Agent](#creating-an-agent)
  - [Agent File Format](#agent-file-format)
  - [Spawning Agents](#spawning-agents)
- [Command Reference](#command-reference)
- [Examples](#examples)

---

## Quick Start

### 1. Initialize Your Project

```bash
/init
```

This creates the `.attocode/` directory structure:

```
.attocode/
├── config.json      # Project settings
├── rules.md         # Project-specific rules
├── skills/          # Custom skills
└── agents/          # Custom agents
```

### 2. Create Your First Skill

```bash
/skills new code-review
```

This creates `.attocode/skills/code-review/SKILL.md` with a template you can customize.

### 3. Create Your First Agent

```bash
/agents new api-expert
```

This creates `.attocode/agents/api-expert/AGENT.yaml` with a template you can customize.

### 4. View What's Available

```bash
/skills          # List all skills
/agents          # List all agents
```

---

## Directory Structure

Attocode uses a **priority hierarchy** for loading skills and agents:

```
Priority: built-in < ~/.attocode/ < .attocode/
```

| Location | Scope | Priority |
|----------|-------|----------|
| Built-in | All projects | Lowest |
| `~/.attocode/` | User-level (all your projects) | Medium |
| `.attocode/` | Project-level (this project only) | Highest |

**Key behavior:** If a skill or agent with the same name exists in multiple locations, the higher-priority version wins.

### Full Directory Layout

```
~/.attocode/                    # User-level (shared across projects)
├── config.json                 # User defaults
├── rules.md                    # User rules
├── skills/                     # User-defined skills
│   └── my-review/
│       └── SKILL.md
└── agents/                     # User-defined agents
    └── my-researcher/
        └── AGENT.yaml

.attocode/                      # Project-level (this project only)
├── config.json                 # Project config (overrides user)
├── rules.md                    # Project rules
├── skills/                     # Project skills
│   └── project-deploy/
│       └── SKILL.md
└── agents/                     # Project agents
    └── domain-expert/
        └── AGENT.yaml
```

### Backward Compatibility

Legacy paths still work:
- `.agent/skills/` → Project skills (legacy)
- `~/.agent/skills/` → User skills (legacy)
- `.agents/` → Project agents (legacy)

---

## Skills

### What are Skills?

Skills are **specialized capabilities** that enhance the agent's behavior. They inject domain-specific knowledge and instructions into the agent's context.

**Two types:**
- **Invokable skills** - Called explicitly with `/skillname`
- **Passive skills** - Auto-activate based on triggers (keywords, file patterns)

### Creating a Skill

**Method 1: Using the command**
```bash
/skills new my-skill
```

**Method 2: Create manually**
```bash
mkdir -p .attocode/skills/my-skill
# Create .attocode/skills/my-skill/SKILL.md
```

**Method 3: Create a user-level skill (shared across projects)**
```bash
mkdir -p ~/.attocode/skills/my-skill
# Create ~/.attocode/skills/my-skill/SKILL.md
```

### Skill File Format

Skills are Markdown files with YAML frontmatter:

```markdown
---
name: code-review
description: Perform thorough code reviews with configurable focus
invokable: true
arguments:
  - name: file
    description: File to review
    type: file
    required: true
    aliases: [-f, --file]
  - name: focus
    description: Review focus area
    type: string
    default: general
triggers:
  - review
  - code quality
tags:
  - review
  - quality
tools:
  - read_file
  - grep
  - glob
---

# Code Review Skill

When reviewing code, follow these guidelines:

## Process

1. Read the file completely
2. Identify potential issues
3. Categorize by severity
4. Provide actionable suggestions

## Focus Areas

- **security**: Look for vulnerabilities, injection risks, auth issues
- **performance**: Find inefficiencies, N+1 queries, memory leaks
- **style**: Check naming, formatting, consistency
- **general**: All of the above

## Output Format

Provide findings as:

```
[SEVERITY] Location: Description
  Suggestion: How to fix
```
```

### Frontmatter Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique skill identifier |
| `description` | string | Yes | Brief description |
| `invokable` | boolean | No | Can be called with `/name` |
| `arguments` | array | No | Arguments for invokable skills |
| `triggers` | array | No | Keywords/patterns for auto-activation |
| `tags` | array | No | Categories for discovery |
| `tools` | array | No | Tools this skill uses |
| `version` | string | No | Skill version |
| `author` | string | No | Skill author |

### Invokable vs Passive Skills

**Invokable skills** are called explicitly:

```markdown
---
name: deploy
invokable: true
arguments:
  - name: target
    description: Deployment target
    default: staging
---
```

Usage: `/deploy --target production`

**Passive skills** activate automatically on triggers:

```markdown
---
name: typescript-patterns
invokable: false
triggers:
  - type: file_pattern
    pattern: "*.ts"
  - type: keyword
    pattern: "typescript"
---
```

Activates when you mention "typescript" or work with `.ts` files.

### Skill Arguments

Arguments let users pass parameters to invokable skills:

```yaml
arguments:
  - name: file
    description: Target file to analyze
    type: file          # string, number, boolean, file
    required: true
    aliases: [-f]

  - name: verbose
    description: Show detailed output
    type: boolean
    default: false
    aliases: [-v, --verbose]

  - name: depth
    description: Analysis depth (1-5)
    type: number
    default: 3
```

**Usage:**
```bash
/analyze --file src/main.ts -v --depth 5
/analyze -f src/main.ts      # Using alias
```

### Template Variables

Use `{{variable}}` in skill content to inject argument values:

```markdown
---
name: explain
arguments:
  - name: topic
    required: true
---

# Explain: {{topic}}

Provide a clear explanation of {{topic}} with:
- Definition
- Examples
- Common pitfalls
```

**Built-in variables:**
- `{{_cwd}}` - Current working directory
- `{{_sessionId}}` - Current session ID
- `{{_positional}}` - Positional arguments as string
- `{{_args}}` - Positional arguments as array

---

## Agents

### What are Agents?

Agents are **autonomous workers** that can be spawned to handle specific tasks. Each agent has:
- A specialized system prompt
- Configured tools
- Resource limits (iterations, tokens)
- A model preference (fast/balanced/quality)

### Creating an Agent

**Method 1: Using the command**
```bash
/agents new my-agent
```

**Method 2: With options**
```bash
/agents new api-designer --model quality --description "Design REST APIs"
```

**Method 3: Create manually**
```bash
mkdir -p .attocode/agents/my-agent
# Create .attocode/agents/my-agent/AGENT.yaml
```

### Agent File Format

Agents are YAML files:

```yaml
name: api-designer
description: Design RESTful APIs following best practices
model: quality  # fast (haiku) | balanced (sonnet) | quality (opus)

maxIterations: 30
maxTokenBudget: 80000

capabilities:
  - api-design
  - openapi
  - rest
  - documentation

tools:
  - read_file
  - write_file
  - edit_file
  - list_files
  - glob
  - grep

tags:
  - api
  - design
  - architecture

systemPrompt: |
  You are an API design expert. Your job is to:
  - Design clean, RESTful APIs
  - Follow industry best practices
  - Create OpenAPI 3.0 specifications
  - Consider versioning, pagination, error handling

  ## Design Principles

  1. Use nouns for resources, verbs for actions
  2. Use proper HTTP methods (GET, POST, PUT, DELETE)
  3. Return appropriate status codes
  4. Design for consistency and predictability

  ## Output Format

  When designing an API:
  1. Start with resource identification
  2. Define endpoints and methods
  3. Specify request/response schemas
  4. Document with OpenAPI spec
```

### Agent Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique agent identifier |
| `description` | string | Yes | What the agent does |
| `systemPrompt` | string | Yes | Instructions for the agent |
| `model` | string | No | `fast`, `balanced`, or `quality` |
| `maxIterations` | number | No | Max tool-use cycles (default: 30) |
| `maxTokenBudget` | number | No | Max tokens to use |
| `capabilities` | array | No | Keywords for NL matching |
| `tools` | array | No | Tool whitelist (all if omitted) |
| `tags` | array | No | Categories for discovery |

### Spawning Agents

Use `/spawn` to run an agent:

```bash
/spawn researcher "Find all API endpoints in this codebase"
/spawn coder "Add input validation to the login form"
/spawn api-designer "Design a REST API for user management"
```

The agent runs autonomously and returns results when complete.

---

## Command Reference

### Skill Commands

| Command | Description |
|---------|-------------|
| `/skills` | List all skills with categories and usage |
| `/skills new <name>` | Create a new skill scaffold |
| `/skills info <name>` | Show detailed skill information |
| `/skills enable <name>` | Activate a skill |
| `/skills disable <name>` | Deactivate a skill |
| `/skills edit <name>` | Open skill in $EDITOR |
| `/skills reload` | Reload all skills |

### Agent Commands

| Command | Description |
|---------|-------------|
| `/agents` | List all agents with models and sources |
| `/agents new <name>` | Create a new agent scaffold |
| `/agents info <name>` | Show detailed agent information |
| `/agents edit <name>` | Open agent in $EDITOR |
| `/agents reload` | Reload all agents |
| `/spawn <agent> <task>` | Run an agent with a task |

### Initialization

| Command | Description |
|---------|-------------|
| `/init` | Create `.attocode/` directory structure |
| `/init --force` | Recreate missing files |
| `/init --minimal` | Create directories only (no config files) |

---

## Examples

### Example 1: Code Review Skill

Create a skill for reviewing code with different focus areas:

```bash
/skills new review
```

Edit `.attocode/skills/review/SKILL.md`:

```markdown
---
name: review
description: Review code for bugs, security, and style issues
invokable: true
arguments:
  - name: file
    description: File to review
    type: file
    required: true
    aliases: [-f]
  - name: focus
    description: Focus area (security, perf, style, all)
    type: string
    default: all
---

# Code Review

Review {{file}} with focus on: {{focus}}

## Review Checklist

### Security (if focus includes security or all)
- [ ] Input validation
- [ ] SQL injection risks
- [ ] XSS vulnerabilities
- [ ] Authentication/authorization

### Performance (if focus includes perf or all)
- [ ] N+1 queries
- [ ] Unnecessary computations
- [ ] Memory leaks
- [ ] Caching opportunities

### Style (if focus includes style or all)
- [ ] Naming conventions
- [ ] Code organization
- [ ] Documentation
- [ ] Error handling

## Output

Provide findings as actionable items with severity levels.
```

**Usage:**
```bash
/review --file src/auth/login.ts --focus security
/review -f src/api/users.ts
```

### Example 2: Domain Expert Agent

Create an agent that understands your project's domain:

```bash
/agents new domain-expert
```

Edit `.attocode/agents/domain-expert/AGENT.yaml`:

```yaml
name: domain-expert
description: Expert in our e-commerce platform's domain model
model: quality

maxIterations: 40
maxTokenBudget: 100000

capabilities:
  - domain
  - business-logic
  - e-commerce
  - orders
  - inventory

tools:
  - read_file
  - list_files
  - glob
  - grep

systemPrompt: |
  You are a domain expert for our e-commerce platform. You understand:

  ## Core Domains

  - **Orders**: Order lifecycle, status transitions, fulfillment
  - **Inventory**: Stock management, reservations, warehouses
  - **Customers**: Profiles, addresses, payment methods
  - **Products**: Catalog, variants, pricing, categories

  ## Key Patterns

  - Event sourcing for order state
  - CQRS for read/write separation
  - Saga pattern for distributed transactions

  ## Your Role

  When asked about the domain:
  1. Reference actual code in the codebase
  2. Explain business rules and their implementation
  3. Identify potential issues or inconsistencies
  4. Suggest improvements aligned with domain patterns
```

**Usage:**
```bash
/spawn domain-expert "Explain how order cancellation works"
/spawn domain-expert "What happens when inventory runs out during checkout?"
```

### Example 3: User-Level Skill (Shared)

Create a skill available in all your projects:

```bash
mkdir -p ~/.attocode/skills/commit-helper
```

Create `~/.attocode/skills/commit-helper/SKILL.md`:

```markdown
---
name: commit-helper
description: Help write conventional commit messages
invokable: true
triggers:
  - commit
  - git commit
---

# Commit Message Helper

Help write a commit message following conventional commits.

## Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

## Types

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation
- **style**: Formatting (no code change)
- **refactor**: Code restructuring
- **test**: Adding tests
- **chore**: Maintenance

## Process

1. Analyze the staged changes
2. Identify the primary type
3. Determine the scope (component/module affected)
4. Write a concise description
5. Add body if changes are complex
```

Now `/commit-helper` is available in all your projects.

---

## Tips

1. **Start simple**: Create skills/agents with minimal config, then add features as needed.

2. **Use user-level for common patterns**: Skills you use across projects belong in `~/.attocode/`.

3. **Be specific in system prompts**: The more context you give agents, the better they perform.

4. **Test with `/skills info` and `/agents info`**: Verify your configuration loaded correctly.

5. **Use triggers wisely**: Passive skills with broad triggers can activate unexpectedly.

6. **Set appropriate limits**: Use `maxIterations` and `maxTokenBudget` to prevent runaway agents.

---

## Troubleshooting

**Skill/agent not appearing?**
- Check file location and naming (SKILL.md, AGENT.yaml)
- Run `/skills reload` or `/agents reload`
- Check `/skills info <name>` for load errors

**Arguments not working?**
- Verify YAML syntax in frontmatter
- Check argument names match usage
- Use `/skills info <name>` to see parsed arguments

**Agent not using expected tools?**
- Check `tools` whitelist in AGENT.yaml
- Omit `tools` field to allow all tools

**Passive skill not activating?**
- Check trigger patterns match your input
- Verify skill is enabled with `/skills enable <name>`
