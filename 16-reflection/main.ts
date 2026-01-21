/**
 * Lesson 16: Self-Reflection & Critique
 *
 * This lesson demonstrates how agents can evaluate and improve
 * their own output through reflection and iterative refinement.
 *
 * Key concepts:
 * 1. Reflection prompts and criteria
 * 2. Output critique and scoring
 * 3. Reflection-driven retry loops
 * 4. Trajectory analysis
 *
 * Run: npm run lesson:16
 */

import chalk from 'chalk';
import { SimpleReflector, REFLECTION_TEMPLATES } from './reflector.js';
import { OutputCritic, QUALITY_RUBRICS } from './critic.js';
import {
  ReflectionLoop,
  createStrictLoop,
  createLenientLoop,
  type TaskContext,
} from './retry-loop.js';
import type { ReflectionResult, QualityScore } from './types.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 16: Self-Reflection & Critique               ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: UNDERSTANDING REFLECTION
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Understanding Reflection'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nWhy self-reflection matters:'));
console.log(chalk.gray(`
  Without reflection:
    Goal → [Agent] → Output (might be wrong)

  With reflection:
    Goal → [Agent] → Output → [Reflect] → Satisfied? → Done
                                  ↓ No
                              Feedback → [Agent] → Better Output → ...

  Benefits:
  • Catches mistakes before delivery
  • Improves output quality iteratively
  • Provides transparency into decision-making
  • Enables learning from mistakes
`));

console.log(chalk.white('Reflection criteria we check:'));
Object.entries(QUALITY_RUBRICS).forEach(([key, rubric]) => {
  console.log(chalk.gray(`  • ${rubric.name}: ${rubric.description}`));
});

// =============================================================================
// PART 2: REFLECTION PROMPTS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Reflection Prompts'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nReflection prompt structure:'));
console.log(chalk.gray(`
  A good reflection prompt includes:
  1. Clear evaluation criteria
  2. The goal being pursued
  3. The output to evaluate
  4. Previous attempts (for context)
  5. Structured output format
`));

// Show a sample prompt
const sampleGoal = 'Write a function to validate email addresses';
const sampleOutput = `
function validateEmail(email) {
  return email.includes('@');
}
`;

const samplePrompt = REFLECTION_TEMPLATES.code(sampleGoal, sampleOutput);
console.log(chalk.green('\nSample reflection prompt (code review):'));
console.log(chalk.gray(samplePrompt.slice(0, 500) + '...'));

// =============================================================================
// PART 3: BASIC REFLECTION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Basic Reflection'));
console.log(chalk.gray('─'.repeat(60)));

const reflector = new SimpleReflector({
  checkCompleteness: true,
  checkCorrectness: true,
  checkCodeQuality: true,
  checkClarity: true,
});

// Test outputs with different quality levels
const testCases = [
  {
    name: 'Good output',
    goal: 'Write a function to add two numbers',
    output: `
/**
 * Adds two numbers together.
 * @param a First number
 * @param b Second number
 * @returns The sum of a and b
 */
function add(a: number, b: number): number {
  return a + b;
}
    `.trim(),
  },
  {
    name: 'Incomplete output',
    goal: 'Write a complete REST API client',
    output: `
class APIClient {
  // TODO: implement fetch method
  // FIXME: add error handling
}
    `.trim(),
  },
  {
    name: 'Code with issues',
    goal: 'Write a secure user authentication function',
    output: `
function auth(user, pass) {
  console.log("Checking auth for", user, pass);
  if (user == "admin" && pass == "password123") {
    return true;
  }
  return false;
}
    `.trim(),
  },
];

console.log(chalk.green('\nReflecting on different outputs:'));

for (const testCase of testCases) {
  console.log(chalk.white(`\n  ${testCase.name}:`));
  console.log(chalk.gray(`  Goal: ${testCase.goal}`));

  const reflection = await reflector.reflect(testCase.goal, testCase.output);

  console.log(chalk.gray(`  Satisfied: ${reflection.satisfied ? chalk.green('Yes') : chalk.red('No')}`));
  console.log(chalk.gray(`  Confidence: ${(reflection.confidence * 100).toFixed(0)}%`));

  if (reflection.issues.length > 0) {
    console.log(chalk.gray('  Issues:'));
    for (const issue of reflection.issues.slice(0, 3)) {
      const severityColor = {
        critical: chalk.red,
        high: chalk.yellow,
        medium: chalk.blue,
        low: chalk.gray,
      }[issue.severity];
      console.log(severityColor(`    • [${issue.severity}] ${issue.description}`));
    }
  }

  if (reflection.strengths.length > 0) {
    console.log(chalk.gray('  Strengths:'));
    for (const strength of reflection.strengths) {
      console.log(chalk.green(`    ✓ ${strength}`));
    }
  }
}

// =============================================================================
// PART 4: OUTPUT CRITIQUE & SCORING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Output Critique & Scoring'));
console.log(chalk.gray('─'.repeat(60)));

const critic = new OutputCritic();

const codeToScore = `
/**
 * Calculates the factorial of a number.
 * Uses recursion with memoization for efficiency.
 */
const factorial = (function() {
  const cache: Record<number, number> = {};

  return function factorial(n: number): number {
    if (n < 0) {
      throw new Error('Factorial not defined for negative numbers');
    }
    if (n <= 1) return 1;
    if (cache[n]) return cache[n];

    cache[n] = n * factorial(n - 1);
    return cache[n];
  };
})();
`;

console.log(chalk.green('\nScoring a code sample:'));
console.log(chalk.gray(codeToScore.trim().slice(0, 200) + '...'));

const score = await critic.score(codeToScore);

console.log(chalk.white('\n  Quality Scores:'));
console.log(chalk.gray(`  Overall: ${score.overall}/100`));
console.log(chalk.gray('\n  By Dimension:'));
Object.entries(score.dimensions).forEach(([dim, value]) => {
  const bar = '█'.repeat(Math.floor(value / 10)) + '░'.repeat(10 - Math.floor(value / 10));
  const color = value >= 80 ? chalk.green : value >= 60 ? chalk.yellow : chalk.red;
  console.log(color(`    ${dim.padEnd(15)} ${bar} ${value}`));
});

// Full critique
const criteria = {
  checkCompleteness: true,
  checkCorrectness: true,
  checkCodeQuality: true,
  checkClarity: true,
  checkEdgeCases: true,
  customCriteria: [],
  confidenceThreshold: 0.7,
};

const critique = await critic.critique(codeToScore, criteria);

console.log(chalk.white(`\n  Assessment: ${critique.assessment.toUpperCase()}`));
if (critique.positives.length > 0) {
  console.log(chalk.green('  Positives:'));
  critique.positives.forEach((p) => console.log(chalk.green(`    ✓ ${p}`)));
}

// =============================================================================
// PART 5: REFLECTION LOOP
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Reflection Loop'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nReflection loop concept:'));
console.log(chalk.gray(`
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
`));

const loop = new ReflectionLoop({
  maxAttempts: 3,
  satisfactionThreshold: 0.75,
  includePreviousAttempts: true,
});

// Subscribe to events
loop.on((event) => {
  switch (event.type) {
    case 'attempt.started':
      console.log(chalk.blue(`  ▶ Attempt ${event.attempt} started`));
      break;
    case 'reflection.completed':
      const confidence = (event.result.confidence * 100).toFixed(0);
      const status = event.result.satisfied ? chalk.green('✓ satisfied') : chalk.yellow('needs improvement');
      console.log(chalk.gray(`    Reflection: ${confidence}% confidence - ${status}`));
      break;
    case 'loop.completed':
      console.log(chalk.green(`  ✓ Loop completed after ${event.result.attempts} attempts`));
      break;
  }
});

// Simulate a task that improves with feedback
let attemptCounter = 0;

const improvingTask = async (context: TaskContext): Promise<string> => {
  attemptCounter++;

  // Simulate improvement based on attempt number
  switch (attemptCounter) {
    case 1:
      // First attempt: incomplete
      return `
function sort(arr) {
  // TODO: implement sorting
  return arr;
}
      `.trim();

    case 2:
      // Second attempt: basic implementation
      return `
function sort(arr) {
  return arr.slice().sort((a, b) => a - b);
}
      `.trim();

    default:
      // Third attempt: complete implementation
      return `
/**
 * Sorts an array of numbers in ascending order.
 * Creates a new array (doesn't mutate the original).
 */
function sort(arr: number[]): number[] {
  if (!Array.isArray(arr)) {
    throw new Error('Input must be an array');
  }
  if (arr.length === 0) return [];
  return [...arr].sort((a, b) => a - b);
}
      `.trim();
  }
};

console.log(chalk.green('\nExecuting reflection loop:'));
console.log(chalk.gray('  Goal: "Write a function to sort numbers"'));

attemptCounter = 0; // Reset counter
const result = await loop.executeSimple(
  () => improvingTask({ attempt: attemptCounter, previousAttempts: [], goal: 'test' }),
  'Write a function to sort numbers'
);

console.log(chalk.white('\n  Final result:'));
console.log(chalk.gray(`    Attempts: ${result.attempts}`));
console.log(chalk.gray(`    Satisfied: ${result.satisfied ? 'Yes' : 'No'}`));
console.log(chalk.gray(`    Duration: ${result.durationMs.toFixed(0)}ms`));

// Trajectory analysis
const analysis = loop.analyzeTrajectory(result);
console.log(chalk.white('\n  Trajectory Analysis:'));
console.log(chalk.gray(`    Improved: ${analysis.improved ? 'Yes' : 'No'}`));
console.log(chalk.gray(`    Convergence: ${analysis.convergence}`));
if (analysis.bottleneck) {
  console.log(chalk.gray(`    Bottleneck: ${analysis.bottleneck}`));
}

// =============================================================================
// PART 6: STRICT VS LENIENT REFLECTION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Strict vs Lenient Reflection'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nDifferent reflection strictness levels:'));
console.log(chalk.gray(`
  Strict:  High threshold, more criteria, more attempts
  Lenient: Low threshold, fewer criteria, fewer attempts

  Use strict for:
  • Production code
  • Security-sensitive output
  • User-facing content

  Use lenient for:
  • Quick prototypes
  • Internal tools
  • Time-sensitive tasks
`));

const strictLoop = createStrictLoop();
const lenientLoop = createLenientLoop();

const sampleCode = `
function greet(name) {
  return "Hello, " + name;
}
`;

const strictReflector = new SimpleReflector({
  checkCompleteness: true,
  checkCorrectness: true,
  checkCodeQuality: true,
  checkClarity: true,
  checkEdgeCases: true,
  confidenceThreshold: 0.85,
});

const lenientReflector = new SimpleReflector({
  checkCompleteness: true,
  checkCorrectness: true,
  checkCodeQuality: false,
  checkClarity: false,
  checkEdgeCases: false,
  confidenceThreshold: 0.5,
});

const strictResult = await strictReflector.reflect('Write a greeting function', sampleCode);
const lenientResult = await lenientReflector.reflect('Write a greeting function', sampleCode);

console.log(chalk.green('\nSame code, different standards:'));
console.log(chalk.gray(`  Code: ${sampleCode.trim().slice(0, 50)}...`));
console.log();
console.log(chalk.gray('  Strict reflection:'));
console.log(chalk.gray(`    Satisfied: ${strictResult.satisfied ? chalk.green('Yes') : chalk.red('No')}`));
console.log(chalk.gray(`    Issues: ${strictResult.issues.length}`));
console.log(chalk.gray(`    Confidence: ${(strictResult.confidence * 100).toFixed(0)}%`));
console.log();
console.log(chalk.gray('  Lenient reflection:'));
console.log(chalk.gray(`    Satisfied: ${lenientResult.satisfied ? chalk.green('Yes') : chalk.red('No')}`));
console.log(chalk.gray(`    Issues: ${lenientResult.issues.length}`));
console.log(chalk.gray(`    Confidence: ${(lenientResult.confidence * 100).toFixed(0)}%`));

// =============================================================================
// PART 7: WHEN NOT TO REFLECT
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: When NOT to Reflect'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nReflection adds overhead. Skip it when:'));
console.log(chalk.gray(`
  ✗ Task is simple and well-defined
    Example: "What is 2 + 2?"

  ✗ Speed matters more than quality
    Example: Interactive chat responses

  ✗ Output is easily verifiable
    Example: API calls with schema validation

  ✗ Cost is a concern
    Example: High-volume, low-stakes tasks

  Use reflection when:

  ✓ Output quality is critical
    Example: Code generation for production

  ✓ Mistakes are expensive
    Example: Financial calculations

  ✓ User trust depends on accuracy
    Example: Medical/legal information

  ✓ Task is complex or ambiguous
    Example: Multi-step reasoning
`));

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. Reflection helps catch and fix mistakes'));
console.log(chalk.gray('  2. Quality criteria should match the task'));
console.log(chalk.gray('  3. Reflection loops enable iterative improvement'));
console.log(chalk.gray('  4. Trajectory analysis shows improvement patterns'));
console.log(chalk.gray('  5. Choose strictness based on context'));
console.log();
console.log(chalk.white('Key components:'));
console.log(chalk.gray('  • Reflector - Evaluates output against goals'));
console.log(chalk.gray('  • Critic - Scores output across dimensions'));
console.log(chalk.gray('  • ReflectionLoop - Orchestrates improvement cycles'));
console.log(chalk.gray('  • TrajectoryAnalysis - Tracks improvement progress'));
console.log();
console.log(chalk.bold.green('Next: Lesson 17 - Multi-Agent Coordination'));
console.log(chalk.gray('Make agents work together as a team!'));
console.log();
