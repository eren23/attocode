# Lesson 16: Self-Reflection & Critique

> Teaching agents to evaluate and improve their own output

## What You'll Learn

1. **Reflection Prompts**: Designing prompts for self-evaluation
2. **Output Critique**: Structured quality assessment
3. **Reflection Loops**: Iterative improvement cycles
4. **Quality Scoring**: Multi-dimensional output evaluation
5. **Trajectory Analysis**: Understanding improvement patterns

## Why This Matters

Without self-reflection, agents produce output without knowing if it's good. Reflection enables:

- **Quality Assurance**: Catch mistakes before delivery
- **Iterative Improvement**: Get better with each attempt
- **Transparency**: Understand why output was or wasn't satisfactory
- **Learning**: Identify patterns in failures and successes

## Key Concepts

### Reflection Result

```typescript
interface ReflectionResult {
  satisfied: boolean;        // Goal achieved?
  critique: string;          // Detailed feedback
  suggestions: string[];     // How to improve
  confidence: number;        // 0-1 assessment confidence
  issues: ReflectionIssue[]; // Specific problems found
  strengths: string[];       // What was done well
}
```

### Quality Dimensions

```
┌──────────────────────────────────────────────────────────┐
│                    Quality Score                         │
├──────────────────────────────────────────────────────────┤
│  Completeness  ████████░░  80%  Addresses all requirements│
│  Correctness   █████████░  90%  Accurate, error-free      │
│  Clarity       ███████░░░  70%  Easy to understand        │
│  Efficiency    ██████░░░░  60%  Optimal implementation    │
│  Style         ████████░░  80%  Follows conventions       │
├──────────────────────────────────────────────────────────┤
│  Overall                   76%                           │
└──────────────────────────────────────────────────────────┘
```

### Reflection Loop

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │ Execute  │───►│ Reflect  │───►│ Satisfied?       │  │
│  │ Task     │    │ on       │    │                  │  │
│  │          │    │ Output   │    │ Yes → Done ✓     │  │
│  └──────────┘    └──────────┘    │ No  → Improve    │  │
│       ▲                          └────────┬─────────┘  │
│       │                                   │            │
│       └───────────── Feedback ◄───────────┘            │
│                                                        │
└─────────────────────────────────────────────────────────┘
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Reflection types and interfaces |
| `reflector.ts` | Reflection prompt generation and processing |
| `critic.ts` | Output critique and quality scoring |
| `retry-loop.ts` | Reflection-driven retry mechanism |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:16
```

## Code Examples

### Basic Reflection

```typescript
import { SimpleReflector } from './reflector.js';

const reflector = new SimpleReflector({
  checkCompleteness: true,
  checkCorrectness: true,
  checkCodeQuality: true,
});

const result = await reflector.reflect(
  'Write a function to validate emails',
  `function validate(email) { return email.includes('@'); }`
);

console.log('Satisfied:', result.satisfied);
console.log('Confidence:', result.confidence);
console.log('Issues:', result.issues.length);
```

### Output Critique

```typescript
import { OutputCritic } from './critic.js';

const critic = new OutputCritic();

// Get detailed scores
const score = await critic.score(myCode);
console.log('Overall:', score.overall);
console.log('Completeness:', score.dimensions.completeness);
console.log('Correctness:', score.dimensions.correctness);

// Get full critique
const critique = await critic.critique(myCode, {
  checkCompleteness: true,
  checkCorrectness: true,
  checkCodeQuality: true,
  checkClarity: true,
  checkEdgeCases: true,
});

console.log('Assessment:', critique.assessment); // 'excellent' | 'good' | 'acceptable' | 'needs_work' | 'poor'
```

### Reflection Loop

```typescript
import { ReflectionLoop } from './retry-loop.js';

const loop = new ReflectionLoop({
  maxAttempts: 3,
  satisfactionThreshold: 0.8,
  includePreviousAttempts: true,
});

// Subscribe to events
loop.on((event) => {
  if (event.type === 'reflection.completed') {
    console.log(`Attempt ${event.attempt}: ${event.result.confidence * 100}% confidence`);
  }
});

// Execute with reflection
const result = await loop.executeSimple(
  async () => generateCode(requirements),
  'Generate a sorting function'
);

console.log(`Completed in ${result.attempts} attempts`);
console.log(`Final confidence: ${result.reflections.at(-1)?.confidence}`);
```

### Trajectory Analysis

```typescript
const result = await loop.execute(task, goal);

const analysis = loop.analyzeTrajectory(result);

console.log('Improved:', analysis.improved);
console.log('Convergence:', analysis.convergence);
// 'improving' | 'plateau' | 'declining' | 'oscillating'

if (analysis.bottleneck) {
  console.log('Common issue:', analysis.bottleneck);
}
```

## Reflection Prompts

### Standard Template

```
You are a critical evaluator. Assess whether the output achieves the goal.

## Goal
${goal}

## Output to Evaluate
${output}

## Your Task
Evaluate completeness, correctness, clarity, and quality.

Respond in JSON:
{
  "satisfied": boolean,
  "critique": "detailed feedback",
  "suggestions": ["improvement 1", "improvement 2"],
  "confidence": 0.0-1.0,
  "issues": [...],
  "strengths": [...]
}
```

### Code Review Template

Includes additional checks for:
- Syntax and logic errors
- Edge case handling
- Security concerns
- Code style and documentation

## Strictness Levels

```typescript
// Strict: Production code, security-sensitive
const strictLoop = createStrictLoop();
// - 5 max attempts
// - 0.9 satisfaction threshold
// - All criteria checked

// Lenient: Quick prototypes, internal tools
const lenientLoop = createLenientLoop();
// - 2 max attempts
// - 0.6 satisfaction threshold
// - Only completeness and correctness
```

## When to Use Reflection

### Use Reflection When:
- Output quality is critical
- Mistakes are expensive
- Task is complex or ambiguous
- User trust depends on accuracy

### Skip Reflection When:
- Task is simple and well-defined
- Speed matters more than quality
- Output is easily verifiable otherwise
- Cost/latency is a concern

## Issue Types

| Type | Description |
|------|-------------|
| `incomplete` | Missing required elements |
| `incorrect` | Factually wrong or buggy |
| `unclear` | Hard to understand |
| `inefficient` | Could be done better |
| `inconsistent` | Contradicts requirements |
| `off_topic` | Doesn't address the goal |
| `style` | Style or formatting issues |
| `security` | Security concerns |
| `edge_case` | Missing edge case handling |

## Best Practices

### Design Good Reflection Prompts
- Be specific about evaluation criteria
- Include context from previous attempts
- Request structured output format

### Choose Appropriate Strictness
- Match criteria to task importance
- Consider time/cost constraints
- Balance thoroughness with efficiency

### Analyze Patterns
- Track improvement trajectories
- Identify common bottlenecks
- Learn from failure patterns

### Prevent Infinite Loops
- Set reasonable max attempts
- Detect when improvement plateaus
- Allow human escalation for critical issues

## Next Steps

In **Lesson 17: Multi-Agent Coordination**, we'll explore how multiple agents can work together, combining reflection with collaboration:

- Agent roles and specialization
- Communication protocols
- Conflict resolution
- Team orchestration
