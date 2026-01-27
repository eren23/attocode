# Lesson 23: Execution Policies & Intent Classification

This lesson teaches granular control over tool execution through policy-based decisions and intent classification. Inspired by patterns from Codex and similar production agent systems.

## Key Concepts

### Three-Tier Policy System

Tools are classified into three policy levels:

| Policy | Behavior | Use Case |
|--------|----------|----------|
| `allow` | Execute without confirmation | Read-only operations, safe commands |
| `prompt` | Require user approval | Write operations, network access |
| `forbidden` | Block execution | Destructive operations, security risks |

### Intent Classification

Distinguishes between:

- **Deliberate**: User explicitly requested this action
- **Inferred**: Reasonable inference from user's request
- **Accidental**: Likely hallucinated or unintended
- **Unknown**: Cannot determine intent

### Permission Grants

Temporary allowances that can be:
- Scoped to specific arguments
- Limited by time or usage count
- Tracked for audit compliance

## Files

| File | Purpose |
|------|---------|
| `types.ts` | Type definitions for policies, intents, grants |
| `policy-manager.ts` | Policy configuration and permission management |
| `intent-classifier.ts` | Evidence-based intent classification |
| `policy-evaluator.ts` | Combines policies, conditions, and intent |
| `main.ts` | Interactive demo of all features |

## Usage

### Basic Policy Manager

```typescript
import { createPolicyManager, POLICY_PRESETS } from './policy-manager.js';

const manager = createPolicyManager({
  defaultPolicy: 'prompt',
  readOnlyTools: ['read_file', 'search'],
  writeTools: ['write_file'],
  destructiveTools: ['delete_file'],
});

// Check if a tool call is allowed
const result = manager.quickCheck({
  name: 'read_file',
  args: { path: '/etc/hosts' }
});
// { allowed: true, reason: 'Tool is allowed by policy' }
```

### Conditional Policies

```typescript
manager.setToolPolicy('bash', {
  policy: 'prompt',
  riskLevel: 'high',
  conditions: [
    // Allow safe commands
    { argMatch: { command: /^ls\s/ }, policy: 'allow' },
    // Forbid dangerous commands
    { argMatch: { command: /^rm\s/ }, policy: 'forbidden' },
  ],
});
```

### Intent Classification

```typescript
import { createIntentClassifier } from './intent-classifier.js';

const classifier = createIntentClassifier();

const intent = await classifier.classify(
  { name: 'delete_file', args: { path: 'data.db' } },
  [{ role: 'user', content: 'What files are in this directory?' }]
);

// intent.type === 'accidental' - user didn't ask for deletion
// intent.confidence === 0.15 - low confidence this was intended
```

### Full Policy Evaluation

```typescript
import { createPolicyEvaluator, buildContext } from './policy-evaluator.js';

const evaluator = createPolicyEvaluator({
  defaultPolicy: 'prompt',
  intentAware: true,
  intentThreshold: 0.8,
});

const context = buildContext()
  .toolCall({ name: 'write_file', args: { path: 'notes.txt' } })
  .addMessage('user', 'Create a notes file')
  .interactiveSession('user123')
  .build();

const decision = await evaluator.evaluate(toolCall, context);
// decision.allowed === true (high-confidence deliberate intent)
```

### Permission Grants

```typescript
// Grant one-time permission
const grant = manager.grantFromUser('deploy', 'admin', {
  allowedArgs: { environment: 'production' },
  maxUses: 1,
  expiresIn: 300000, // 5 minutes
  reason: 'Admin approved deployment',
});

// Check grant
const hasGrant = manager.hasActiveGrant('deploy', { environment: 'production' });

// Use and consume grant
manager.useGrant(grant.id);
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Policy Evaluator                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐ │
│  │   Policy     │  │    Intent     │  │  Permission  │ │
│  │   Manager    │  │  Classifier   │  │    Store     │ │
│  └──────────────┘  └───────────────┘  └──────────────┘ │
│         │                  │                  │         │
│         ▼                  ▼                  ▼         │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Policy Decision                      │  │
│  │  • allowed: boolean                               │  │
│  │  • policy: 'allow' | 'prompt' | 'forbidden'      │  │
│  │  • intent?: IntentClassification                  │  │
│  │  • usedGrant?: PermissionGrant                   │  │
│  └──────────────────────────────────────────────────┘  │
│                          │                              │
│                          ▼                              │
│                    Audit Log                            │
└─────────────────────────────────────────────────────────┘
```

## Intent Evidence Types

The classifier gathers evidence from multiple sources:

| Evidence Type | Description | Weight |
|--------------|-------------|--------|
| `explicit_request` | User directly asked for this action | +0.9 |
| `keyword_match` | User message contains related keywords | +0.6-0.8 |
| `context_flow` | Logical follow-up to previous actions | +0.4-0.6 |
| `pattern_match` | Matches known intent patterns | +0.3 |
| `hallucination_sign` | Suspicious fabricated-looking values | -0.7 |
| `contradiction` | Contradicts user's stated intent | -0.9 |

## Policy Presets

Built-in presets for common tool categories:

```typescript
import { POLICY_PRESETS } from './types.js';

// Available presets:
POLICY_PRESETS.readOnly      // allow, low risk
POLICY_PRESETS.write         // prompt, medium risk
POLICY_PRESETS.destructive   // forbidden, critical risk
POLICY_PRESETS.network       // prompt, medium risk
POLICY_PRESETS.shell         // prompt, high risk
```

## Running the Demo

```bash
npx tsx 23-execution-policies/main.ts
```

The demo covers:
1. Basic policy management
2. Conditional policies with argument matching
3. Intent classification scenarios
4. Full policy evaluation with intent
5. Permission grant workflow

## Best Practices

1. **Default to prompt**: Start restrictive and open up as needed
2. **Use conditions wisely**: Be specific about what's allowed/forbidden
3. **Enable intent classification**: Catches many hallucination cases
4. **Audit everything**: Enable audit logging in production
5. **Grant carefully**: Use short expiration times and limited uses
6. **Handle suggestions**: Present alternatives when blocking

## Integration with Production Agent

In Lesson 25, this system integrates with the production agent:

```typescript
const agent = buildAgent()
  .provider(myProvider)
  .executionPolicy({
    defaultPolicy: 'prompt',
    intentAware: true,
    toolPolicies: {
      read_file: { policy: 'allow' },
      bash: {
        policy: 'prompt',
        conditions: [/* ... */]
      },
    },
  })
  .build();
```

## Next Steps

- **Lesson 24**: Advanced patterns including thread management and configuration-driven agents
- **Lesson 25**: Full production agent with all features integrated
