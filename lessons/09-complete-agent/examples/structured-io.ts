/**
 * Structured I/O Demo: Input Patterns That Reduce LLM Mistakes
 *
 * Run: npx tsx 08-complete-agent/examples/structured-io.ts
 *
 * This example demonstrates:
 * 1. Tool result formatting
 * 2. State tracking summaries
 * 3. Instruction patterns
 * 4. Input validation helpers
 * 5. Response parsing
 */

import {
  formatToolResult,
  formatToolResults,
  buildStateSummary,
  INSTRUCTION_PATTERNS,
  buildRobustSystemPrompt,
  sanitizePath,
  extractFilePaths,
  detectDangerousIntent,
  isCompletionResponse,
  isStuckResponse,
  extractSummary,
} from '../input-patterns.js';

// =============================================================================
// DEMO: Tool Result Formatting
// =============================================================================

console.log('╔════════════════════════════════════════════════════════════════╗');
console.log('║  Structured I/O: Input Patterns for Reliable Agents            ║');
console.log('╚════════════════════════════════════════════════════════════════╝\n');

console.log('1. Tool Result Formatting\n');
console.log('─'.repeat(60));
console.log('Why: Clear boundaries prevent LLM from confusing tool output');
console.log('     with conversation text.\n');

// Successful result
const successResult = {
  success: true,
  output: `{
  "name": "my-project",
  "version": "1.0.0",
  "dependencies": {
    "typescript": "^5.0.0"
  }
}`,
};

console.log('Formatted SUCCESS result:');
console.log(formatToolResult('read_file', successResult));

// Failed result
const failedResult = {
  success: false,
  output: 'File not found: /nonexistent/path.txt',
};

console.log('\nFormatted FAILED result:');
console.log(formatToolResult('read_file', failedResult));

// Multiple results
console.log('\nMultiple results:');
console.log(formatToolResults([
  { name: 'glob', result: { success: true, output: 'src/index.ts\nsrc/utils.ts' } },
  { name: 'read_file', result: { success: true, output: '// index.ts contents...' } },
]));

// =============================================================================
// DEMO: State Tracking
// =============================================================================

console.log('\n\n2. State Tracking Summaries\n');
console.log('─'.repeat(60));
console.log('Why: Helps LLM remember what was done in long conversations.\n');

const stateSummary = buildStateSummary({
  currentTask: 'Refactor authentication module',
  filesRead: ['src/auth.ts', 'src/types.ts', 'package.json'],
  filesModified: ['src/auth.ts'],
  commandsRun: ['npm test'],
  completedSteps: ['Read existing code', 'Identified issues'],
  pendingSteps: ['Apply fixes', 'Run tests', 'Update docs'],
});

console.log('State summary for LLM:');
console.log(stateSummary);

// =============================================================================
// DEMO: Instruction Patterns
// =============================================================================

console.log('\n\n3. Instruction Patterns\n');
console.log('─'.repeat(60));
console.log('Why: Specific instructions prevent common LLM mistakes.\n');

console.log('WAIT_FOR_RESULT pattern:');
console.log('─'.repeat(40));
console.log(INSTRUCTION_PATTERNS.WAIT_FOR_RESULT);

console.log('\n\nONE_STEP_AT_A_TIME pattern:');
console.log('─'.repeat(40));
console.log(INSTRUCTION_PATTERNS.ONE_STEP_AT_A_TIME);

console.log('\n\nEDIT_GUIDANCE pattern:');
console.log('─'.repeat(40));
console.log(INSTRUCTION_PATTERNS.EDIT_GUIDANCE);

// =============================================================================
// DEMO: Robust System Prompt
// =============================================================================

console.log('\n\n4. Building a Robust System Prompt\n');
console.log('─'.repeat(60));

const toolDescriptions = `
- read_file: Read the contents of a file
- write_file: Write content to a file
- edit_file: Make surgical edits with find/replace
- bash: Run shell commands
`.trim();

const systemPrompt = buildRobustSystemPrompt(
  toolDescriptions,
  'Focus on TypeScript best practices.'
);

console.log('Generated system prompt:');
console.log('─'.repeat(40));
console.log(systemPrompt.slice(0, 500) + '...\n');
console.log(`(Total length: ${systemPrompt.length} chars)`);

// =============================================================================
// DEMO: Input Validation
// =============================================================================

console.log('\n\n5. Input Validation Helpers\n');
console.log('─'.repeat(60));

console.log('Path sanitization:');
const testPaths = [
  '"src/index.ts"',
  "'config/settings.json'",
  'path\\\\to\\\\file.txt',
  '//double//slashes//',
];

for (const p of testPaths) {
  console.log(`  ${p.padEnd(25)} → ${sanitizePath(p)}`);
}

console.log('\n\nExtracting file paths from text:');
const userInput = `
  Please read the \`package.json\` file and then check
  "src/components/Button.tsx" for any issues. Also look at
  ./config/webpack.config.js and ../shared/types.ts
`;

const extractedPaths = extractFilePaths(userInput);
console.log('Input text:', userInput.trim().slice(0, 100) + '...');
console.log('Extracted paths:', extractedPaths);

console.log('\n\nDangerous intent detection:');
const dangerousInputs = [
  'Delete all files in the temp directory',
  'Update the production database',
  'Store the API key in config',
  'Recursively delete node_modules',
  'Just read the README file',
];

for (const input of dangerousInputs) {
  const warnings = detectDangerousIntent(input);
  const status = warnings.length > 0 ? `⚠️  ${warnings[0]}` : '✓ Safe';
  console.log(`  "${input.slice(0, 40)}..." → ${status}`);
}

// =============================================================================
// DEMO: Response Parsing
// =============================================================================

console.log('\n\n6. Response Parsing Helpers\n');
console.log('─'.repeat(60));

const responses = [
  { text: "I've finished refactoring the code. The task is now complete.", expected: 'completion' },
  { text: "I'm not sure what format you want. Could you clarify?", expected: 'stuck' },
  { text: "Let me read the file to understand the current state.", expected: 'in-progress' },
  { text: "All tasks are done. Summary: Updated 3 files, added tests.", expected: 'completion' },
];

console.log('Completion detection:');
for (const { text, expected } of responses) {
  const isComplete = isCompletionResponse(text);
  const isStuck = isStuckResponse(text);
  const detected = isComplete ? 'completion' : isStuck ? 'stuck' : 'in-progress';
  const match = detected === expected ? '✓' : '✗';
  console.log(`  ${match} "${text.slice(0, 50)}..." → ${detected}`);
}

console.log('\n\nSummary extraction:');
const longResponse = `
I've analyzed the codebase and made several improvements.

Summary: Refactored the authentication module to use async/await,
added input validation, and updated the tests.

The changes include:
1. Converted callbacks to promises
2. Added Zod schemas for validation
3. Updated 15 test cases

All tests are now passing.
`;

console.log('Long response:', longResponse.trim().slice(0, 80) + '...');
console.log('Extracted summary:', extractSummary(longResponse));

// =============================================================================
// DEMO: Before/After Comparison
// =============================================================================

console.log('\n\n7. Before/After: Input Structuring Impact\n');
console.log('─'.repeat(60));

console.log('BEFORE (prone to mistakes):');
console.log('─'.repeat(40));
console.log(`
System: You are a coding assistant.
User: Read config.json and update the port.
`);
console.log('Problems:');
console.log('  - LLM might guess config contents');
console.log('  - No guidance on edit format');
console.log('  - No clear completion signal');

console.log('\n\nAFTER (structured for reliability):');
console.log('─'.repeat(40));
console.log(`
System: You are a coding assistant with tools: read_file, edit_file.
        ${INSTRUCTION_PATTERNS.WAIT_FOR_RESULT.split('\n')[0]}
        ${INSTRUCTION_PATTERNS.EDIT_GUIDANCE.split('\n')[0]}
        ${INSTRUCTION_PATTERNS.COMPLETION_SIGNAL.split('\n')[0]}

User: Read config.json and update the port to 8080.

[After read_file returns]
${formatToolResult('read_file', { success: true, output: '{"port": 3000}' })}
`);
console.log('Improvements:');
console.log('  - Clear tool list and rules');
console.log('  - Explicit "wait for result" instruction');
console.log('  - Formatted tool output with boundaries');

// =============================================================================
// SUMMARY
// =============================================================================

console.log('\n\n═══════════════════════════════════════════════════════════════════');
console.log('KEY TAKEAWAYS');
console.log('═══════════════════════════════════════════════════════════════════');
console.log(`
1. FORMAT tool results with clear boundaries (═══ TOOL: name ═══)
2. TRACK state to prevent agent from "forgetting" what it did
3. USE instruction patterns that address specific failure modes:
   - WAIT_FOR_RESULT: Prevents hallucinated tool outputs
   - ONE_STEP_AT_A_TIME: Prevents over-planning
   - EDIT_GUIDANCE: Ensures precise file modifications
4. VALIDATE inputs before passing to agent
5. PARSE responses to detect completion/stuck states
6. DETECT dangerous intent early for safety
`);
