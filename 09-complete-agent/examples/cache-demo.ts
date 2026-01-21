/**
 * Cache Demo: Demonstrating Prompt Caching Benefits
 *
 * Run: npx tsx 08-complete-agent/examples/cache-demo.ts
 *
 * This example shows:
 * 1. How to structure messages for caching
 * 2. Estimating cache savings
 * 3. Building cache-aware conversations
 */

import {
  createCacheableContent,
  createCacheableSystemMessage,
  createCacheableUserMessage,
  estimateCacheSavings,
  CacheAwareConversation,
  hasCacheableContent,
} from '../cache.js';

// =============================================================================
// DEMO: Basic Cacheable Content
// =============================================================================

console.log('╔════════════════════════════════════════════════════════════════╗');
console.log('║  Cache Demo: Prompt Caching Patterns                           ║');
console.log('╚════════════════════════════════════════════════════════════════╝\n');

console.log('1. Creating Cacheable Content\n');
console.log('─'.repeat(60));

// Simple cacheable content
const cachedContent = createCacheableContent('This content will be cached', true);
const uncachedContent = createCacheableContent('This content will NOT be cached', false);

console.log('Cached content:');
console.log(JSON.stringify(cachedContent, null, 2));
console.log('\nUncached content:');
console.log(JSON.stringify(uncachedContent, null, 2));

// =============================================================================
// DEMO: System Message with Caching
// =============================================================================

console.log('\n\n2. System Message with Static/Dynamic Parts\n');
console.log('─'.repeat(60));

const systemMessage = createCacheableSystemMessage({
  static: `You are a coding assistant with these tools:
- read_file: Read file contents
- write_file: Write to a file
- edit_file: Make surgical edits
- bash: Execute shell commands

Always read files before modifying them.
Use edit_file with precise string matching.`,

  dynamic: 'The user is working in a TypeScript project.',
});

console.log('System message structure:');
console.log(`Role: ${systemMessage.role}`);
console.log(`Content parts: ${(systemMessage.content as Array<unknown>).length}`);
console.log('\nFirst part (CACHED - static instructions):');
console.log('  cache_control:', (systemMessage.content as Array<{ cache_control?: unknown }>)[0].cache_control);
console.log('\nSecond part (NOT CACHED - dynamic context):');
console.log('  cache_control:', (systemMessage.content as Array<{ cache_control?: unknown }>)[1]?.cache_control ?? 'undefined');

// =============================================================================
// DEMO: User Message with Large Context
// =============================================================================

console.log('\n\n3. User Message with Large Context (File Contents)\n');
console.log('─'.repeat(60));

const largeFileContent = `
// Large file that will be referenced multiple times
export class UserService {
  private users: Map<string, User> = new Map();

  async getUser(id: string): Promise<User | undefined> {
    return this.users.get(id);
  }

  async createUser(data: CreateUserInput): Promise<User> {
    const user = { id: generateId(), ...data, createdAt: new Date() };
    this.users.set(user.id, user);
    return user;
  }

  async updateUser(id: string, data: Partial<User>): Promise<User> {
    const existing = this.users.get(id);
    if (!existing) throw new Error('User not found');
    const updated = { ...existing, ...data };
    this.users.set(id, updated);
    return updated;
  }
}
`.repeat(10); // Simulate a large file

const userMessage = createCacheableUserMessage(
  'Add input validation to the createUser method',
  largeFileContent
);

console.log('User message with context:');
console.log(`Content parts: ${(userMessage.content as Array<unknown>).length}`);
console.log(`First part (context): ${(userMessage.content as Array<{ text: string }>)[0].text.length} chars - CACHED`);
console.log(`Second part (instruction): ${(userMessage.content as Array<{ text: string }>)[1].text.length} chars - not cached`);

// =============================================================================
// DEMO: Cache Statistics
// =============================================================================

console.log('\n\n4. Estimating Cache Savings\n');
console.log('─'.repeat(60));

const conversation = [
  systemMessage,
  userMessage,
];

const stats = estimateCacheSavings(conversation);

console.log('Cache Statistics:');
console.log(`  Total tokens (est): ${stats.estimatedTokens}`);
console.log(`  Cacheable tokens:   ${stats.cacheableTokens}`);
console.log(`  Worth caching:      ${stats.worthCaching ? 'Yes ✓' : 'No'}`);
console.log(`  Estimated savings:  ${stats.estimatedSavings}`);
console.log(`  Recommendation:     ${stats.recommendation}`);

// =============================================================================
// DEMO: Cache-Aware Conversation Builder
// =============================================================================

console.log('\n\n5. Building a Cache-Aware Conversation\n');
console.log('─'.repeat(60));

const convo = new CacheAwareConversation(
  // Static system prompt (cached)
  `You are a helpful coding assistant.
Available tools: read_file, write_file, edit_file, bash.
Always be concise and precise.`,

  // Dynamic context (not cached)
  'Working directory: /project/src'
);

// Add some static context (like documentation - cached)
convo.addStaticContext('user', 'Here is the API documentation:\n' + '...docs content...'.repeat(100));

// Add conversation history
convo.addMessage({ role: 'user', content: 'Read the package.json file' });
convo.addMessage({ role: 'assistant', content: 'I\'ll read that file for you.' });
convo.addMessage({ role: 'user', content: 'Now update the version to 2.0.0' });
convo.addMessage({ role: 'assistant', content: 'I\'ll update the version.' });
convo.addMessage({ role: 'user', content: 'Add a new script called "deploy"' });

// Build with caching (older messages get cached)
const messages = convo.build(2); // Last 2 messages won't be cached

console.log('Built conversation:');
console.log(`  Total messages: ${messages.length}`);
console.log(`  Has cacheable content: ${hasCacheableContent(messages)}`);

const convoStats = convo.getStats();
console.log(`\nConversation stats:`);
console.log(`  Cacheable tokens: ${convoStats.cacheableTokens}`);
console.log(`  Estimated savings: ${convoStats.estimatedSavings}`);

// =============================================================================
// DEMO: Cost Comparison
// =============================================================================

console.log('\n\n6. Cost Comparison Example\n');
console.log('─'.repeat(60));

// Simulate a 10-turn conversation
console.log('Simulating 10-turn agent conversation...\n');

const COST_PER_1K_INPUT = 0.003; // $3 per 1M tokens (Claude Sonnet via OpenRouter)
const CACHE_WRITE_MULTIPLIER = 1.25; // 25% extra for cache write
const CACHE_READ_MULTIPLIER = 0.1; // 90% discount for cache read

const systemTokens = 2000;
const avgTurnTokens = 500;

let withoutCacheCost = 0;
let withCacheCost = 0;

console.log('Turn | Without Cache | With Cache');
console.log('─────┼───────────────┼────────────');

for (let turn = 1; turn <= 10; turn++) {
  const historyTokens = (turn - 1) * avgTurnTokens;
  const totalTokens = systemTokens + historyTokens + avgTurnTokens;

  // Without cache: pay full price every time
  const turnCostWithout = (totalTokens / 1000) * COST_PER_1K_INPUT;
  withoutCacheCost += turnCostWithout;

  // With cache: first turn is cache write, subsequent are cache read
  let turnCostWith: number;
  if (turn === 1) {
    // Cache write (system prompt)
    turnCostWith = ((systemTokens * CACHE_WRITE_MULTIPLIER) / 1000) * COST_PER_1K_INPUT;
    turnCostWith += ((avgTurnTokens) / 1000) * COST_PER_1K_INPUT;
  } else {
    // Cache read (system prompt) + new tokens
    turnCostWith = ((systemTokens * CACHE_READ_MULTIPLIER) / 1000) * COST_PER_1K_INPUT;
    turnCostWith += ((historyTokens + avgTurnTokens) / 1000) * COST_PER_1K_INPUT;
  }
  withCacheCost += turnCostWith;

  console.log(`  ${turn.toString().padStart(2)}  | $${turnCostWithout.toFixed(4).padStart(11)} | $${turnCostWith.toFixed(4).padStart(9)}`);
}

console.log('─────┼───────────────┼────────────');
console.log(`Total | $${withoutCacheCost.toFixed(4).padStart(11)} | $${withCacheCost.toFixed(4).padStart(9)}`);
console.log(`\nSavings: $${(withoutCacheCost - withCacheCost).toFixed(4)} (${Math.round((1 - withCacheCost / withoutCacheCost) * 100)}%)`);

// =============================================================================
// SUMMARY
// =============================================================================

console.log('\n\n═══════════════════════════════════════════════════════════════════');
console.log('KEY TAKEAWAYS');
console.log('═══════════════════════════════════════════════════════════════════');
console.log(`
1. Mark STATIC content for caching (system prompts, tool definitions)
2. Keep DYNAMIC content uncached (latest user message, changing context)
3. Use CacheAwareConversation for automatic cache management
4. Caching benefits grow with conversation length
5. Only worth it for content >1000 tokens
6. Cache expires after ~5 minutes of inactivity
`);
