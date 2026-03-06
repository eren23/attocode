---
sidebar_position: 3
title: "Custom Skills"
---

# Custom Skills

Skills are markdown-based instruction packages that extend the agent with specialized capabilities. They are discovered from the filesystem and injected into the agent's context.

## Skill Structure

A skill is a directory containing a `SKILL.md` file with YAML frontmatter:

```
.attocode/skills/code-review/
  SKILL.md
```

```markdown
---
name: code-review
description: Performs thorough code reviews with security and performance checks
type: invokable
tools:
  - read_file
  - grep
  - glob
tags:
  - review
  - quality
arguments:
  - name: path
    description: File or directory to review
    type: file
    required: true
  - name: focus
    description: Review focus area
    type: string
    default: general
---

# Code Review Skill

When performing a code review, follow these steps:

1. Read the target file(s) and understand the overall structure
2. Check for common issues:
   - Security vulnerabilities (injection, auth bypass)
   - Performance problems (N+1 queries, unnecessary allocations)
   - Error handling gaps (uncaught exceptions, missing validation)
3. Provide specific, actionable feedback with line references
4. Suggest improvements with code examples where appropriate
```

## Skill Types

### Invokable Skills

Triggered explicitly by the user with `/<skill-name>`:

```
/code-review --path src/agent.ts --focus security
```

Invokable skills can declare `arguments` in the frontmatter. Each argument has:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Argument name (used as `{{name}}` in templates) |
| `description` | string | Shown in help text |
| `type` | `string`, `boolean`, `file`, `number` | Validation type |
| `required` | boolean | Whether the argument must be provided |
| `default` | any | Default value if omitted |
| `aliases` | string[] | CLI aliases like `['-f', '--file']` |

### Passive Skills

Always loaded into agent context when `autoActivate` is enabled:

```yaml
---
name: project-conventions
description: Project-specific coding conventions
type: passive
---
```

Passive skills can also use triggers for conditional activation:

```yaml
triggers:
  - type: keyword
    pattern: "test|spec"
  - type: file_pattern
    pattern: "*.test.ts"
  - type: context
    pattern: "testing"
```

## Discovery Hierarchy

Skills are loaded from multiple directories with increasing priority:

1. **Built-in** (`attocode/skills/`) -- shipped with the agent
2. **User** (`~/.attocode/skills/`) -- user-global skills
3. **Project** (`.attocode/skills/`) -- project-specific skills

Later sources override earlier ones if the skill name matches. Legacy paths (`.agent/skills/`) are supported for backward compatibility.

## Creating a Skill

Use the scaffold command:

```
/skills new my-skill
```

This creates `.attocode/skills/my-skill/SKILL.md` with a template frontmatter and body.

## Managing Skills

```
/skills            # List all skills with locations and usage hints
/skills info name  # Show detailed info for a specific skill
```

## Execution Modes

Skills support two execution modes:

- **`prompt-injection`** (default): The skill content is injected into the agent's system prompt or context. The agent follows the instructions naturally.
- **`workflow`**: The skill defines multi-step procedures that the skill executor runs sequentially.

## Skill Manager API

For programmatic access:

```typescript
import { createSkillManager, getDefaultSkillDirectories } from './integrations/skills/skills.js';

const skills = createSkillManager({
  directories: getDefaultSkillDirectories(),
  autoActivate: true,
});

await skills.loadSkills();

// List available skills
const allSkills = skills.getSkills();

// Activate a skill
await skills.activateSkill('code-review', { path: 'src/agent.ts' });
```

## Best Practices

- Keep skill instructions focused on a single capability
- Use specific, actionable language the agent can follow
- Declare only the tools the skill actually needs
- Use tags for discoverability
- Test skills with different models to ensure instructions are clear enough
