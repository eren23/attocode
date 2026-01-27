# Lesson 14: Memory Systems

> Enabling agents to remember beyond the conversation window

## What You'll Learn

1. **Episodic Memory**: Storing and retrieving interaction history
2. **Semantic Memory**: Managing facts and knowledge
3. **Retrieval Strategies**: Different ways to find relevant memories
4. **Memory Decay**: Simulating forgetting for relevance
5. **Working Memory**: Managing current context

## Why This Matters

Conversation history alone isn't enough:

```
Without Memory                  With Memory
─────────────────               ───────────────
User: My name is Alice          User: My name is Alice
Bot: Nice to meet you!          Bot: Nice to meet you!
                                [Stores: name = Alice]
... context window fills ...    ... context window fills...
... memory lost ...             [Memory persists]

User: What's my name?           User: What's my name?
Bot: I don't know.              Bot: Your name is Alice!
```

Memory enables:
- **Personalization**: Remember user preferences
- **Continuity**: Maintain context across sessions
- **Learning**: Build knowledge over time
- **Relevance**: Surface useful information

## Key Concepts

### Memory Types

```
┌─────────────┬───────────────────────────────────────────┐
│ Type        │ Purpose                                   │
├─────────────┼───────────────────────────────────────────┤
│ Episodic    │ "What happened" - Interaction sequences   │
│ Semantic    │ "What I know"   - Facts and knowledge     │
│ Procedural  │ "How to do"     - Learned procedures      │
│ Working     │ "Right now"     - Current context         │
└─────────────┴───────────────────────────────────────────┘
```

### Memory Entry Structure

```typescript
interface MemoryEntry {
  id: string;
  type: 'episodic' | 'semantic' | 'procedural';
  content: string;
  embedding?: number[];        // For semantic search
  importance: number;          // 0-1
  createdAt: Date;
  lastAccessed: Date;
  accessCount: number;
  tags: string[];
  decayRate: number;          // How fast it fades
}
```

### Retrieval Strategies

```
Strategy    │ Best For                         │ Scoring
────────────┼──────────────────────────────────┼───────────────
Recency     │ Recent context                   │ Time since access
Relevance   │ Semantic search                  │ Query similarity
Importance  │ Key facts                        │ Importance score
Frequency   │ Common knowledge                 │ Access count
Hybrid      │ General use                      │ Weighted combination
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Memory types and interfaces |
| `memory-store.ts` | Persistence layer (in-memory, file) |
| `episodic-memory.ts` | Interaction history management |
| `semantic-memory.ts` | Facts and knowledge management |
| `retriever.ts` | Memory retrieval strategies |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:14
```

## Code Examples

### Basic Memory Storage

```typescript
import { InMemoryStore, generateMemoryId } from './memory-store.js';

const store = new InMemoryStore();

// Store a memory
await store.store({
  id: generateMemoryId(),
  type: 'semantic',
  content: 'The user prefers TypeScript',
  importance: 0.8,
  createdAt: new Date(),
  lastAccessed: new Date(),
  accessCount: 0,
  metadata: { source: 'user' },
  tags: ['preferences', 'typescript'],
  relatedTo: [],
  decayRate: 0.95,
});

// Query memories
const memories = await store.query({
  type: 'semantic',
  tags: ['preferences'],
  sortBy: 'importance',
  sortOrder: 'desc',
});
```

### Episodic Memory

```typescript
import { createEpisodicMemory } from './episodic-memory.js';

const episodic = createEpisodicMemory(store);

// Start an episode
episodic.startEpisode();

// Record interactions
episodic.recordUserMessage('Help me with Python');
episodic.recordAssistantMessage('Of course!', [
  { tool: 'search', args: {}, success: true }
]);

// End episode
const episode = await episodic.endEpisode('success');

// Later: retrieve similar episodes
const similar = await episodic.searchEpisodes('Python help');
```

### Semantic Memory

```typescript
import { createSemanticMemory } from './semantic-memory.js';

const semantic = createSemanticMemory(store);

// Learn facts
await semantic.learnFact('Python is a programming language', {
  confidence: 0.95,
});

await semantic.learnFact('The user prefers dark mode', {
  confidence: 0.8,
  source: 'user',
});

// Query knowledge
const facts = await semantic.getFactsAbout('Python');

// Answer questions
const answer = await semantic.answerQuestion('What is Python?');
console.log(answer.answer, answer.confidence);
```

### Memory Retrieval

```typescript
import { MemoryRetriever } from './retriever.js';

const retriever = new MemoryRetriever(store, {
  recency: 0.3,
  relevance: 0.3,
  importance: 0.25,
  frequency: 0.15,
});

// Retrieve with query
const result = await retriever.retrieve('Python debugging', {
  strategy: 'hybrid',
  limit: 5,
  threshold: 0.3,
});

for (const { memory, score, scoreBreakdown } of result.memories) {
  console.log(`${memory.content} (score: ${score.toFixed(2)})`);
  console.log(`  Recency: ${scoreBreakdown.recency.toFixed(2)}`);
  console.log(`  Relevance: ${scoreBreakdown.relevance.toFixed(2)}`);
}
```

## Memory Decay

Memories fade over time to prevent old information from dominating:

```
Decay formula: importance × (decayRate ^ hours_since_access)

With decayRate = 0.95:
  After 1 hour:   95% of original importance
  After 24 hours: ~29% of original importance
  After 1 week:   ~0.5% of original importance
```

Configure decay per memory:
- High decay (0.8): Short-term, context-specific
- Low decay (0.98): Long-term, important facts

## Working Memory

Short-term storage for current task context:

```
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
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  When full → evict lowest relevance items              │
└─────────────────────────────────────────────────────────┘
```

## Best Practices

### Choose the Right Memory Type
- **Episodic**: For interaction patterns and outcomes
- **Semantic**: For facts, preferences, knowledge
- **Procedural**: For learned workflows

### Balance Retrieval Strategies
- Recent context → Recency-focused
- Knowledge search → Relevance-focused
- Important facts → Importance-focused
- General use → Hybrid

### Manage Memory Size
- Set importance thresholds
- Use decay to fade old memories
- Consolidate similar memories

### Consider Privacy
- Allow users to delete memories
- Be transparent about what's stored
- Handle sensitive information carefully

## Next Steps

In **Lesson 15: Planning & Decomposition**, we'll use memory to:
- Remember task progress across sessions
- Learn from past planning attempts
- Build procedural memory for common workflows
