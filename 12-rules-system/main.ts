/**
 * Lesson 12: Rules & Instructions System
 *
 * This lesson demonstrates how to build dynamic system prompts
 * from multiple configuration sources. This pattern is used by
 * tools like Claude Code to support CLAUDE.md files.
 *
 * Key concepts:
 * 1. Hierarchical configuration (global < user < project < directory)
 * 2. Rule discovery and loading
 * 3. Priority-based merging
 * 4. Dynamic prompt construction
 *
 * Run: npm run lesson:12
 */

import chalk from 'chalk';
import * as fs from 'fs/promises';
import * as path from 'path';
import { RuleLoader } from './rule-loader.js';
import { RuleMerger } from './rule-merger.js';
import { PromptBuilder, buildFromSections } from './prompt-builder.js';
import type {
  InstructionSource,
  InstructionFile,
  Rule,
  RuleType,
  Scope,
  PromptSections,
} from './types.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║       Lesson 12: Rules & Instructions System                ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: RULE LOADER BASICS
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Rule Loader - Discovery & Loading'));
console.log(chalk.gray('─'.repeat(60)));

const loader = new RuleLoader({
  baseDir: process.cwd(),
  filePatterns: ['CLAUDE.md', 'AGENTS.md', '.claude/instructions.md'],
});

console.log(chalk.green('\nDiscovering instruction files...'));
const discoveredSources = await loader.discover();

if (discoveredSources.length > 0) {
  console.log(chalk.white(`\nFound ${discoveredSources.length} instruction source(s):`));
  for (const source of discoveredSources) {
    console.log(chalk.gray(`  - ${source.location}`));
    console.log(chalk.gray(`    Scope: ${source.scope}, Priority: ${source.priority}`));
  }
} else {
  console.log(chalk.gray('\nNo instruction files found in the current directory.'));
  console.log(chalk.gray('This is normal - we\'ll use demo content instead.'));
}

// =============================================================================
// PART 2: PARSING INSTRUCTION FILES
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Parsing Instruction Files'));
console.log(chalk.gray('─'.repeat(60)));

// Demo instruction file content
const demoGlobalConfig = `---
scope: global
priority: 500
tags: [global, coding]
---

# Global Coding Standards

Always follow these standards across all projects.

## Constraints

- Never commit sensitive data to version control
- Never expose API keys in client-side code
- Always validate user input

## Preferences

- Use TypeScript for new projects
- Prefer functional programming patterns
- Write tests for critical paths
`;

const demoProjectConfig = `---
scope: project
priority: 300
---

# Project: First Principles Agent

This is an educational project about building AI agents.

## Context

This project teaches developers how to build AI coding agents
from first principles, using TypeScript and modern patterns.

## Instructions

- Explain concepts clearly with comments
- Use simple examples before complex ones
- Include error handling in all examples

## Format

- Use TypeScript for all code
- Include JSDoc comments
- Follow the existing lesson structure
`;

const demoLocalConfig = `---
scope: directory
priority: 200
---

# Local Rules for Lesson 12

## Tool Configuration

- When editing files, prefer using the Edit tool over Write
- Always read files before modifying them

## Constraints

- Do not modify files outside the 12-rules-system directory
`;

console.log(chalk.green('\nParsing demo instruction files...'));

const globalFile = loader.parseFile(demoGlobalConfig, '~/.claude/CLAUDE.md');
const projectFile = loader.parseFile(demoProjectConfig, '/project/CLAUDE.md');
const localFile = loader.parseFile(demoLocalConfig, '/project/12-rules-system/CLAUDE.local.md');

console.log(chalk.white('\nParsed file structure:'));
console.log(chalk.gray('  Global config:'));
console.log(chalk.gray(`    Frontmatter: scope=${globalFile.frontmatter?.scope}, priority=${globalFile.frontmatter?.priority}`));
console.log(chalk.gray(`    Sections: ${globalFile.sections.length}`));
for (const section of globalFile.sections) {
  console.log(chalk.gray(`      - ${section.heading ?? '(no heading)'} [${section.ruleType}]`));
}

console.log(chalk.gray('  Project config:'));
console.log(chalk.gray(`    Sections: ${projectFile.sections.length}`));
for (const section of projectFile.sections) {
  console.log(chalk.gray(`      - ${section.heading ?? '(no heading)'} [${section.ruleType}]`));
}

console.log(chalk.gray('  Local config:'));
console.log(chalk.gray(`    Sections: ${localFile.sections.length}`));
for (const section of localFile.sections) {
  console.log(chalk.gray(`      - ${section.heading ?? '(no heading)'} [${section.ruleType}]`));
}

// =============================================================================
// PART 3: MERGING RULES
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Merging Rules from Multiple Sources'));
console.log(chalk.gray('─'.repeat(60)));

const merger = new RuleMerger({
  strategy: 'combine',
  deduplicate: true,
  includeSourceComments: false,
});

// Create sources for our demo files
const sources: InstructionSource[] = [
  {
    id: 'global',
    type: 'inline',
    location: demoGlobalConfig,
    scope: 'global',
    priority: 500,
    enabled: true,
  },
  {
    id: 'project',
    type: 'inline',
    location: demoProjectConfig,
    scope: 'project',
    priority: 300,
    enabled: true,
  },
  {
    id: 'local',
    type: 'inline',
    location: demoLocalConfig,
    scope: 'directory',
    priority: 200,
    enabled: true,
  },
];

console.log(chalk.green('\nMerging rules...'));

const ruleSet = merger.merge([
  { source: sources[0], file: globalFile },
  { source: sources[1], file: projectFile },
  { source: sources[2], file: localFile },
]);

console.log(chalk.white('\nMerge statistics:'));
console.log(chalk.gray(`  Sources processed: ${ruleSet.metadata.sourcesProcessed}`));
console.log(chalk.gray(`  Total rules: ${ruleSet.metadata.totalRules}`));
console.log(chalk.gray(`  After merge: ${ruleSet.metadata.mergedRules}`));
console.log(chalk.gray(`  Build time: ${ruleSet.metadata.buildDurationMs.toFixed(2)}ms`));

console.log(chalk.white('\nRules by type:'));
const rulesByType = new Map<RuleType, Rule[]>();
for (const rule of ruleSet.rules) {
  const existing = rulesByType.get(rule.type) ?? [];
  existing.push(rule);
  rulesByType.set(rule.type, existing);
}

for (const [type, rules] of rulesByType) {
  console.log(chalk.gray(`  ${type}: ${rules.length} rule(s)`));
}

// =============================================================================
// PART 4: BUILDING THE SYSTEM PROMPT
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Building the System Prompt'));
console.log(chalk.gray('─'.repeat(60)));

const builder = new PromptBuilder({
  includeSectionHeaders: true,
  sectionSeparator: '\n\n---\n\n',
});

const systemPrompt = builder.build(ruleSet);

console.log(chalk.green('\nGenerated system prompt:'));
console.log(chalk.gray('─'.repeat(60)));

// Print with line numbers and limited length
const lines = systemPrompt.split('\n');
for (let i = 0; i < Math.min(lines.length, 30); i++) {
  console.log(chalk.gray(`${String(i + 1).padStart(3)} │ `) + lines[i]);
}

if (lines.length > 30) {
  console.log(chalk.gray(`    │ ... (${lines.length - 30} more lines)`));
}

console.log(chalk.gray('─'.repeat(60)));
console.log(chalk.gray(`Total length: ${systemPrompt.length} characters`));

// =============================================================================
// PART 5: TEMPLATE EXPANSION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Template Variable Expansion'));
console.log(chalk.gray('─'.repeat(60)));

const templateContent = `
You are helping with the {{projectName}} project.

Current date: {{date}}
Working directory: {{cwd}}

User preferences:
- Theme: {{theme}}
- Language: {{language}}
`;

const variables = {
  projectName: 'First Principles Agent',
  date: new Date().toISOString().split('T')[0],
  cwd: process.cwd(),
  theme: 'dark',
  language: 'TypeScript',
};

console.log(chalk.green('\nTemplate before expansion:'));
console.log(chalk.gray(templateContent.trim()));

const expanded = builder.expandTemplates(templateContent, variables);

console.log(chalk.green('\nTemplate after expansion:'));
console.log(chalk.white(expanded.trim()));

// =============================================================================
// PART 6: CUSTOM SECTIONS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Building from Custom Sections'));
console.log(chalk.gray('─'.repeat(60)));

const customSections: PromptSections = {
  persona: 'You are a helpful coding assistant specializing in TypeScript.',
  context: 'The user is working on an educational project about AI agents.',
  instructions: `
- Read files before editing
- Explain your reasoning
- Ask clarifying questions when needed
`,
  constraints: `
- Never modify files without user approval
- Never execute dangerous commands
`,
  preferences: `
- Prefer functional programming
- Use descriptive variable names
`,
};

const customPrompt = buildFromSections(customSections);

console.log(chalk.green('\nPrompt from custom sections:'));
console.log(chalk.gray('─'.repeat(60)));

const customLines = customPrompt.split('\n');
for (let i = 0; i < Math.min(customLines.length, 20); i++) {
  console.log(chalk.gray(`${String(i + 1).padStart(3)} │ `) + customLines[i]);
}

if (customLines.length > 20) {
  console.log(chalk.gray(`    │ ... (${customLines.length - 20} more lines)`));
}

// =============================================================================
// PART 7: PRIORITY DEMONSTRATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Priority Override Demonstration'));
console.log(chalk.gray('─'.repeat(60)));

// Create conflicting rules at different priority levels
const conflictingRules: Rule[] = [
  {
    sourceId: 'global',
    content: 'Use 2-space indentation',
    type: 'preference',
    priority: 500,
    scope: 'global',
  },
  {
    sourceId: 'project',
    content: 'Use 4-space indentation for this project',
    type: 'preference',
    priority: 300,
    scope: 'project',
  },
  {
    sourceId: 'local',
    content: 'Use tabs for this directory',
    type: 'preference',
    priority: 200,
    scope: 'directory',
  },
];

console.log(chalk.green('\nConflicting rules (indentation preference):'));
for (const rule of conflictingRules) {
  console.log(chalk.gray(`  [${rule.scope}] priority=${rule.priority}: "${rule.content}"`));
}

const priorityMerger = new RuleMerger({
  strategy: 'priority',
  typeStrategies: {
    preference: 'priority', // Keep only highest priority
  },
});

const priorityResult = priorityMerger.merge(
  conflictingRules.map((rule) => ({
    source: {
      id: rule.sourceId,
      type: 'inline' as const,
      location: rule.content,
      scope: rule.scope,
      priority: rule.priority,
      enabled: true,
    },
    file: {
      path: rule.sourceId,
      sections: [{ content: rule.content, ruleType: rule.type }],
      rawContent: rule.content,
    },
  }))
);

console.log(chalk.green('\nAfter priority-based merge:'));
for (const rule of priorityResult.rules) {
  console.log(chalk.white(`  Winner [${rule.scope}]: "${rule.content}"`));
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
console.log(chalk.gray('  1. RuleLoader discovers and loads instruction files'));
console.log(chalk.gray('  2. Files can have YAML frontmatter for configuration'));
console.log(chalk.gray('  3. RuleMerger combines rules with priority handling'));
console.log(chalk.gray('  4. PromptBuilder constructs structured system prompts'));
console.log(chalk.gray('  5. Templates allow dynamic content injection'));
console.log();
console.log(chalk.white('Scope hierarchy (more specific overrides general):'));
console.log(chalk.gray('  global → user → project → directory → session'));
console.log();
console.log(chalk.white('Common file patterns:'));
console.log(chalk.gray('  - CLAUDE.md: Project-level instructions'));
console.log(chalk.gray('  - CLAUDE.local.md: Local overrides (gitignored)'));
console.log(chalk.gray('  - ~/.claude/CLAUDE.md: Global user preferences'));
console.log();
console.log(chalk.bold.green('Next: Lesson 13 - Client/Server Separation'));
console.log(chalk.gray('Build a server API for your agent!'));
console.log();
