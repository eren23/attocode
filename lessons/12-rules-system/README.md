# Lesson 12: Rules & Instructions System

> Building dynamic system prompts from hierarchical configuration sources

## What You'll Learn

1. **Hierarchical Configuration**: How to layer rules from global to local
2. **Rule Discovery**: Automatically finding instruction files in projects
3. **Priority Merging**: Resolving conflicts between rule sources
4. **Dynamic Prompts**: Building system prompts at runtime
5. **Template Expansion**: Injecting variables into prompts

## Why This Matters

Modern AI coding assistants support configuration files that let users customize behavior. Examples:

- **Claude Code**: `CLAUDE.md` files
- **Cursor**: `.cursorrules` files
- **Aider**: `.aider.md` files

A rules system enables:
- Per-project coding standards
- Personal preferences that apply everywhere
- Directory-specific overrides
- Dynamic prompt construction

## Key Concepts

### Scope Hierarchy

Rules come from multiple scopes, with more specific scopes overriding general ones:

```
┌─────────────────────────────────────────┐
│              Global                      │  ~/.claude/CLAUDE.md
│  ┌───────────────────────────────────┐  │
│  │            User                    │  │  ~/CLAUDE.md
│  │  ┌─────────────────────────────┐  │  │
│  │  │         Project              │  │  │  /project/CLAUDE.md
│  │  │  ┌───────────────────────┐  │  │  │
│  │  │  │      Directory         │  │  │  │  /project/src/CLAUDE.local.md
│  │  │  │  ┌─────────────────┐  │  │  │  │
│  │  │  │  │    Session       │  │  │  │  │  Runtime overrides
│  │  │  │  └─────────────────┘  │  │  │  │
│  │  │  └───────────────────────┘  │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘

Priority: session > directory > project > user > global
```

### Instruction File Format

```markdown
---
scope: project
priority: 300
tags: [typescript, web]
---

# Project Instructions

## Context
This is a TypeScript web application.

## Constraints
- Never commit .env files
- Always use strict mode

## Preferences
- Use functional components
- Prefer async/await over callbacks
```

### Rule Types

| Type | Purpose | Example |
|------|---------|---------|
| `persona` | Agent identity/role | "You are a TypeScript expert" |
| `context` | Background information | "This is a React application" |
| `instruction` | What to do | "Explain your reasoning" |
| `constraint` | What NOT to do | "Never expose API keys" |
| `preference` | What to prefer | "Use functional programming" |
| `format` | Output formatting | "Use markdown for responses" |
| `tool-config` | Tool-specific settings | "Prefer Edit over Write" |

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Type definitions for rules and sources |
| `rule-loader.ts` | File discovery and parsing |
| `rule-merger.ts` | Combining rules with priority |
| `prompt-builder.ts` | Constructing system prompts |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:12
```

## Code Examples

### Discovering Rules

```typescript
import { RuleLoader } from './rule-loader.js';

const loader = new RuleLoader({
  baseDir: process.cwd(),
  filePatterns: ['CLAUDE.md', 'AGENTS.md'],
});

// Find all instruction files
const sources = await loader.discover();

// Load and parse each one
for (const source of sources) {
  const result = await loader.load(source);
  if (result.success) {
    const parsed = loader.parseFile(result.content!, source.location);
    console.log(`Found ${parsed.sections.length} sections`);
  }
}
```

### Merging Rules

```typescript
import { RuleMerger } from './rule-merger.js';

const merger = new RuleMerger({
  strategy: 'combine',      // Include all rules
  deduplicate: true,        // Remove duplicates
});

// Merge rules from multiple files
const ruleSet = merger.merge([
  { source: globalSource, file: globalFile },
  { source: projectSource, file: projectFile },
]);

console.log(`Merged ${ruleSet.metadata.mergedRules} rules`);
```

### Building Prompts

```typescript
import { PromptBuilder } from './prompt-builder.js';

const builder = new PromptBuilder({
  includeSectionHeaders: true,
  maxLength: 10000,
});

const systemPrompt = builder.build(ruleSet);

// Or build with variables
const prompt = builder.buildWithVariables(ruleSet, {
  projectName: 'My Project',
  date: new Date().toISOString(),
});
```

### Direct Section Building

```typescript
import { buildFromSections } from './prompt-builder.js';

const prompt = buildFromSections({
  persona: 'You are a helpful assistant.',
  instructions: 'Always explain your reasoning.',
  constraints: 'Never execute dangerous commands.',
});
```

## Merge Strategies

### `combine` (default)

Include all rules, sorted by priority:

```typescript
const merger = new RuleMerger({ strategy: 'combine' });
// All rules included, sorted by scope then priority
```

### `priority`

Higher priority rules override lower ones:

```typescript
const merger = new RuleMerger({ strategy: 'priority' });
// Only highest priority rule of each type kept
```

### `latest`

Most recently loaded rules win:

```typescript
const merger = new RuleMerger({ strategy: 'latest' });
// Later sources override earlier ones
```

### Per-Type Strategies

```typescript
const merger = new RuleMerger({
  strategy: 'combine',
  typeStrategies: {
    constraint: 'combine',    // Keep all constraints
    preference: 'priority',   // Highest priority wins
    persona: 'latest',        // Most specific wins
  },
});
```

## Template Variables

Prompts can include template variables:

```markdown
You are helping with the {{projectName}} project.

Current date: {{date}}
User: {{userName}}
```

Expanded at runtime:

```typescript
const prompt = builder.buildWithVariables(ruleSet, {
  projectName: 'First Principles Agent',
  date: '2024-01-15',
  userName: 'Developer',
});
```

## Frontmatter Options

```yaml
---
# Scope override
scope: directory

# Priority within scope (lower = higher priority)
priority: 200

# Tags for filtering
tags: [typescript, testing]

# Condition for inclusion
condition:
  directories: ['src/**']
  fileTypes: ['*.ts', '*.tsx']

# Enable/disable
enabled: true
---
```

## Best Practices

### File Organization

```
~/.claude/
  CLAUDE.md              # Global preferences

/my-project/
  CLAUDE.md              # Project standards
  .claude/
    CLAUDE.md           # Additional project rules
    instructions.md     # Alternative location

  /src/
    CLAUDE.local.md     # Directory-specific (gitignored)
```

### Rule Writing

**Good rules:**
```markdown
## Constraints
- Never commit API keys or secrets
- Always validate user input before processing
```

**Avoid:**
```markdown
## Constraints
- Be careful with security stuff
- Make sure things work
```

### Gitignore Local Files

```gitignore
# Local instruction overrides
*.local.md
CLAUDE.local.md
```

## Integration Example

```typescript
import { RuleLoader, RuleMerger, PromptBuilder } from './12-rules-system';

async function buildAgentPrompt(workingDir: string): Promise<string> {
  const loader = new RuleLoader({ baseDir: workingDir });
  const merger = new RuleMerger();
  const builder = new PromptBuilder();

  // Discover and load all instruction files
  const sources = await loader.discover();
  const files = [];

  for (const source of sources) {
    const result = await loader.load(source);
    if (result.success) {
      const file = loader.parseFile(result.content!, source.location);
      files.push({ source, file });
    }
  }

  // Merge and build
  const ruleSet = merger.merge(files);
  return builder.build(ruleSet);
}

// Use in agent
const systemPrompt = await buildAgentPrompt(process.cwd());
const agent = new Agent({
  systemPrompt,
  // ...
});
```

## Advanced: .agentignore Support

The production agent implements `.agentignore` - AI-specific file exclusion patterns separate from `.gitignore`.

### Why Separate from .gitignore?

```
Files to hide from AI but keep in git:
- Large data files (agent doesn't need to analyze)
- Generated documentation
- Test fixtures with large payloads

Files in .gitignore the AI might need:
- Local config files (for understanding setup)
- Build outputs (for debugging)
```

### Priority Order

```
1. .agentignore (highest - AI-specific)
2. .gitignore (medium - inherit git patterns)
3. ~/.agent/ignore (global defaults)
4. Built-in patterns (always applied)
```

### Pattern Syntax

Uses gitignore-style patterns:

```gitignore
# .agentignore - AI-specific file exclusion

# Directories
data/
docs/generated/

# Glob patterns
*.csv
*.json.bak

# Negation (include despite previous patterns)
!important-data.csv

# Directory-only (trailing /)
scratch/

# Root-anchored (leading /)
/config/secrets/
```

### Built-in Patterns

Always ignored regardless of configuration:

```typescript
const BUILTIN_PATTERNS = [
  // Version control
  '.git', '.svn', '.hg',

  // Dependencies
  'node_modules', '__pycache__', '.venv', 'venv',

  // IDE/Editor
  '.idea', '.vscode', '*.swp', '*~',

  // OS files
  '.DS_Store', 'Thumbs.db',

  // Build outputs
  'dist', 'build', 'out',

  // Sensitive files
  '.env', '.env.local', '*.pem', '*.key',
  'credentials.json', 'secrets.json',
];
```

### Usage

```typescript
import { createIgnoreManager } from './ignore.js';

// Create and load patterns
const ignore = createIgnoreManager({
  includeGitignore: true,  // Include .gitignore patterns
  includeGlobal: true,     // Include ~/.agent/ignore
});
await ignore.load(process.cwd());

// Check single path
if (ignore.shouldIgnore('data/large-file.csv')) {
  console.log('Skipping file');
}

// Filter path list
const visibleFiles = ignore.filterPaths(allFiles);

// Filter with directory detection
const filtered = await ignore.filterPathsWithStats(paths);
```

### Sample .agentignore

```gitignore
# .agentignore - AI-specific file exclusion
# Files listed here will be hidden from the AI agent
# but remain visible to git and other tools

# Large data files that don't need AI analysis
data/
*.csv
*.json.bak

# Generated documentation
docs/api/
docs/generated/

# Test fixtures with large data
tests/fixtures/large/

# Temporary development files
scratch/
notes.md

# Sensitive configuration not needed for code changes
.env.production
config/secrets/

# Build artifacts already in .gitignore but ensure agent ignores
coverage/
.nyc_output/
```

### Events

```typescript
ignore.subscribe((event) => {
  switch (event.type) {
    case 'ignore.loaded':
      console.log(`Loaded ${event.patternCount} patterns from ${event.source}`);
      break;
    case 'ignore.matched':
      console.log(`Ignoring ${event.path} (matched: ${event.pattern})`);
      break;
  }
});
```

### Integration with File Tools

```typescript
// In file listing tool
async function listFiles(dir: string, ignoreManager: IgnoreManager) {
  const allFiles = await glob('**/*', { cwd: dir });
  return ignoreManager.filterPaths(allFiles);
}

// In file reading tool
async function readFile(path: string, ignoreManager: IgnoreManager) {
  if (ignoreManager.shouldIgnore(path)) {
    return { error: `File ${path} is excluded by .agentignore` };
  }
  return { content: await fs.readFile(path, 'utf-8') };
}
```

## Next Steps

In **Lesson 13: Client/Server Separation**, we'll build a server API that exposes the agent functionality, allowing multiple clients (CLI, web, IDE) to connect.

The rules system integrates naturally - clients can send rule updates, and the server rebuilds prompts dynamically!
