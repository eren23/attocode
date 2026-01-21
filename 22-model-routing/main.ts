/**
 * Lesson 22: Model Routing & Fallbacks
 *
 * This lesson demonstrates intelligent model selection based on:
 * - Task requirements and complexity
 * - Cost optimization and budget constraints
 * - Fallback handling and graceful degradation
 *
 * Run: npm run lesson:22
 */

import chalk from 'chalk';
import {
  type TaskContext,
  type RoutingRule,
  DEFAULT_MODEL_CAPABILITIES,
} from './types.js';
import {
  SimpleModelRegistry,
  CapabilityMatcher,
  calculateComplexityScore,
  getComplexityLevel,
  analyzeTaskText,
  SCORING_PRESETS,
} from './capability-matcher.js';
import {
  SmartRouter,
  RuleBuilder,
  ComplexityRouter,
  createRouter,
} from './router.js';
import {
  FallbackChain,
  FallbackBuilder,
  CircuitBreaker,
  CircuitBreakerRegistry,
} from './fallback-chain.js';
import {
  CostTracker,
  CostEstimator,
  CostOptimizer,
  CostReportGenerator,
} from './cost-optimizer.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 22: Model Routing & Fallbacks                ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: WHY MODEL ROUTING?
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Why Model Routing?'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nOne model doesn\'t fit all tasks:'));
console.log(chalk.gray(`
  ┌─────────────────────────────────────────────────────────┐
  │  Task: "Translate 'hello' to French"                    │
  │  ❌ Using GPT-4: $0.045 (overkill!)                     │
  │  ✓ Using GPT-3.5: $0.001 (perfect fit)                  │
  │                                                         │
  │  Task: "Prove this mathematical theorem"                │
  │  ❌ Using GPT-3.5: May fail or give wrong answer        │
  │  ✓ Using Claude-3-Opus: Best reasoning capabilities     │
  │                                                         │
  │  Solution: Route tasks to appropriate models            │
  └─────────────────────────────────────────────────────────┘
`));

// =============================================================================
// PART 2: MODEL CAPABILITIES
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Model Capabilities'));
console.log(chalk.gray('─'.repeat(60)));

const registry = new SimpleModelRegistry();

console.log(chalk.green('\nAvailable models:'));
console.log(chalk.gray('─'.repeat(75)));
console.log(chalk.gray(
  '  Model'.padEnd(20) +
  'Quality'.padStart(8) +
  'Input/1K'.padStart(10) +
  'Output/1K'.padStart(10) +
  'Latency'.padStart(10) +
  'Tools'.padStart(8) +
  'Vision'.padStart(8)
));
console.log(chalk.gray('─'.repeat(75)));

for (const model of registry.listModels()) {
  const name = model.model.padEnd(18);
  const quality = String(model.qualityScore).padStart(8);
  const input = `$${model.costPer1kInput.toFixed(4)}`.padStart(10);
  const output = `$${model.costPer1kOutput.toFixed(4)}`.padStart(10);
  const latency = `${model.latencyMs}ms`.padStart(10);
  const tools = (model.supportsTools ? '✓' : '✗').padStart(8);
  const vision = (model.supportsVision ? '✓' : '✗').padStart(8);

  console.log(chalk.gray(`  ${name}${quality}${input}${output}${latency}${tools}${vision}`));
}

// =============================================================================
// PART 3: COMPLEXITY ESTIMATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Task Complexity Estimation'));
console.log(chalk.gray('─'.repeat(60)));

const taskExamples: TaskContext[] = [
  {
    task: 'Translate hello to Spanish',
    estimatedInputTokens: 50,
    expectedOutputSize: 'small',
    requiresTools: false,
    requiresVision: false,
    requiresStructuredOutput: false,
    complexity: 'simple',
    qualityRequirement: 'low',
    latencyRequirement: 'fast',
    taskType: 'translation',
  },
  {
    task: 'Analyze this codebase and suggest improvements',
    estimatedInputTokens: 5000,
    expectedOutputSize: 'large',
    requiresTools: true,
    requiresVision: false,
    requiresStructuredOutput: false,
    complexity: 'complex',
    qualityRequirement: 'high',
    latencyRequirement: 'normal',
    taskType: 'code_review',
  },
  {
    task: 'Explain why the sky is blue',
    estimatedInputTokens: 100,
    expectedOutputSize: 'medium',
    requiresTools: false,
    requiresVision: false,
    requiresStructuredOutput: false,
    complexity: 'moderate',
    qualityRequirement: 'medium',
    latencyRequirement: 'normal',
    taskType: 'reasoning',
  },
];

console.log(chalk.green('\nComplexity analysis:'));
for (const task of taskExamples) {
  const score = calculateComplexityScore(task);
  const level = getComplexityLevel(score);
  const bar = '█'.repeat(Math.round(score * 20)).padEnd(20);

  console.log(chalk.white(`\n  "${task.task.slice(0, 40)}..."`));
  console.log(chalk.gray(`    Score: ${score.toFixed(2)} [${bar}] ${level}`));
}

// =============================================================================
// PART 4: CAPABILITY MATCHING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Capability Matching'));
console.log(chalk.gray('─'.repeat(60)));

const matcher = new CapabilityMatcher(registry, SCORING_PRESETS.balanced);

console.log(chalk.green('\nMatching tasks to models:'));

for (const task of taskExamples) {
  console.log(chalk.white(`\n  Task: "${task.task.slice(0, 50)}..."`));

  const topModels = matcher.findTopModels(task, 3);

  for (let i = 0; i < topModels.length; i++) {
    const m = topModels[i];
    const prefix = i === 0 ? chalk.green('  ✓') : chalk.gray('   ');
    const score = `(score: ${m.totalScore.toFixed(2)})`;
    console.log(`${prefix} ${m.model.padEnd(20)} ${score}`);
    console.log(chalk.gray(`      Reasons: ${m.reasons.slice(0, 2).join(', ')}`));
  }
}

// =============================================================================
// PART 5: ROUTING RULES
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Routing Rules'));
console.log(chalk.gray('─'.repeat(60)));

const router = createRouter(registry);

// Add a custom rule
const customRule = new RuleBuilder()
  .name('code-generation-sonnet')
  .when((task) => task.taskType === 'code_generation')
  .routeTo('claude-3-sonnet')
  .withPriority(10)
  .describe('Route code generation to Claude Sonnet')
  .build();

router.addRule(customRule);

console.log(chalk.green('\nRouting decisions:'));

for (const task of taskExamples) {
  const decision = await router.route(task);

  console.log(chalk.white(`\n  Task: "${task.task.slice(0, 40)}..."`));
  console.log(chalk.green(`    → ${decision.model}`));
  console.log(chalk.gray(`      Reason: ${decision.reason}`));
  console.log(chalk.gray(`      Estimated cost: $${decision.estimatedCost.toFixed(4)}`));
  console.log(chalk.gray(`      Confidence: ${(decision.confidence * 100).toFixed(0)}%`));

  if (decision.matchedRule) {
    console.log(chalk.blue(`      Matched rule: ${decision.matchedRule}`));
  }

  if (decision.alternatives.length > 0) {
    console.log(chalk.gray(`      Alternatives: ${decision.alternatives.map((a) => a.model).join(', ')}`));
  }
}

// =============================================================================
// PART 6: COMPLEXITY-BASED ROUTING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Complexity-Based Routing'));
console.log(chalk.gray('─'.repeat(60)));

const complexityRouter = new ComplexityRouter({
  simple: 'claude-3-haiku',
  moderate: 'claude-3-sonnet',
  complex: 'claude-3-opus',
});

console.log(chalk.green('\nSimple routing by complexity:'));

for (const task of taskExamples) {
  const result = complexityRouter.explain(task);
  console.log(chalk.white(`\n  "${task.task.slice(0, 40)}..."`));
  console.log(chalk.gray(`    Complexity: ${result.complexity} (${result.score.toFixed(2)})`));
  console.log(chalk.green(`    → ${result.model}`));
}

// =============================================================================
// PART 7: FALLBACK CHAINS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Fallback Chains'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nFallback chain concept:'));
console.log(chalk.gray(`
  Primary: claude-3-sonnet
      │
      ▼ (rate limit)
  Fallback 1: claude-3-haiku
      │
      ▼ (error)
  Fallback 2: gpt-3.5-turbo
`));

const fallbackConfig = new FallbackBuilder()
  .primary('claude-3-sonnet')
  .fallbackTo('claude-3-haiku')
  .fallbackTo('gpt-3.5-turbo')
  .maxRetries(2)
  .retryDelay(100)
  .exponentialBackoff(true)
  .build();

console.log(chalk.green('\nSimulating fallback execution:'));

// Simulate model calls with failures
let callCount = 0;
const fallbackChain = new FallbackChain<string>(fallbackConfig);

fallbackChain.on((event) => {
  if (event.type === 'fallback.triggered') {
    console.log(chalk.yellow(`    ⚠ Fallback triggered: ${event.fromModel} → ${event.toModel}`));
    console.log(chalk.gray(`      Reason: ${event.trigger}`));
  }
});

const result = await fallbackChain.execute(async (model) => {
  callCount++;
  // Simulate first model failing
  if (callCount === 1) {
    throw new Error('Rate limit exceeded (429)');
  }
  return `Response from ${model}`;
});

console.log(chalk.white('\n  Result:'));
console.log(chalk.gray(`    Success: ${result.success}`));
console.log(chalk.gray(`    Success model: ${result.successModel}`));
console.log(chalk.gray(`    Total time: ${result.totalTimeMs}ms`));
console.log(chalk.gray(`    Models attempted: ${result.attemptedModels.map((a) => a.model).join(' → ')}`));

// =============================================================================
// PART 8: CIRCUIT BREAKERS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 8: Circuit Breakers'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nCircuit breaker prevents cascade failures:'));
console.log(chalk.gray(`
  CLOSED  ──[failures]──►  OPEN  ──[timeout]──►  HALF-OPEN
     ▲                       │                        │
     │                       │                        ▼
     └───[successes]─────────┴───────[failure]────────┘
`));

const circuitBreaker = new CircuitBreaker('claude-3-opus', 3, 2, 5000);

console.log(chalk.green('\nSimulating circuit breaker:'));
console.log(chalk.gray(`  Initial state: ${circuitBreaker.getState()}`));

// Simulate failures
for (let i = 0; i < 4; i++) {
  circuitBreaker.recordFailure();
  console.log(chalk.gray(`  After failure ${i + 1}: ${circuitBreaker.getState()}`));
}

console.log(chalk.gray(`  Can request? ${circuitBreaker.canRequest()}`));

// Reset for demo
circuitBreaker.reset();
console.log(chalk.gray(`  After reset: ${circuitBreaker.getState()}`));

// =============================================================================
// PART 9: COST OPTIMIZATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 9: Cost Optimization'));
console.log(chalk.gray('─'.repeat(60)));

const costConfig = {
  dailyBudget: 10.0,
  perRequestBudget: 0.5,
  alertThreshold: 0.8,
  optimizeForCost: false,
  minimumQualityScore: 60,
};

const costOptimizer = new CostOptimizer(costConfig, registry, 'balanced');
const estimator = costOptimizer.getEstimator();

console.log(chalk.green('\nCost comparison for a coding task:'));

const codingTask: TaskContext = {
  task: 'Implement a binary search algorithm',
  estimatedInputTokens: 500,
  expectedOutputSize: 'medium',
  requiresTools: false,
  requiresVision: false,
  requiresStructuredOutput: false,
  complexity: 'moderate',
  qualityRequirement: 'high',
  latencyRequirement: 'normal',
  taskType: 'code_generation',
};

console.log(chalk.gray(CostReportGenerator.modelComparisonReport(estimator, codingTask)));

// Select optimal model
const optimal = costOptimizer.selectModel(codingTask);
if (optimal) {
  console.log(chalk.green(`\n  Optimal selection: ${optimal.model}`));
  console.log(chalk.gray(`    Estimated cost: $${optimal.estimate.totalCost.toFixed(4)}`));
}

// =============================================================================
// PART 10: BUDGET TRACKING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 10: Budget Tracking'));
console.log(chalk.gray('─'.repeat(60)));

const tracker = costOptimizer.getTracker();

// Simulate some usage
tracker.recordCost('claude-3-sonnet', 0.05);
tracker.recordCost('claude-3-sonnet', 0.03);
tracker.recordCost('claude-3-haiku', 0.001);
tracker.recordCost('claude-3-opus', 0.15);

console.log(chalk.gray(CostReportGenerator.dailyReport(tracker)));

// =============================================================================
// PART 11: TASK TEXT ANALYSIS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 11: Task Text Analysis'));
console.log(chalk.gray('─'.repeat(60)));

const taskTexts = [
  'Write a Python function to sort a list',
  'Analyze this image and describe what you see',
  'Quickly summarize this article',
  'Extract the JSON data from this document',
];

console.log(chalk.green('\nInferring task context from text:'));

for (const text of taskTexts) {
  const inferred = analyzeTaskText(text);
  console.log(chalk.white(`\n  "${text}"`));
  for (const [key, value] of Object.entries(inferred)) {
    console.log(chalk.gray(`    ${key}: ${value}`));
  }
}

// =============================================================================
// PART 12: SCORING PRESETS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 12: Scoring Presets'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nAvailable optimization presets:'));

for (const [name, weights] of Object.entries(SCORING_PRESETS)) {
  console.log(chalk.white(`\n  ${name.toUpperCase()}`));
  console.log(chalk.gray(`    Capability: ${(weights.capability * 100).toFixed(0)}%`));
  console.log(chalk.gray(`    Cost:       ${(weights.cost * 100).toFixed(0)}%`));
  console.log(chalk.gray(`    Latency:    ${(weights.latency * 100).toFixed(0)}%`));
  console.log(chalk.gray(`    Quality:    ${(weights.quality * 100).toFixed(0)}%`));
  console.log(chalk.gray(`    Reliability: ${(weights.reliability * 100).toFixed(0)}%`));
}

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. Different models have different strengths and costs'));
console.log(chalk.gray('  2. Task complexity helps choose the right model'));
console.log(chalk.gray('  3. Capability matching scores models for tasks'));
console.log(chalk.gray('  4. Routing rules provide explicit control'));
console.log(chalk.gray('  5. Fallback chains handle model failures gracefully'));
console.log(chalk.gray('  6. Circuit breakers prevent cascade failures'));
console.log(chalk.gray('  7. Cost optimization balances quality vs budget'));
console.log();
console.log(chalk.white('Key components:'));
console.log(chalk.gray('  • ModelRegistry - Tracks model capabilities'));
console.log(chalk.gray('  • CapabilityMatcher - Scores models for tasks'));
console.log(chalk.gray('  • SmartRouter - Routes with rules and matching'));
console.log(chalk.gray('  • FallbackChain - Handles failures gracefully'));
console.log(chalk.gray('  • CircuitBreaker - Prevents repeated failures'));
console.log(chalk.gray('  • CostOptimizer - Manages budget constraints'));
console.log();
console.log(chalk.bold.green('Congratulations! You\'ve completed the AI reasoning lessons.'));
console.log(chalk.gray('Review earlier lessons or explore the atomic tricks!'));
console.log();
