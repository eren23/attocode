# Lesson 17: Multi-Agent Coordination

> Multiple specialized agents working together as a team

## What You'll Learn

1. **Agent Roles**: Specialization through defined roles
2. **Communication**: Inter-agent message passing
3. **Consensus Protocols**: Reaching agreement when agents disagree
4. **Orchestration**: Coordinating task execution
5. **Coordination Patterns**: Common team structures

## Why This Matters

Single agents struggle with complex tasks:

```
Single Agent:
┌─────────────────────────────────────────────────────────┐
│  One agent tries to be an expert at everything          │
│  - Writes code                                          │
│  - Reviews its own code                                 │
│  - Tests its own code                                   │
│  Problem: Self-review bias, context switching overhead  │
└─────────────────────────────────────────────────────────┘

Multi-Agent Team:
┌─────────────────────────────────────────────────────────┐
│  Specialized agents collaborate                         │
│  Architect ──► Coder ──► Reviewer ──► Tester            │
│                                                         │
│  Benefits:                                              │
│  • Fresh perspectives (no self-review bias)             │
│  • Specialized prompts for each role                    │
│  • Parallel execution possible                          │
│  • Checks and balances                                  │
└─────────────────────────────────────────────────────────┘
```

## Key Concepts

### Agent Roles

```typescript
interface AgentRole {
  name: string;           // "Coder", "Reviewer", etc.
  description: string;
  capabilities: string[]; // ["write_code", "review_code"]
  systemPrompt: string;   // Role-specific instructions
  tools: string[];        // ["read_file", "write_file"]
  authority: number;      // For decision-making priority
}
```

### Communication Channel

```typescript
interface Message {
  from: string;           // Sender agent ID
  to: string;             // Recipient or "all"
  type: MessageType;      // "task_assignment", "opinion", etc.
  content: string;
  timestamp: Date;
}

// Message types
type MessageType =
  | 'task_assignment'
  | 'task_complete'
  | 'opinion'
  | 'vote'
  | 'review_request'
  | 'review_feedback';
```

### Consensus Strategies

```
Strategy    │ How it works              │ Best for
────────────┼───────────────────────────┼────────────────────
Authority   │ Highest authority decides │ Clear hierarchy
Voting      │ Majority wins             │ Democratic teams
Unanimous   │ All must agree            │ Critical decisions
Debate      │ Discuss until agreement   │ Complex tradeoffs
Weighted    │ confidence × authority    │ Balanced decisions
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Agent, team, and coordination types |
| `agent-roles.ts` | Predefined roles (Coder, Reviewer, etc.) |
| `communication.ts` | Inter-agent messaging |
| `consensus.ts` | Agreement protocols |
| `orchestrator.ts` | Task coordination |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:17
```

## Code Examples

### Creating Agents

```typescript
import { createAgent, CODER_ROLE, REVIEWER_ROLE } from './agent-roles.js';

const coder = createAgent(CODER_ROLE);
const reviewer = createAgent(REVIEWER_ROLE);

console.log(coder.role.capabilities); // ['write_code', 'refactor', ...]
```

### Building a Team

```typescript
import { TeamBuilder, createAgentsFromRoles, DEV_TEAM_ROLES } from './orchestrator.js';

const team = new TeamBuilder()
  .setName('Development Team')
  .addAgents(createAgentsFromRoles(DEV_TEAM_ROLES))
  .setConsensusStrategy('voting')
  .setParallelExecution(true)
  .build();
```

### Communication

```typescript
import { createChannel, createTaskAssignment } from './communication.js';

const channel = createChannel();

// Subscribe to messages
channel.subscribe((msg) => {
  console.log(`${msg.from} → ${msg.to}: ${msg.content}`);
});

// Send task assignment
await channel.send(
  createTaskAssignment('orchestrator', 'agent-coder-1', 'task-1', 'Implement login')
);
```

### Reaching Consensus

```typescript
import { ConsensusEngine, createOpinion } from './consensus.js';

const engine = new ConsensusEngine('voting');

const opinions = [
  createOpinion('coder', 'Use React', 'Popular framework', 0.8),
  createOpinion('reviewer', 'Use Vue', 'Simpler API', 0.7),
  createOpinion('tester', 'Use React', 'Better testing tools', 0.6),
];

const decision = await engine.decide(opinions, team.agents);

console.log(decision.decision);  // 'Use React'
console.log(decision.support);   // 0.7 (support level)
console.log(decision.dissent);   // [{ agentId: 'reviewer', ... }]
```

### Orchestrating Tasks

```typescript
import { createOrchestrator, createTeamTask } from './orchestrator.js';

const orchestrator = createOrchestrator('voting');

const task = createTeamTask('Implement authentication', {
  requiredCapabilities: ['write_code', 'review_code'],
  priority: 'high',
  subtasks: [
    'Design auth flow',
    'Implement endpoints',
    'Write tests',
  ],
});

// Assign to appropriate agents
await orchestrator.assignTask(task, team);

// Execute with coordination
const result = await orchestrator.coordinate(task, team);

console.log(result.success);
console.log(result.agentResults);
```

## Coordination Patterns

### Pipeline (Sequential)

```
Architect → Coder → Reviewer → Tester
```
Best for: Waterfall-style workflows

### Parallel with Merge

```
┌─ Coder A ─┐
            ├─► Reviewer
└─ Coder B ─┘
```
Best for: Parallelizable subtasks

### Hub and Spoke

```
        ┌─ Coder
Manager ├─ Reviewer
        └─ Tester
```
Best for: Centralized coordination

## Consensus Strategies

### Authority

Highest authority agent decides:
```typescript
const engine = new ConsensusEngine('authority');
// Architect (authority: 5) overrides Coder (authority: 3)
```

### Voting

Majority wins:
```typescript
const engine = new ConsensusEngine('voting');
// 2 votes for React, 1 for Vue → React wins
```

### Weighted

Votes weighted by confidence × authority:
```typescript
const engine = new ConsensusEngine('weighted');
// Higher confidence + higher authority = more influence
```

### Debate

Agents can change opinions based on others' reasoning:
```typescript
const engine = new ConsensusEngine('debate', 3); // 3 rounds max
// Lower confidence agents may be persuaded by higher confidence ones
```

## Trade-offs

| Aspect | Single Agent | Multi-Agent |
|--------|--------------|-------------|
| Quality | Self-review bias | Fresh perspectives |
| Speed | No coordination overhead | Parallel execution possible |
| Cost | 1 LLM call | Multiple LLM calls |
| Complexity | Simple | Coordination needed |
| Robustness | Single point of failure | Redundancy |

## Best Practices

### Define Clear Roles
- Each role should have distinct capabilities
- Avoid overlapping responsibilities
- Set appropriate authority levels

### Minimize Communication
- Only essential messages
- Batch related communications
- Use efficient message formats

### Choose Right Consensus
- Authority for speed
- Voting for buy-in
- Debate for complex decisions

### Handle Failures
- Agents can fail or timeout
- Have fallback strategies
- Log decisions for debugging

## Advanced: Agent Registry

The production agent implements a full **AgentRegistry** system for managing spawnable agents. This goes beyond static roles to support user-defined agents, hot-reloading, and natural language-based routing.

### Agent Definition

```typescript
interface AgentDefinition {
  name: string;              // Unique identifier
  description: string;       // Human-readable description
  systemPrompt: string;      // Role-specific instructions
  tools?: string[];          // Whitelist of tool names (all if omitted)
  model?: 'fast' | 'balanced' | 'quality' | string;
  maxTokenBudget?: number;
  maxIterations?: number;
  capabilities?: string[];   // Keywords for NL matching
  tags?: string[];           // Tags for discovery
}
```

### Built-in Agents

```typescript
const BUILTIN_AGENTS: AgentDefinition[] = [
  {
    name: 'researcher',
    description: 'Explores codebases and gathers information',
    systemPrompt: `You are a code researcher. Your job is to:
- Explore codebases thoroughly
- Find relevant files and functions
- Summarize code structure and patterns`,
    tools: ['read_file', 'list_files', 'glob', 'grep'],
    model: 'fast',
    maxTokenBudget: 50000,
    capabilities: ['explore', 'search', 'find', 'understand'],
  },
  {
    name: 'coder',
    description: 'Writes and modifies code',
    tools: ['read_file', 'write_file', 'edit_file', 'bash'],
    model: 'balanced',
    capabilities: ['write', 'implement', 'fix', 'create'],
  },
  {
    name: 'reviewer',
    description: 'Reviews code for quality, bugs, and security',
    tools: ['read_file', 'list_files', 'glob', 'grep'],
    model: 'quality',
    capabilities: ['review', 'check', 'audit', 'verify'],
  },
  {
    name: 'architect',
    description: 'Designs system architecture and structure',
    model: 'quality',
    capabilities: ['design', 'plan', 'architect', 'structure'],
  },
  // ... more built-in agents
];
```

### User-Defined Agents

Users can define custom agents in `.agents/` directory using YAML:

```yaml
# .agents/security-reviewer.yaml
name: security-reviewer
description: Reviews code for security vulnerabilities
systemPrompt: |
  You are a security expert. Focus on:
  - Injection vulnerabilities (SQL, XSS, command)
  - Authentication/authorization issues
  - Sensitive data exposure
  - Known CVEs in dependencies
tools: [read_file, grep, glob, list_files]
model: quality
maxTokenBudget: 80000
capabilities: [security, vulnerability, audit, cve]
tags: [security, review, audit]
```

Or JSON:

```json
{
  "name": "test-writer",
  "description": "Writes comprehensive test suites",
  "systemPrompt": "You are a testing expert...",
  "tools": ["read_file", "write_file", "edit_file", "bash"],
  "capabilities": ["test", "spec", "coverage", "mock"]
}
```

### Agent Registry Class

```typescript
class AgentRegistry {
  private agents = new Map<string, LoadedAgent>();

  constructor(baseDir?: string) {
    // Load built-in agents
    for (const agent of BUILTIN_AGENTS) {
      this.agents.set(agent.name, { ...agent, source: 'builtin', loadedAt: new Date() });
    }
  }

  // Load user agents from .agents/ directory
  async loadUserAgents(): Promise<void> {
    const agentsDir = join(this.baseDir, '.agents');
    if (!existsSync(agentsDir)) return;

    const files = await readdir(agentsDir);
    for (const file of files) {
      if (file.endsWith('.yaml') || file.endsWith('.json')) {
        await this.loadAgentFile(join(agentsDir, file));
      }
    }
  }

  // Find agents matching a natural language query
  findMatchingAgents(query: string, limit = 3): LoadedAgent[] {
    const queryLower = query.toLowerCase();
    const scored: Array<{ agent: LoadedAgent; score: number }> = [];

    for (const agent of this.agents.values()) {
      let score = 0;

      // Check name match
      if (queryLower.includes(agent.name)) score += 10;

      // Check capabilities match
      for (const cap of agent.capabilities || []) {
        if (queryLower.includes(cap)) score += 5;
      }

      // Check tags match
      for (const tag of agent.tags || []) {
        if (queryLower.includes(tag)) score += 3;
      }

      if (score > 0) scored.push({ agent, score });
    }

    return scored
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map(s => s.agent);
  }

  // Register agent at runtime
  registerAgent(definition: AgentDefinition): void {
    this.agents.set(definition.name, {
      ...definition,
      source: 'user',
      loadedAt: new Date(),
    });
  }
}
```

### Auto-Routing by Query

```typescript
// Route task to best agent based on description
async function routeToAgent(task: string, registry: AgentRegistry) {
  const matches = registry.findMatchingAgents(task);

  if (matches.length === 0) {
    // Default to coder agent
    return registry.getAgent('coder');
  }

  // Use top match
  return matches[0];
}

// Example usage
const agent = await routeToAgent('review this code for security issues', registry);
// → Returns security-reviewer (matches 'review' and 'security' capabilities)

const agent2 = await routeToAgent('explore the authentication module', registry);
// → Returns researcher (matches 'explore' capability)
```

### Integration Pattern

```typescript
// Create registry and load agents
const registry = await createAgentRegistry(process.cwd());
await registry.loadUserAgents();

// Watch for changes (hot reload)
registry.startWatching();

// Route and spawn
async function handleTask(task: string) {
  const agentDef = await routeToAgent(task, registry);

  // Filter tools based on agent definition
  const tools = filterToolsForAgent(agentDef, allTools);

  // Spawn with specialized config
  const agent = createAgent({
    systemPrompt: agentDef.systemPrompt,
    tools,
    maxTokenBudget: agentDef.maxTokenBudget,
    model: resolveModel(agentDef.model),
  });

  return agent.run(task);
}
```

### Events

```typescript
type RegistryEvent =
  | { type: 'agent.loaded'; name: string; source: string }
  | { type: 'agent.reloaded'; name: string }
  | { type: 'agent.removed'; name: string }
  | { type: 'agent.spawned'; name: string; task: string }
  | { type: 'agent.completed'; name: string; success: boolean };

registry.on((event) => {
  if (event.type === 'agent.loaded') {
    console.log(`Agent ${event.name} loaded from ${event.source}`);
  }
});
```

## Next Steps

In **Lesson 18: ReAct Pattern**, we'll explore how agents can think explicitly:
- Structured reasoning traces
- Thought → Action → Observation loops
- Better tool use decisions
