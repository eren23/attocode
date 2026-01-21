/**
 * Lesson 14: Memory Systems Types
 *
 * Type definitions for agent memory - episodic, semantic, and working memory.
 */

// =============================================================================
// MEMORY ENTRY TYPES
// =============================================================================

/**
 * Types of memory entries.
 */
export type MemoryType = 'episodic' | 'semantic' | 'procedural';

/**
 * A single memory entry.
 */
export interface MemoryEntry {
  /** Unique identifier */
  id: string;

  /** Type of memory */
  type: MemoryType;

  /** The actual content */
  content: string;

  /** Vector embedding for semantic search */
  embedding?: number[];

  /** Importance score (0-1) */
  importance: number;

  /** When the memory was created */
  createdAt: Date;

  /** When the memory was last accessed */
  lastAccessed: Date;

  /** Number of times accessed */
  accessCount: number;

  /** Additional metadata */
  metadata: MemoryMetadata;

  /** Tags for categorization */
  tags: string[];

  /** Related memory IDs */
  relatedTo: string[];

  /** Decay factor (0-1, lower = decays faster) */
  decayRate: number;
}

/**
 * Metadata for a memory entry.
 */
export interface MemoryMetadata {
  /** Source of the memory (user, agent, system) */
  source: 'user' | 'agent' | 'system' | 'external';

  /** Session ID where this was created */
  sessionId?: string;

  /** Associated tool or action */
  tool?: string;

  /** Confidence in the memory accuracy */
  confidence?: number;

  /** Any additional properties */
  [key: string]: unknown;
}

// =============================================================================
// EPISODIC MEMORY (Interaction History)
// =============================================================================

/**
 * An episode (interaction sequence).
 */
export interface Episode {
  /** Episode ID */
  id: string;

  /** Session this episode belongs to */
  sessionId: string;

  /** Interactions in this episode */
  interactions: Interaction[];

  /** Start time */
  startedAt: Date;

  /** End time (if completed) */
  endedAt?: Date;

  /** Summary of the episode */
  summary?: string;

  /** Outcome (success, failure, abandoned) */
  outcome?: 'success' | 'failure' | 'abandoned' | 'ongoing';
}

/**
 * A single interaction within an episode.
 */
export interface Interaction {
  /** Interaction ID */
  id: string;

  /** Role (user or assistant) */
  role: 'user' | 'assistant' | 'system';

  /** Content of the interaction */
  content: string;

  /** Timestamp */
  timestamp: Date;

  /** Tool calls made (if any) */
  toolCalls?: ToolCallRecord[];

  /** Sentiment/emotion detected */
  sentiment?: 'positive' | 'neutral' | 'negative';
}

/**
 * Record of a tool call.
 */
export interface ToolCallRecord {
  /** Tool name */
  tool: string;

  /** Arguments */
  args: Record<string, unknown>;

  /** Result */
  result?: unknown;

  /** Success status */
  success: boolean;
}

// =============================================================================
// SEMANTIC MEMORY (Facts and Knowledge)
// =============================================================================

/**
 * A fact or piece of knowledge.
 */
export interface Fact {
  /** Fact ID */
  id: string;

  /** The fact statement */
  statement: string;

  /** Subject of the fact */
  subject: string;

  /** Predicate (relationship) */
  predicate: string;

  /** Object of the fact */
  object: string;

  /** Confidence level (0-1) */
  confidence: number;

  /** Source of this knowledge */
  source: string;

  /** When learned */
  learnedAt: Date;

  /** When last verified */
  verifiedAt?: Date;
}

/**
 * A concept in the knowledge graph.
 */
export interface Concept {
  /** Concept ID */
  id: string;

  /** Name of the concept */
  name: string;

  /** Description */
  description: string;

  /** Related concepts */
  relatedConcepts: string[];

  /** Facts about this concept */
  facts: string[]; // Fact IDs

  /** Embedding for similarity search */
  embedding?: number[];
}

// =============================================================================
// WORKING MEMORY (Short-term Context)
// =============================================================================

/**
 * Working memory state.
 */
export interface WorkingMemory {
  /** Current goal being pursued */
  currentGoal?: string;

  /** Active context items */
  context: ContextItem[];

  /** Attention weights for context items */
  attention: Map<string, number>;

  /** Maximum capacity */
  capacity: number;

  /** Items pending eviction */
  evictionQueue: string[];
}

/**
 * An item in working memory.
 */
export interface ContextItem {
  /** Item ID */
  id: string;

  /** Content */
  content: string;

  /** Relevance to current goal (0-1) */
  relevance: number;

  /** When added to working memory */
  addedAt: Date;

  /** Source (from long-term memory or recent input) */
  source: 'long_term' | 'recent_input' | 'retrieved';
}

// =============================================================================
// RETRIEVAL TYPES
// =============================================================================

/**
 * Options for memory retrieval.
 */
export interface RetrievalOptions {
  /** Maximum number of results */
  limit: number;

  /** Retrieval strategy */
  strategy: RetrievalStrategy;

  /** Minimum relevance threshold */
  threshold?: number;

  /** Filter by memory type */
  types?: MemoryType[];

  /** Filter by tags */
  tags?: string[];

  /** Time range filter */
  timeRange?: {
    start?: Date;
    end?: Date;
  };

  /** Include decay calculation */
  applyDecay?: boolean;
}

/**
 * Retrieval strategies.
 */
export type RetrievalStrategy =
  | 'recency'      // Most recent first
  | 'relevance'    // Most relevant to query
  | 'importance'   // Highest importance first
  | 'frequency'    // Most accessed first
  | 'hybrid';      // Combination of factors

/**
 * Default retrieval options.
 */
export const DEFAULT_RETRIEVAL_OPTIONS: RetrievalOptions = {
  limit: 10,
  strategy: 'hybrid',
  threshold: 0.3,
  applyDecay: true,
};

/**
 * Result of a retrieval operation.
 */
export interface RetrievalResult {
  /** Retrieved memories */
  memories: ScoredMemory[];

  /** Query used */
  query: string;

  /** Strategy used */
  strategy: RetrievalStrategy;

  /** Total memories searched */
  totalSearched: number;

  /** Search duration (ms) */
  durationMs: number;
}

/**
 * A memory with relevance score.
 */
export interface ScoredMemory {
  /** The memory entry */
  memory: MemoryEntry;

  /** Relevance score (0-1) */
  score: number;

  /** Score breakdown */
  scoreBreakdown: {
    recency: number;
    relevance: number;
    importance: number;
    frequency: number;
  };
}

// =============================================================================
// MEMORY STORE INTERFACE
// =============================================================================

/**
 * Interface for memory persistence.
 */
export interface MemoryStore {
  /** Store a memory */
  store(entry: MemoryEntry): Promise<void>;

  /** Retrieve a memory by ID */
  get(id: string): Promise<MemoryEntry | null>;

  /** Update a memory */
  update(id: string, updates: Partial<MemoryEntry>): Promise<void>;

  /** Delete a memory */
  delete(id: string): Promise<void>;

  /** Query memories */
  query(options: QueryOptions): Promise<MemoryEntry[]>;

  /** Get all memories */
  getAll(): Promise<MemoryEntry[]>;

  /** Clear all memories */
  clear(): Promise<void>;

  /** Get memory count */
  count(): Promise<number>;
}

/**
 * Query options for memory store.
 */
export interface QueryOptions {
  /** Filter by type */
  type?: MemoryType;

  /** Filter by tags */
  tags?: string[];

  /** Minimum importance */
  minImportance?: number;

  /** Time range */
  after?: Date;
  before?: Date;

  /** Limit results */
  limit?: number;

  /** Offset for pagination */
  offset?: number;

  /** Sort order */
  sortBy?: 'createdAt' | 'lastAccessed' | 'importance' | 'accessCount';
  sortOrder?: 'asc' | 'desc';
}

// =============================================================================
// MEMORY EVENTS
// =============================================================================

/**
 * Events emitted by memory systems.
 */
export type MemoryEvent =
  | { type: 'memory.stored'; entry: MemoryEntry }
  | { type: 'memory.accessed'; id: string }
  | { type: 'memory.updated'; id: string; changes: Partial<MemoryEntry> }
  | { type: 'memory.deleted'; id: string }
  | { type: 'memory.decayed'; id: string; newImportance: number }
  | { type: 'memory.consolidated'; ids: string[]; newId: string }
  | { type: 'working_memory.overflow'; evicted: string[] };

/**
 * Listener for memory events.
 */
export type MemoryEventListener = (event: MemoryEvent) => void;

// =============================================================================
// CONFIGURATION
// =============================================================================

/**
 * Configuration for memory system.
 */
export interface MemoryConfig {
  /** Maximum memories to store */
  maxMemories: number;

  /** Working memory capacity */
  workingMemoryCapacity: number;

  /** Default decay rate */
  defaultDecayRate: number;

  /** Decay interval (ms) */
  decayIntervalMs: number;

  /** Consolidation threshold */
  consolidationThreshold: number;

  /** Enable persistence */
  persistenceEnabled: boolean;

  /** Persistence path */
  persistencePath?: string;
}

/**
 * Default memory configuration.
 */
export const DEFAULT_MEMORY_CONFIG: MemoryConfig = {
  maxMemories: 10000,
  workingMemoryCapacity: 10,
  defaultDecayRate: 0.95,
  decayIntervalMs: 3600000, // 1 hour
  consolidationThreshold: 0.8,
  persistenceEnabled: false,
};
