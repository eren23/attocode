/**
 * Lesson 14: Memory Systems
 *
 * This lesson demonstrates how agents can remember and retrieve
 * information beyond the immediate conversation context.
 *
 * Key concepts:
 * 1. Episodic memory (interaction history)
 * 2. Semantic memory (facts and knowledge)
 * 3. Retrieval strategies
 * 4. Memory decay and importance
 *
 * Run: npm run lesson:14
 */

import chalk from 'chalk';
import { InMemoryStore, generateMemoryId } from './memory-store.js';
import { EpisodicMemory, createEpisodicMemory } from './episodic-memory.js';
import { SemanticMemory, createSemanticMemory } from './semantic-memory.js';
import {
  MemoryRetriever,
  createRecencyRetriever,
  createRelevanceRetriever,
} from './retriever.js';
import type { MemoryEntry } from './types.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 14: Memory Systems                           ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: WHY MEMORY MATTERS
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Why Memory Matters'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nConversation history alone is not enough:'));
console.log(chalk.gray(`
  ┌────────────────────────────────────────────────────────────┐
  │ Without Memory                  With Memory                │
  │ ─────────────────               ───────────────            │
  │ User: My name is Alice          User: My name is Alice     │
  │ Bot: Nice to meet you!          Bot: Nice to meet you!     │
  │                                 [Stores: name = Alice]     │
  │ ... context window fills ...    ... context window fills...│
  │ ... memory lost ...             [Memory persists]          │
  │                                                            │
  │ User: What's my name?           User: What's my name?      │
  │ Bot: I don't know.              Bot: Your name is Alice!   │
  └────────────────────────────────────────────────────────────┘
`));

console.log(chalk.white('Types of agent memory:'));
console.log(chalk.gray(`
  Episodic   - "What happened" - Interaction sequences
  Semantic   - "What I know"   - Facts and knowledge
  Procedural - "How to do"     - Learned procedures
  Working    - "Right now"     - Current context
`));

// =============================================================================
// PART 2: EPISODIC MEMORY
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Episodic Memory (Interaction History)'));
console.log(chalk.gray('─'.repeat(60)));

const store = new InMemoryStore();
const episodicMemory = createEpisodicMemory(store, 'demo-session');

// Simulate a conversation episode
console.log(chalk.green('\nRecording an episode:'));

episodicMemory.startEpisode();

episodicMemory.recordUserMessage('Can you help me write a Python function?');
console.log(chalk.gray('  User: "Can you help me write a Python function?"'));

episodicMemory.recordAssistantMessage(
  'Of course! What should the function do?',
  []
);
console.log(chalk.gray('  Assistant: "Of course! What should the function do?"'));

episodicMemory.recordUserMessage('It should calculate the factorial of a number');
console.log(chalk.gray('  User: "It should calculate the factorial of a number"'));

episodicMemory.recordAssistantMessage(
  'Here\'s a factorial function:\n```python\ndef factorial(n):\n    if n <= 1: return 1\n    return n * factorial(n-1)\n```',
  [{ tool: 'code_generation', args: { language: 'python' }, success: true }]
);
console.log(chalk.gray('  Assistant: [Generates code with code_generation tool]'));

const episode = await episodicMemory.endEpisode('success');

console.log(chalk.white('\n  Episode summary:'));
console.log(chalk.gray(`    ID: ${episode?.id}`));
console.log(chalk.gray(`    Interactions: ${episode?.interactions.length}`));
console.log(chalk.gray(`    Outcome: ${episode?.outcome}`));
console.log(chalk.gray(`    Summary: ${episode?.summary?.slice(0, 80)}...`));

// Start another episode
episodicMemory.startEpisode();
episodicMemory.recordUserMessage('Thanks! That worked perfectly.');
episodicMemory.recordAssistantMessage('Glad I could help!');
await episodicMemory.endEpisode('success');

// Retrieve episodes
const recentEpisodes = await episodicMemory.getRecentEpisodes(5);
console.log(chalk.green(`\n  Total episodes stored: ${recentEpisodes.length}`));

// =============================================================================
// PART 3: SEMANTIC MEMORY
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Semantic Memory (Facts & Knowledge)'));
console.log(chalk.gray('─'.repeat(60)));

const semanticStore = new InMemoryStore();
const semanticMemory = createSemanticMemory(semanticStore);

// Learn some facts
console.log(chalk.green('\nLearning facts:'));

const facts = [
  { statement: 'Python is a programming language', confidence: 0.95 },
  { statement: 'Python was created by Guido van Rossum', confidence: 0.9 },
  { statement: 'Python supports object-oriented programming', confidence: 0.95 },
  { statement: 'JavaScript is used for web development', confidence: 0.95 },
  { statement: 'React is a JavaScript library', confidence: 0.9 },
  { statement: 'The user prefers Python over JavaScript', confidence: 0.7, source: 'user' },
];

for (const factData of facts) {
  const fact = await semanticMemory.learnFact(factData.statement, {
    confidence: factData.confidence,
    source: factData.source || 'learned',
  });
  console.log(chalk.gray(`  Learned: "${fact.statement.slice(0, 50)}..." (${(fact.confidence * 100).toFixed(0)}% confidence)`));
}

// Query facts
console.log(chalk.green('\nQuerying knowledge:'));

const pythonFacts = await semanticMemory.getFactsAbout('Python');
console.log(chalk.white(`  Facts about Python: ${pythonFacts.length}`));
for (const fact of pythonFacts.slice(0, 3)) {
  console.log(chalk.gray(`    • ${fact.statement}`));
}

// Answer a question
const answer = await semanticMemory.answerQuestion('What is Python?');
console.log(chalk.white('\n  Question: "What is Python?"'));
if (answer.answer) {
  console.log(chalk.gray(`  Answer: ${answer.answer}`));
  console.log(chalk.gray(`  Confidence: ${(answer.confidence * 100).toFixed(0)}%`));
} else {
  console.log(chalk.gray('  No answer found'));
}

// Check concept graph
console.log(chalk.green('\nConcept graph:'));
const concepts = semanticMemory.getAllConcepts();
console.log(chalk.white(`  Total concepts: ${concepts.length}`));
for (const concept of concepts.slice(0, 5)) {
  const related = semanticMemory.getRelatedConcepts(concept.name);
  console.log(chalk.gray(`    ${concept.name} → [${related.map((c) => c.name).join(', ')}]`));
}

// =============================================================================
// PART 4: MEMORY RETRIEVAL STRATEGIES
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Memory Retrieval Strategies'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nRetrieval strategies:'));
console.log(chalk.gray(`
  Recency    - Most recent memories first
  Relevance  - Most similar to query
  Importance - Highest importance score
  Frequency  - Most frequently accessed
  Hybrid     - Weighted combination of all factors
`));

// Create test memories with varying properties
const retrieverStore = new InMemoryStore();

const testMemories: MemoryEntry[] = [
  {
    id: generateMemoryId(),
    type: 'semantic',
    content: 'The user prefers dark mode in their IDE',
    importance: 0.8,
    createdAt: new Date(Date.now() - 1000 * 60 * 60), // 1 hour ago
    lastAccessed: new Date(Date.now() - 1000 * 60 * 30), // 30 min ago
    accessCount: 5,
    metadata: { source: 'user' },
    tags: ['preferences', 'ide'],
    relatedTo: [],
    decayRate: 0.95,
  },
  {
    id: generateMemoryId(),
    type: 'semantic',
    content: 'Python is the user\'s favorite language',
    importance: 0.9,
    createdAt: new Date(Date.now() - 1000 * 60 * 60 * 24), // 1 day ago
    lastAccessed: new Date(Date.now() - 1000 * 60 * 60 * 12), // 12 hours ago
    accessCount: 15,
    metadata: { source: 'user' },
    tags: ['preferences', 'python', 'language'],
    relatedTo: [],
    decayRate: 0.95,
  },
  {
    id: generateMemoryId(),
    type: 'semantic',
    content: 'The project uses TypeScript and React',
    importance: 0.7,
    createdAt: new Date(Date.now() - 1000 * 60 * 5), // 5 min ago
    lastAccessed: new Date(Date.now() - 1000 * 60 * 2), // 2 min ago
    accessCount: 2,
    metadata: { source: 'agent' },
    tags: ['project', 'typescript', 'react'],
    relatedTo: [],
    decayRate: 0.95,
  },
  {
    id: generateMemoryId(),
    type: 'episodic',
    content: 'User asked about Python debugging techniques',
    importance: 0.6,
    createdAt: new Date(Date.now() - 1000 * 60 * 60 * 2), // 2 hours ago
    lastAccessed: new Date(Date.now() - 1000 * 60 * 60), // 1 hour ago
    accessCount: 3,
    metadata: { source: 'agent' },
    tags: ['python', 'debugging'],
    relatedTo: [],
    decayRate: 0.95,
  },
];

for (const memory of testMemories) {
  await retrieverStore.store(memory);
}

const retriever = new MemoryRetriever(retrieverStore);

// Test different retrieval strategies
console.log(chalk.green('\nRetrieving with query "python":'));

const strategies: Array<'recency' | 'relevance' | 'importance' | 'frequency' | 'hybrid'> = [
  'recency',
  'relevance',
  'importance',
  'frequency',
  'hybrid',
];

for (const strategy of strategies) {
  const result = await retriever.retrieve('python', { strategy, limit: 2 });
  console.log(chalk.white(`\n  Strategy: ${strategy.toUpperCase()}`));
  for (const { memory, score, scoreBreakdown } of result.memories) {
    console.log(chalk.gray(`    Score: ${score.toFixed(3)} - "${memory.content.slice(0, 40)}..."`));
    console.log(chalk.gray(`      (rec: ${scoreBreakdown.recency.toFixed(2)}, rel: ${scoreBreakdown.relevance.toFixed(2)}, imp: ${scoreBreakdown.importance.toFixed(2)}, freq: ${scoreBreakdown.frequency.toFixed(2)})`));
  }
}

// =============================================================================
// PART 5: MEMORY DECAY
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Memory Decay'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nMemory decay simulation:'));
console.log(chalk.gray(`
  Memories decay over time (importance decreases).
  This mimics human forgetting - unimportant memories fade.

  Decay formula: importance × (decayRate ^ hours_since_access)

  With decayRate = 0.95:
    After 1 hour:   95% of original importance
    After 24 hours: ~29% of original importance
    After 1 week:   ~0.5% of original importance
`));

const decayDemo = {
  importance: 0.8,
  decayRate: 0.95,
};

const hoursAgo = [1, 6, 12, 24, 48, 168];
console.log(chalk.green('\n  Decay over time (initial importance: 0.8):'));
for (const hours of hoursAgo) {
  const decayed = decayDemo.importance * Math.pow(decayDemo.decayRate, hours);
  const bar = '█'.repeat(Math.floor(decayed * 20)) + '░'.repeat(20 - Math.floor(decayed * 20));
  console.log(chalk.gray(`    ${String(hours).padStart(3)}h ago: ${bar} ${(decayed * 100).toFixed(1)}%`));
}

// =============================================================================
// PART 6: WORKING MEMORY
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Working Memory (Current Context)'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nWorking memory concept:'));
console.log(chalk.gray(`
  Working memory is short-term, limited capacity storage.
  It holds information relevant to the current task.

  ┌─────────────────────────────────────────────────────────┐
  │                    Working Memory                       │
  │                   (capacity: 7±2 items)                 │
  │  ┌─────────────────────────────────────────────────┐   │
  │  │  Current goal: Help user debug Python code      │   │
  │  ├─────────────────────────────────────────────────┤   │
  │  │  Context items (by relevance):                  │   │
  │  │    1. User prefers Python         [0.9]         │   │
  │  │    2. Error is IndexError         [0.85]        │   │
  │  │    3. Code uses list comprehension[0.7]         │   │
  │  │    4. Project uses pytest         [0.5]         │   │
  │  └─────────────────────────────────────────────────┘   │
  │                                                         │
  │  When full → evict lowest relevance items              │
  └─────────────────────────────────────────────────────────┘
`));

// =============================================================================
// PART 7: INTEGRATION EXAMPLE
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Integration Example'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nSimulating memory-augmented conversation:'));

// Simulate a user interaction with memory retrieval
const userQuery = 'Can you help me with a Python project?';

console.log(chalk.white(`\n  User: "${userQuery}"`));

// Retrieve relevant memories
const relevantMemories = await retriever.retrieve(userQuery, {
  strategy: 'hybrid',
  limit: 3,
});

console.log(chalk.gray('\n  [Agent retrieves relevant memories]'));
for (const { memory, score } of relevantMemories.memories) {
  console.log(chalk.gray(`    • ${memory.content.slice(0, 50)}... (score: ${score.toFixed(2)})`));
}

// Generate context-aware response
console.log(chalk.gray('\n  [Agent generates response with memory context]'));
console.log(chalk.white(`\n  Assistant: "I'd be happy to help with your Python project!`));
console.log(chalk.white(`             I remember that Python is your favorite language,`));
console.log(chalk.white(`             so you'll enjoy this. What are you working on?"`));

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. Episodic memory stores interaction sequences'));
console.log(chalk.gray('  2. Semantic memory stores facts and knowledge'));
console.log(chalk.gray('  3. Different retrieval strategies serve different needs'));
console.log(chalk.gray('  4. Memory decay prevents outdated info from dominating'));
console.log(chalk.gray('  5. Working memory provides task-relevant context'));
console.log();
console.log(chalk.white('Key components:'));
console.log(chalk.gray('  • MemoryStore - Persistence layer for memories'));
console.log(chalk.gray('  • EpisodicMemory - Manages interaction history'));
console.log(chalk.gray('  • SemanticMemory - Manages facts and knowledge'));
console.log(chalk.gray('  • MemoryRetriever - Retrieves with configurable strategies'));
console.log();
console.log(chalk.bold.green('Next: Lesson 15 - Planning & Decomposition'));
console.log(chalk.gray('Break complex tasks into manageable steps!'));
console.log();
