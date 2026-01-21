/**
 * Lesson 18: ReAct Pattern (Reasoning + Acting)
 *
 * This lesson demonstrates the ReAct pattern where the agent
 * explicitly verbalizes its reasoning before each action.
 * This creates a traceable chain of thought that improves
 * accuracy and debuggability.
 *
 * Key concepts:
 * 1. Thought → Action → Observation loop
 * 2. Explicit reasoning improves tool use
 * 3. Traceable decision chains
 * 4. Error recovery with reasoning
 *
 * Run: npm run lesson:18
 */

import chalk from 'chalk';
import {
  parseReActOutput,
  extractAllThoughts,
  extractAllActions,
  hasFinalAnswer,
  extractFinalAnswer,
  validateAction,
  attemptRecovery,
} from './thought-parser.js';
import {
  formatObservation,
  formatFileContent,
  formatCommandOutput,
  formatSearchResults,
  formatError,
} from './observation-formatter.js';
import type {
  ReActStep,
  ReActTrace,
  ReActAction,
  ReActToolRegistry,
  ParsedReActOutput,
} from './types.js';
import type { ToolDefinition, ToolResult } from '../03-tool-system/types.js';
import { z } from 'zod';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 18: ReAct Pattern                             ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: UNDERSTANDING REACT FORMAT
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Understanding ReAct Format'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nReAct Format Example:'));
console.log(chalk.gray(`
  Thought: I need to find TypeScript files in the project.
           Let me search the src directory.

  Action: search({"pattern": "*.ts", "directory": "src"})

  Observation: Found 15 files:
               - src/index.ts
               - src/utils/helper.ts
               ...

  Thought: Good, I found the files. Now I need to count them.
           The search already showed 15 files.

  Final Answer: There are 15 TypeScript files in the src directory.
`));

console.log(chalk.white('\nKey components:'));
console.log(chalk.gray('  - Thought: Agent\'s reasoning process'));
console.log(chalk.gray('  - Action: Tool call with arguments'));
console.log(chalk.gray('  - Observation: Tool result'));
console.log(chalk.gray('  - Final Answer: Conclusion when done'));

// =============================================================================
// PART 2: PARSING REACT OUTPUT
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Parsing ReAct Output'));
console.log(chalk.gray('─'.repeat(60)));

// Example outputs to parse
const examples = [
  {
    name: 'Standard format',
    output: `Thought: I need to read the config file to understand the project structure.

Action: read_file({"path": "package.json"})`,
  },
  {
    name: 'Final answer',
    output: `Thought: Based on the information gathered, I can now answer.

Final Answer: The project uses TypeScript 5.0 with ESNext modules.`,
  },
  {
    name: 'Alternative action format',
    output: `Thought: Let me search for the main entry point.

Action: search {"query": "main", "type": "function"}`,
  },
];

for (const example of examples) {
  console.log(chalk.green(`\n${example.name}:`));
  console.log(chalk.gray(example.output.split('\n').map(l => '  ' + l).join('\n')));

  const parsed = parseReActOutput(example.output);

  console.log(chalk.blue('\n  Parsed result:'));
  console.log(chalk.gray(`    Success: ${parsed.success}`));
  console.log(chalk.gray(`    Is Final Answer: ${parsed.isFinalAnswer}`));

  if (parsed.thought) {
    console.log(chalk.gray(`    Thought: "${parsed.thought.slice(0, 50)}..."`));
  }

  if (parsed.action) {
    console.log(chalk.gray(`    Action: ${parsed.action.tool}(${JSON.stringify(parsed.action.args)})`));
  }

  if (parsed.finalAnswer) {
    console.log(chalk.gray(`    Final Answer: "${parsed.finalAnswer.slice(0, 50)}..."`));
  }

  if (parsed.errors.length > 0) {
    console.log(chalk.red(`    Errors: ${parsed.errors.join(', ')}`));
  }
}

// =============================================================================
// PART 3: OBSERVATION FORMATTING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Formatting Observations'));
console.log(chalk.gray('─'.repeat(60)));

// File content
const fileContent = `{
  "name": "first-principles-agent",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "lesson:1": "tsx 01-core-loop/main.ts",
    "lesson:2": "tsx 02-provider-abstraction/main.ts"
  }
}`;

console.log(chalk.green('\nFile content observation:'));
const fileObs = formatFileContent('package.json', fileContent, { maxLength: 200 });
console.log(chalk.gray(fileObs.content));
console.log(chalk.gray(`  (truncated: ${fileObs.truncated}, original: ${fileObs.originalLength} chars)`));

// Command output
console.log(chalk.green('\nCommand output observation:'));
const cmdObs = formatCommandOutput(
  'ls -la src/',
  'total 24\ndrwxr-xr-x  5 user  staff  160 Jan 15 10:00 .\ndrwxr-xr-x  8 user  staff  256 Jan 15 09:00 ..\n-rw-r--r--  1 user  staff  1234 Jan 15 10:00 index.ts',
  '',
  0,
  { maxLength: 200 }
);
console.log(chalk.gray(cmdObs.content));

// Search results
console.log(chalk.green('\nSearch results observation:'));
const searchObs = formatSearchResults(
  'function main',
  [
    { file: 'src/index.ts', line: 15, content: 'export function main() {' },
    { file: 'src/cli.ts', line: 42, content: 'async function main() {' },
  ],
  { maxLength: 300 }
);
console.log(chalk.gray(searchObs.content));

// Error
console.log(chalk.green('\nError observation:'));
const errorObs = formatError(
  new Error('File not found: config.yaml'),
  'Attempting to read configuration',
  { maxLength: 200 }
);
console.log(chalk.gray(errorObs.content));

// =============================================================================
// PART 4: SIMULATED REACT EXECUTION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Simulated ReAct Execution'));
console.log(chalk.gray('─'.repeat(60)));

// Simulated ReAct trace
const simulatedTrace: ReActTrace = {
  goal: 'Find all TODO comments in the codebase',
  steps: [
    {
      stepNumber: 1,
      thought: 'I need to search for TODO comments. I\'ll use grep to find them across all TypeScript files.',
      action: { tool: 'search', args: { pattern: 'TODO', glob: '**/*.ts' } },
      observation: 'Found 3 matches:\n- src/index.ts:15: // TODO: Add error handling\n- src/utils.ts:42: // TODO: Optimize this\n- test/test.ts:8: // TODO: Add more tests',
      timestamp: new Date(),
      durationMs: 150,
    },
    {
      stepNumber: 2,
      thought: 'I found 3 TODO comments. Let me organize them by file to give a clear answer.',
      action: { tool: 'noop', args: {} },
      observation: 'No action needed - organizing results.',
      timestamp: new Date(),
      durationMs: 10,
    },
  ],
  finalAnswer: 'Found 3 TODO comments:\n1. src/index.ts:15 - Add error handling\n2. src/utils.ts:42 - Optimize this\n3. test/test.ts:8 - Add more tests',
  success: true,
  totalDurationMs: 160,
  toolCallCount: 2,
  errors: [],
};

console.log(chalk.green(`\nGoal: "${simulatedTrace.goal}"`));
console.log();

for (const step of simulatedTrace.steps) {
  console.log(chalk.blue(`Step ${step.stepNumber}:`));
  console.log(chalk.white(`  Thought: ${step.thought.slice(0, 80)}...`));
  console.log(chalk.yellow(`  Action: ${step.action.tool}(${JSON.stringify(step.action.args)})`));
  console.log(chalk.gray(`  Observation: ${step.observation.split('\n')[0]}...`));
  console.log(chalk.gray(`  Duration: ${step.durationMs}ms`));
  console.log();
}

console.log(chalk.green('Final Answer:'));
console.log(chalk.white(simulatedTrace.finalAnswer.split('\n').map(l => '  ' + l).join('\n')));

// =============================================================================
// PART 5: REACT VS STANDARD COMPARISON
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: ReAct vs Standard Agent Comparison'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nStandard Agent:'));
console.log(chalk.gray(`
  1. Receive goal
  2. Call tools directly based on goal
  3. Return result

  Pros:
    - Faster (fewer tokens)
    - Simpler implementation

  Cons:
    - No visible reasoning
    - Harder to debug
    - May make incorrect assumptions
`));

console.log(chalk.white('ReAct Agent:'));
console.log(chalk.gray(`
  1. Receive goal
  2. Think about what to do
  3. Take action
  4. Observe result
  5. Think about result
  6. Repeat until done

  Pros:
    - Explicit reasoning chain
    - Easier to debug
    - Better at complex tasks
    - Can catch and correct errors

  Cons:
    - More tokens used
    - Slower execution
    - Requires structured output
`));

console.log(chalk.white('\nWhen to use ReAct:'));
console.log(chalk.green('  ✓ Complex multi-step tasks'));
console.log(chalk.green('  ✓ Tasks requiring reasoning'));
console.log(chalk.green('  ✓ When debugging is important'));
console.log(chalk.green('  ✓ When accuracy > speed'));
console.log(chalk.red('  ✗ Simple single-tool tasks'));
console.log(chalk.red('  ✗ When latency is critical'));
console.log(chalk.red('  ✗ High-volume repetitive tasks'));

// =============================================================================
// PART 6: PROMPT TEMPLATE
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: ReAct Prompt Template'));
console.log(chalk.gray('─'.repeat(60)));

const promptTemplate = `
You solve problems step by step, showing your reasoning.

## Format

For each step, use this format:

Thought: [Your reasoning about what to do]
Action: tool_name({"arg1": "value1"})

After receiving the observation, continue thinking:

Thought: [Analysis of the result]
Action: [next action if needed]

When you have the answer:

Final Answer: [Your complete answer]

## Available Tools

- search(pattern, glob): Search files for a pattern
- read_file(path): Read a file's contents
- list_files(directory): List files in a directory

## Important Rules

1. Always think before acting
2. Use observations to guide next steps
3. Don't assume - verify with tools
4. Provide Final Answer when confident
`;

console.log(chalk.gray(promptTemplate));

// =============================================================================
// PART 7: ACTION VALIDATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Action Validation'));
console.log(chalk.gray('─'.repeat(60)));

const availableTools = ['search', 'read_file', 'list_files', 'write_file'];

const testActions: ReActAction[] = [
  { tool: 'search', args: { pattern: 'TODO' } },
  { tool: 'unknown_tool', args: {} },
  { tool: 'read_file', args: { path: 'test.ts' } },
];

for (const action of testActions) {
  const validation = validateAction(action, availableTools);
  console.log(chalk.gray(`\nAction: ${action.tool}(${JSON.stringify(action.args)})`));
  console.log(validation.valid
    ? chalk.green('  ✓ Valid')
    : chalk.red(`  ✗ Invalid: ${validation.errors.join(', ')}`)
  );
}

// =============================================================================
// PART 8: ERROR RECOVERY
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 8: Error Recovery'));
console.log(chalk.gray('─'.repeat(60)));

const malformedOutputs = [
  'I\'ll search for the file using search pattern TODO in typescript files',
  'Let me use the read_file tool to check package.json',
];

for (const output of malformedOutputs) {
  console.log(chalk.gray(`\nMalformed: "${output}"`));

  const parsed = parseReActOutput(output);
  if (!parsed.success) {
    console.log(chalk.yellow('  Standard parsing failed, attempting recovery...'));

    const recovered = attemptRecovery(output, availableTools);
    if (recovered) {
      console.log(chalk.green(`  ✓ Recovered: ${recovered.action?.tool}(${JSON.stringify(recovered.action?.args)})`));
    } else {
      console.log(chalk.red('  ✗ Recovery failed'));
    }
  }
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
console.log(chalk.gray('  1. ReAct interleaves reasoning with action'));
console.log(chalk.gray('  2. Explicit thoughts create traceable decision chains'));
console.log(chalk.gray('  3. Observations are formatted tool results'));
console.log(chalk.gray('  4. Final Answer signals completion'));
console.log(chalk.gray('  5. Validation and recovery handle errors'));
console.log();
console.log(chalk.white('ReAct loop:'));
console.log(chalk.gray('  Goal → Thought → Action → Observation → Thought → ... → Final Answer'));
console.log();
console.log(chalk.white('Best for:'));
console.log(chalk.gray('  - Complex reasoning tasks'));
console.log(chalk.gray('  - Multi-step problem solving'));
console.log(chalk.gray('  - Tasks needing transparency'));
console.log();
console.log(chalk.bold.green('Next: Lesson 15 - Planning & Decomposition'));
console.log(chalk.gray('Break complex tasks into manageable steps!'));
console.log();
