# Lesson 22: Model Routing & Fallbacks

> Intelligent model selection, cost optimization, and graceful degradation

## What You'll Learn

1. **Capability Matching**: Match tasks to models based on requirements
2. **Complexity Estimation**: Determine task difficulty for routing
3. **Cost Optimization**: Balance quality vs budget
4. **Fallback Chains**: Handle failures gracefully
5. **Circuit Breakers**: Prevent cascade failures

## Why This Matters

One model doesn't fit all tasks:

```
Without Routing:
┌─────────────────────────────────────────────────────────┐
│  Every task → GPT-4                                     │
│                                                         │
│  "Hello" translation: $0.045 (overkill!)                │
│  Simple classification: $0.045 (wasteful!)              │
│  Complex reasoning: $0.045 (appropriate)                │
│                                                         │
│  Total: 3× higher costs than necessary                  │
└─────────────────────────────────────────────────────────┘

With Intelligent Routing:
┌─────────────────────────────────────────────────────────┐
│  Simple tasks → GPT-3.5/Haiku: $0.001                   │
│  Medium tasks → Sonnet/GPT-4o: $0.015                   │
│  Complex tasks → Opus/GPT-4: $0.045                     │
│                                                         │
│  Result: 70% cost reduction, same quality               │
└─────────────────────────────────────────────────────────┘
```

## Key Concepts

### Model Capabilities

```typescript
interface ModelCapability {
  model: string;
  provider: string;
  maxTokens: number;
  supportsTools: boolean;
  supportsVision: boolean;
  costPer1kInput: number;
  costPer1kOutput: number;
  latencyMs: number;
  qualityScore: number;  // 0-100
}
```

### Task Context

```typescript
interface TaskContext {
  task: string;
  estimatedInputTokens: number;
  expectedOutputSize: 'small' | 'medium' | 'large';
  requiresTools: boolean;
  requiresVision: boolean;
  complexity: 'simple' | 'moderate' | 'complex';
  qualityRequirement: 'low' | 'medium' | 'high' | 'maximum';
  taskType?: 'code_generation' | 'reasoning' | 'chat' | ...;
}
```

### Routing Decision Flow

```
Task Received
      │
      ▼
┌──────────────┐    Yes    ┌────────────────┐
│ Check Rules  │ ────────► │ Use Rule Model │
└──────────────┘           └────────────────┘
      │ No
      ▼
┌──────────────┐
│ Score Models │──► Sort by weighted score
└──────────────┘
      │
      ▼
┌──────────────┐    No     ┌────────────────┐
│ Within Budget│ ────────► │ Find Cheaper   │
└──────────────┘           └────────────────┘
      │ Yes
      ▼
   Return Best
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Model, task, routing type definitions |
| `capability-matcher.ts` | Model registry and scoring |
| `router.ts` | Routing rules and decision logic |
| `fallback-chain.ts` | Retry and fallback handling |
| `cost-optimizer.ts` | Budget tracking and optimization |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:22
```

## Code Examples

### Basic Routing

```typescript
import { createRouter } from './router.js';

const router = createRouter();

const task = {
  task: 'Analyze this code',
  estimatedInputTokens: 2000,
  expectedOutputSize: 'medium',
  requiresTools: false,
  requiresVision: false,
  requiresStructuredOutput: false,
  complexity: 'moderate',
  qualityRequirement: 'high',
  latencyRequirement: 'normal',
  taskType: 'code_review',
};

const decision = await router.route(task);
console.log(`Use model: ${decision.model}`);
console.log(`Reason: ${decision.reason}`);
console.log(`Cost estimate: $${decision.estimatedCost}`);
```

### Custom Routing Rules

```typescript
import { RuleBuilder, SmartRouter } from './router.js';

const router = new SmartRouter();

// High-priority rule for vision tasks
router.addRule(
  new RuleBuilder()
    .name('vision-to-gpt4o')
    .when((task) => task.requiresVision)
    .routeTo('gpt-4o')
    .withPriority(5)
    .describe('Route vision tasks to GPT-4o')
    .build()
);

// Budget-conscious rule
router.addRule(
  new RuleBuilder()
    .name('budget-conscious')
    .when((task) => task.maxCost !== undefined && task.maxCost < 0.01)
    .routeTo('claude-3-haiku')
    .withPriority(1)  // Highest priority
    .build()
);
```

### Complexity-Based Routing

```typescript
import { ComplexityRouter } from './router.js';

const router = new ComplexityRouter({
  simple: 'claude-3-haiku',    // Fast, cheap
  moderate: 'claude-3-sonnet', // Balanced
  complex: 'claude-3-opus',    // Best quality
});

const model = router.route(task);
const explanation = router.explain(task);
// { model: 'claude-3-sonnet', complexity: 'moderate', score: 0.65 }
```

### Fallback Chains

```typescript
import { FallbackBuilder } from './fallback-chain.js';

const chain = new FallbackBuilder()
  .primary('claude-3-sonnet')
  .fallbackTo('claude-3-haiku')
  .fallbackTo('gpt-3.5-turbo')
  .maxRetries(2)
  .retryDelay(1000)
  .exponentialBackoff(true)
  .createChain<string>();

const result = await chain.execute(async (model) => {
  return await callModel(model, prompt);
});

if (result.success) {
  console.log(`Success with ${result.successModel}`);
} else {
  console.log(`All models failed`);
}
```

### Circuit Breakers

```typescript
import { CircuitBreakerRegistry } from './fallback-chain.js';

const breakers = new CircuitBreakerRegistry({
  failureThreshold: 5,
  successThreshold: 3,
  resetTimeoutMs: 30000,
});

// Before making a request
if (!breakers.canRequest('claude-3-opus')) {
  // Use fallback model instead
}

// After request
if (success) {
  breakers.recordSuccess('claude-3-opus');
} else {
  breakers.recordFailure('claude-3-opus');
}
```

### Cost Optimization

```typescript
import { CostOptimizer } from './cost-optimizer.js';

const optimizer = new CostOptimizer({
  dailyBudget: 10.0,
  perRequestBudget: 0.5,
  alertThreshold: 0.8,
  optimizeForCost: true,
  minimumQualityScore: 60,
});

// Select optimal model considering budget
const selection = optimizer.selectModel(task);

// Track actual usage
optimizer.recordUsage(selection.model, actualCost);

// Check budget
const remaining = optimizer.getTracker().getRemainingBudget();
```

## Scoring Presets

| Preset | Cost | Quality | Latency | Use Case |
|--------|------|---------|---------|----------|
| balanced | 20% | 25% | 15% | General purpose |
| quality | 10% | 45% | 10% | Critical tasks |
| cost | 40% | 15% | 10% | High volume |
| speed | 10% | 15% | 40% | Real-time apps |

## Model Comparison

| Model | Quality | Input $/1K | Output $/1K | Latency | Best For |
|-------|---------|------------|-------------|---------|----------|
| Claude-3-Opus | 95 | $0.015 | $0.075 | 2000ms | Complex reasoning |
| Claude-3-Sonnet | 85 | $0.003 | $0.015 | 1000ms | General coding |
| Claude-3-Haiku | 70 | $0.00025 | $0.00125 | 500ms | Simple tasks |
| GPT-4-Turbo | 90 | $0.01 | $0.03 | 1500ms | Long context |
| GPT-4o | 88 | $0.005 | $0.015 | 800ms | Vision + speed |
| GPT-3.5-Turbo | 60 | $0.0005 | $0.0015 | 400ms | High volume |

## Circuit Breaker States

```
CLOSED ──[failures exceed threshold]──► OPEN
   ▲                                       │
   │                                       │
   │                            [reset timeout]
   │                                       │
   │                                       ▼
   └───[successes exceed threshold]── HALF-OPEN
                                           │
                                           │
                            [any failure]──┘
```

## Best Practices

### 1. Start Simple
```typescript
// Begin with complexity-based routing
const router = new ComplexityRouter();
```

### 2. Add Rules Gradually
```typescript
// Only add rules when you identify patterns
router.addRule(visionRule);
router.addRule(budgetRule);
```

### 3. Monitor and Adjust
```typescript
const stats = router.getStats();
console.log('Fallback rate:', stats.fallbackRate);
console.log('Cost by model:', stats.costByModel);
```

### 4. Use Circuit Breakers
```typescript
// Prevent hammering failing models
const breakers = new CircuitBreakerRegistry();
```

### 5. Track Costs
```typescript
// Always record actual usage
optimizer.recordUsage(model, actualCost);
```

## Common Patterns

### A/B Testing Models
```typescript
router.addRule({
  name: 'ab-test-new-model',
  condition: () => Math.random() < 0.1, // 10% traffic
  model: 'new-model-v2',
  priority: 1,
  enabled: true,
});
```

### Gradual Rollout
```typescript
const rolloutPercent = 0.25; // Increase over time
router.addRule({
  name: 'gradual-rollout',
  condition: (task) => hash(task.id) < rolloutPercent,
  model: 'new-model',
  priority: 5,
  enabled: true,
});
```

### Peak Hour Optimization
```typescript
router.addRule({
  name: 'peak-hour-cheap',
  condition: () => {
    const hour = new Date().getHours();
    return hour >= 9 && hour <= 17; // Business hours
  },
  model: 'claude-3-haiku', // Use cheaper model
  priority: 50,
  enabled: true,
});
```

## Next Steps

Congratulations! You've completed the core AI reasoning lessons. Consider:

1. **Review earlier lessons** to reinforce concepts
2. **Explore atomic tricks** for advanced patterns
3. **Build a complete agent** combining all lessons
