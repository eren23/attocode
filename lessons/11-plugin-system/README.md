# Lesson 11: Plugin Architecture

> Building a modular, extensible agent through plugins

## What You'll Learn

1. **Plugin System Design**: How to create a plugin architecture that enables extensibility
2. **Sandboxed Contexts**: Providing isolated access to agent services
3. **Lifecycle Management**: Properly initializing and cleaning up plugins
4. **Resource Tracking**: Ensuring clean unloading of plugin resources
5. **Inter-Plugin Communication**: How plugins can communicate through events

## Why This Matters

A plugin system transforms your agent from a monolithic application into an extensible platform. Benefits include:

- **Modularity**: Features can be developed, tested, and deployed independently
- **Third-party Extensions**: Others can extend your agent without modifying core code
- **Clean Separation**: Core functionality stays focused while plugins add extras
- **Easy Updates**: Plugins can be updated or replaced without affecting other parts

## Key Concepts

### Plugin Interface

Every plugin must implement this interface:

```typescript
interface Plugin {
  metadata: PluginMetadata;
  initialize(context: PluginContext): Promise<void>;
  cleanup?(): Promise<void>;
}

interface PluginMetadata {
  name: string;      // Unique identifier (lowercase, alphanumeric, hyphens)
  version: string;   // Semver version
  description?: string;
  dependencies?: PluginDependency[];
}
```

### Plugin Context

The context is the plugin's interface to the agent:

```typescript
interface PluginContext {
  // Hook registration
  registerHook(event, handler, options): void;

  // Tool registration
  registerTool(tool): void;

  // Configuration
  getConfig<T>(key): T | undefined;
  setConfig<T>(key, value): void;

  // Storage
  store(key, value): Promise<void>;
  retrieve<T>(key): Promise<T | undefined>;

  // Logging
  log(level, message, data?): void;

  // Inter-plugin communication
  emit(eventName, data): void;
  subscribe(eventName, handler): () => void;
}
```

### Plugin Lifecycle

```
┌──────────────┐
│  Registered  │  Plugin is known but not active
└──────┬───────┘
       │ enable()
       ▼
┌──────────────┐
│   Loading    │  Running initialize()
└──────┬───────┘
       │
       ├─────────────────┐
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│    Active    │  │    Error     │  Initialization failed
└──────┬───────┘  └──────────────┘
       │ disable()
       ▼
┌──────────────┐
│  Unloading   │  Running cleanup()
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   Disabled   │  Ready to re-enable or unregister
└──────────────┘
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Plugin interfaces and type definitions |
| `plugin-context.ts` | Sandboxed context implementation |
| `plugin-loader.ts` | Plugin discovery and loading |
| `plugin-manager.ts` | Central plugin lifecycle manager |
| `example-plugins/` | Example plugin implementations |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:11
```

## Code Examples

### Creating a Simple Plugin

```typescript
import type { Plugin, PluginContext } from './types.js';

export const myPlugin: Plugin = {
  metadata: {
    name: 'my-plugin',
    version: '1.0.0',
    description: 'A simple example plugin',
  },

  async initialize(context: PluginContext) {
    context.log('info', 'Plugin starting...');

    // Register a hook
    context.registerHook('tool.before', (event) => {
      context.log('debug', `Tool called: ${event.tool}`);
    });

    // Store some data
    await context.store('startedAt', Date.now());

    context.log('info', 'Plugin ready!');
  },

  async cleanup() {
    console.log('Cleaning up...');
  },
};
```

### Registering a Tool

```typescript
import { z } from 'zod';

async initialize(context: PluginContext) {
  context.registerTool({
    name: 'my_tool',
    description: 'Does something useful',
    parameters: z.object({
      input: z.string().describe('The input to process'),
    }),
    dangerLevel: 'safe',
    execute: async ({ input }) => {
      return {
        success: true,
        output: `Processed: ${input}`,
      };
    },
  });
}
```

### Inter-Plugin Communication

```typescript
// Plugin A - emitting events
context.emit('data.processed', { count: 42 });

// Plugin B - listening for events
context.subscribe('data.processed', (data) => {
  context.log('info', `Received: ${JSON.stringify(data)}`);
});
```

### Using the Plugin Manager

```typescript
import { PluginManager } from './plugin-manager.js';
import { myPlugin } from './my-plugin.js';

const manager = new PluginManager();

// Register
await manager.register(myPlugin);

// Enable
await manager.enable('my-plugin');

// Later, disable
await manager.disable('my-plugin');

// Unregister
await manager.unregister('my-plugin');

// Shutdown all
await manager.shutdown();
```

## Example Plugins

### Logger Plugin

Logs all agent events for debugging:

```typescript
context.registerHook('tool.before', (event) => {
  context.log('debug', `Tool: ${event.tool}`);
}, { priority: 0 });  // Run first
```

### Security Plugin

Blocks dangerous operations:

```typescript
context.registerHook('tool.before', (event) => {
  if (isDangerous(event.args)) {
    event.preventDefault = true;
    context.emit('security.blocked', { reason: 'Dangerous operation' });
  }
}, { priority: 5, canModify: true });  // Run early, can block
```

### Metrics Plugin

Collects performance metrics:

```typescript
context.registerHook('tool.after', (event) => {
  recordDuration(event.tool, event.durationMs);
}, { priority: 50 });

// Expose metrics via custom tool
context.registerTool({
  name: 'get_metrics',
  // ...
});
```

## Plugin Dependencies

Plugins can declare dependencies on other plugins:

```typescript
metadata: {
  name: 'advanced-logging',
  version: '1.0.0',
  dependencies: [
    { name: 'logger', version: '^1.0.0' },
    { name: 'metrics', version: '^1.0.0', optional: true },
  ],
},
```

The plugin manager will:
1. Check dependencies before loading
2. Load plugins in dependency order
3. Report missing dependencies

## Design Patterns

### Namespace Isolation

Plugin tools are automatically namespaced:

```typescript
context.registerTool({ name: 'my_tool' });
// Actually registered as: 'my-plugin:my_tool'
```

### Resource Tracking

Everything a plugin registers is tracked:

```typescript
interface PluginResources {
  hooks: string[];        // Registered hook IDs
  tools: string[];        // Registered tool names
  configKeys: string[];   // Set config keys
  storageKeys: string[];  // Stored data keys
  subscriptions: [];      // Event subscriptions
}
```

When the plugin is unloaded, all resources are automatically cleaned up.

### Error Isolation

Plugin errors don't crash the agent:

```typescript
try {
  await plugin.initialize(context);
} catch (err) {
  plugin.state = 'error';
  plugin.error = err;
  // Other plugins continue to work
}
```

## Testing Plugins

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { PluginManager } from './plugin-manager.js';
import { myPlugin } from './my-plugin.js';

describe('My Plugin', () => {
  let manager: PluginManager;

  beforeEach(() => {
    manager = new PluginManager({ autoEnable: true });
  });

  it('initializes correctly', async () => {
    await manager.register(myPlugin);
    expect(manager.getState('my-plugin')).toBe('active');
  });

  it('registers expected hooks', async () => {
    await manager.register(myPlugin);
    const plugin = manager.get('my-plugin');
    expect(plugin?.resources.hooks.length).toBeGreaterThan(0);
  });
});
```

## Common Issues

### "Plugin already registered"

Each plugin name must be unique. Check if you're accidentally registering twice.

### "Missing dependency"

Ensure dependent plugins are registered before the plugin that needs them.

### "Initialization timeout"

Plugins have a default 5-second timeout. For slow initialization:

```typescript
await manager.register(plugin, { initTimeout: 30000 });
```

### "Resources not cleaned up"

Make sure to call `manager.shutdown()` or `manager.unregister()` when done.

## Advanced: Skills System

The production agent extends plugins with **Skills** - markdown files that inject specialized prompts and workflows without writing code.

### Skills vs Tools

| Aspect | Tools | Skills |
|--------|-------|--------|
| Format | TypeScript functions | Markdown files |
| Purpose | Execute actions | Inject context/workflows |
| Location | `tools/`, plugins | `.skills/`, `skills/` |
| Invocation | LLM tool calls | User command or trigger |
| Output | Action results | Prompt injection |

### Skill File Format

Skills are markdown files with YAML frontmatter:

```markdown
---
name: code-review
description: Detailed code review workflow with security focus
triggers:
  - "review this code"
  - "check for security issues"
  - "audit this file"
tags: [review, security, quality]
---

# Code Review Skill

When reviewing code, follow this structured approach:

## 1. Security Analysis
- Check for injection vulnerabilities (SQL, XSS, command)
- Verify authentication/authorization
- Look for sensitive data exposure
- Review input validation

## 2. Code Quality
- Check naming conventions
- Review error handling
- Verify proper resource cleanup
- Look for code duplication

## 3. Output Format
Provide findings as:
- **Critical**: Security vulnerabilities
- **Warning**: Potential issues
- **Info**: Suggestions for improvement
```

### Skills Manager

```typescript
interface SkillDefinition {
  name: string;
  description: string;
  content: string;         // The markdown content
  triggers?: string[];     // Keywords that activate this skill
  tags?: string[];         // For discovery
  source: string;          // File path
  loadedAt: Date;
}

class SkillsManager {
  private skills = new Map<string, SkillDefinition>();
  private skillsDir: string;

  // Load skills from .skills/ directory
  async loadSkills(): Promise<void> {
    const files = await glob('**/*.md', { cwd: this.skillsDir });

    for (const file of files) {
      await this.loadSkillFile(join(this.skillsDir, file));
    }
  }

  // Parse skill file with frontmatter
  private async loadSkillFile(filePath: string): Promise<void> {
    const content = await readFile(filePath, 'utf-8');
    const { data: frontmatter, content: body } = parseFrontmatter(content);

    const skill: SkillDefinition = {
      name: frontmatter.name || basename(filePath, '.md'),
      description: frontmatter.description || '',
      content: body,
      triggers: frontmatter.triggers || [],
      tags: frontmatter.tags || [],
      source: filePath,
      loadedAt: new Date(),
    };

    this.skills.set(skill.name, skill);
  }

  // Find skills matching a query
  findMatchingSkills(query: string): SkillDefinition[] {
    const queryLower = query.toLowerCase();
    const matches: Array<{ skill: SkillDefinition; score: number }> = [];

    for (const skill of this.skills.values()) {
      let score = 0;

      // Check triggers
      for (const trigger of skill.triggers || []) {
        if (queryLower.includes(trigger.toLowerCase())) {
          score += 10;
        }
      }

      // Check tags
      for (const tag of skill.tags || []) {
        if (queryLower.includes(tag.toLowerCase())) {
          score += 5;
        }
      }

      // Check name
      if (queryLower.includes(skill.name.toLowerCase())) {
        score += 8;
      }

      if (score > 0) {
        matches.push({ skill, score });
      }
    }

    return matches
      .sort((a, b) => b.score - a.score)
      .map(m => m.skill);
  }

  // Get skill by name
  getSkill(name: string): SkillDefinition | undefined {
    return this.skills.get(name);
  }

  // List all skills
  listSkills(): SkillDefinition[] {
    return Array.from(this.skills.values());
  }
}
```

### Skill Invocation

```typescript
// Create skill tool for user invocation
function createSkillTool(skillsManager: SkillsManager) {
  return {
    name: 'invoke_skill',
    description: 'Load a skill to get specialized guidance for a task',
    parameters: {
      type: 'object',
      properties: {
        skill: { type: 'string', description: 'Skill name or search query' },
      },
      required: ['skill'],
    },
    async execute({ skill }) {
      // Try exact match first
      let skillDef = skillsManager.getSkill(skill);

      // Fall back to search
      if (!skillDef) {
        const matches = skillsManager.findMatchingSkills(skill);
        if (matches.length > 0) {
          skillDef = matches[0];
        }
      }

      if (!skillDef) {
        return `No skill found matching "${skill}". Available: ${
          skillsManager.listSkills().map(s => s.name).join(', ')
        }`;
      }

      // Return skill content for context injection
      return `## Skill: ${skillDef.name}\n\n${skillDef.content}`;
    },
  };
}
```

### Auto-Suggestion

```typescript
// Suggest skills based on user message
async function suggestSkills(
  message: string,
  skillsManager: SkillsManager
): Promise<string | null> {
  const matches = skillsManager.findMatchingSkills(message);

  if (matches.length === 0) return null;

  const suggestions = matches.slice(0, 3).map(s =>
    `- **${s.name}**: ${s.description}`
  ).join('\n');

  return `I found skills that might help:\n${suggestions}\n\nUse \`/skill <name>\` to activate.`;
}
```

### Skill Events

```typescript
type SkillEvent =
  | { type: 'skill.loaded'; name: string; source: string }
  | { type: 'skill.invoked'; name: string; user: string }
  | { type: 'skill.suggested'; names: string[]; query: string }
  | { type: 'skill.error'; name: string; error: string };

skillsManager.on((event) => {
  if (event.type === 'skill.invoked') {
    console.log(`Skill ${event.name} invoked`);
  }
});
```

### Example Skills Directory

```
.skills/
├── code-review.md        # Detailed code review workflow
├── debugging.md          # Systematic debugging approach
├── refactoring.md        # Safe refactoring patterns
├── testing.md            # Test writing guidance
├── documentation.md      # Documentation standards
└── security/
    ├── audit.md          # Security audit checklist
    └── owasp.md          # OWASP top 10 checks
```

## Next Steps

In **Lesson 12: Rules & Instructions System**, we'll build a system for managing dynamic configuration and rules that can modify agent behavior based on context.

The plugin system you learned here can be used to:
- Add custom rule sources
- Implement rule processors
- Create rule-based hooks
