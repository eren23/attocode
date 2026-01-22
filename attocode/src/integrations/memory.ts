/**
 * Lesson 23: Memory Integration
 *
 * Integrates the memory system (Lesson 14) into the production agent.
 * Provides episodic, semantic, and working memory capabilities.
 */

import type { MemoryConfig, Message } from '../types.js';

// =============================================================================
// MEMORY TYPES
// =============================================================================

interface MemoryEntry {
  id: string;
  type: 'episodic' | 'semantic' | 'working';
  content: string;
  embedding?: number[];
  importance: number;
  createdAt: Date;
  lastAccessed: Date;
  accessCount: number;
  metadata: Record<string, unknown>;
}

interface RetrievalResult {
  entries: MemoryEntry[];
  strategy: string;
}

// =============================================================================
// MEMORY MANAGER
// =============================================================================

/**
 * Manages different types of memory for the agent.
 */
export class MemoryManager {
  private episodic: Map<string, MemoryEntry> = new Map();
  private semantic: Map<string, MemoryEntry> = new Map();
  private working: MemoryEntry[] = [];
  private config: MemoryConfig;

  constructor(config: MemoryConfig) {
    this.config = config;
  }

  /**
   * Store an episodic memory (interaction history).
   */
  storeEpisodic(content: string, metadata: Record<string, unknown> = {}): string {
    if (!this.config.types?.episodic) return '';

    const entry = this.createEntry('episodic', content, metadata);
    this.episodic.set(entry.id, entry);
    return entry.id;
  }

  /**
   * Store a semantic memory (facts, knowledge).
   */
  storeSemantic(content: string, metadata: Record<string, unknown> = {}): string {
    if (!this.config.types?.semantic) return '';

    const entry = this.createEntry('semantic', content, metadata);
    // Check for duplicates (simple text match)
    for (const existing of this.semantic.values()) {
      if (existing.content === content) {
        existing.accessCount++;
        existing.lastAccessed = new Date();
        return existing.id;
      }
    }
    this.semantic.set(entry.id, entry);
    return entry.id;
  }

  /**
   * Update working memory (current context).
   */
  updateWorking(content: string, metadata: Record<string, unknown> = {}): void {
    if (!this.config.types?.working) return;

    const entry = this.createEntry('working', content, metadata);

    // Keep working memory limited
    this.working.push(entry);
    if (this.working.length > 10) {
      this.working.shift();
    }
  }

  /**
   * Clear working memory.
   */
  clearWorking(): void {
    this.working = [];
  }

  /**
   * Retrieve relevant memories.
   */
  retrieve(query: string, limit?: number): RetrievalResult {
    const maxResults = limit || this.config.retrievalLimit || 10;
    const strategy = this.config.retrievalStrategy || 'hybrid';

    let entries: MemoryEntry[] = [];

    switch (strategy) {
      case 'recency':
        entries = this.retrieveByRecency(query, maxResults);
        break;
      case 'relevance':
        entries = this.retrieveByRelevance(query, maxResults);
        break;
      case 'importance':
        entries = this.retrieveByImportance(query, maxResults);
        break;
      case 'hybrid':
      default:
        entries = this.retrieveHybrid(query, maxResults);
        break;
    }

    // Update access counts
    for (const entry of entries) {
      entry.accessCount++;
      entry.lastAccessed = new Date();
    }

    return { entries, strategy };
  }

  /**
   * Get memory context as strings for prompt injection.
   */
  getContextStrings(query: string): string[] {
    const { entries } = this.retrieve(query);

    return entries.map((entry) => {
      const typeLabel = entry.type.charAt(0).toUpperCase() + entry.type.slice(1);
      return `[${typeLabel}] ${entry.content}`;
    });
  }

  /**
   * Store a conversation turn.
   */
  storeConversation(messages: Message[]): void {
    for (const msg of messages) {
      if (msg.role === 'user') {
        this.storeEpisodic(`User: ${msg.content}`, { role: 'user' });
      } else if (msg.role === 'assistant') {
        this.storeEpisodic(`Assistant: ${msg.content}`, { role: 'assistant' });

        // Extract potential facts for semantic memory
        this.extractAndStoreFacts(msg.content);
      }
    }

    // Update working memory with recent context
    const recentContent = messages
      .slice(-3)
      .map((m) => `${m.role}: ${m.content.slice(0, 100)}`)
      .join('\n');
    this.updateWorking(recentContent);
  }

  /**
   * Extract facts from response for semantic memory.
   */
  private extractAndStoreFacts(content: string): void {
    // Simple heuristic: look for declarative statements
    const sentences = content.split(/[.!?]+/).filter((s) => s.trim().length > 20);

    for (const sentence of sentences) {
      const trimmed = sentence.trim();
      // Store sentences that look like facts
      if (
        trimmed.includes(' is ') ||
        trimmed.includes(' are ') ||
        trimmed.includes(' was ') ||
        trimmed.includes(' were ') ||
        trimmed.includes(' has ') ||
        trimmed.includes(' have ')
      ) {
        this.storeSemantic(trimmed, { source: 'extracted' });
      }
    }
  }

  /**
   * Retrieve by recency.
   */
  private retrieveByRecency(query: string, limit: number): MemoryEntry[] {
    const all = this.getAllEntries();
    return all
      .sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime())
      .slice(0, limit);
  }

  /**
   * Retrieve by relevance (simple text matching).
   */
  private retrieveByRelevance(query: string, limit: number): MemoryEntry[] {
    const queryTerms = query.toLowerCase().split(/\s+/);
    const all = this.getAllEntries();

    const scored = all.map((entry) => {
      const content = entry.content.toLowerCase();
      let score = 0;
      for (const term of queryTerms) {
        if (content.includes(term)) {
          score += 1;
        }
      }
      return { entry, score };
    });

    return scored
      .filter((s) => s.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map((s) => s.entry);
  }

  /**
   * Retrieve by importance.
   */
  private retrieveByImportance(query: string, limit: number): MemoryEntry[] {
    const all = this.getAllEntries();
    return all.sort((a, b) => b.importance - a.importance).slice(0, limit);
  }

  /**
   * Hybrid retrieval combining strategies.
   */
  private retrieveHybrid(query: string, limit: number): MemoryEntry[] {
    const all = this.getAllEntries();
    const queryTerms = query.toLowerCase().split(/\s+/);
    const now = Date.now();

    const scored = all.map((entry) => {
      const content = entry.content.toLowerCase();

      // Relevance score
      let relevance = 0;
      for (const term of queryTerms) {
        if (content.includes(term)) relevance += 1;
      }
      relevance = relevance / Math.max(queryTerms.length, 1);

      // Recency score (decay over time)
      const ageHours = (now - entry.createdAt.getTime()) / (1000 * 60 * 60);
      const recency = Math.exp(-ageHours / 24); // Decay over 24 hours

      // Importance score
      const importance = entry.importance;

      // Access frequency bonus
      const frequencyBonus = Math.min(entry.accessCount * 0.1, 0.5);

      // Combined score
      const score = relevance * 0.4 + recency * 0.3 + importance * 0.2 + frequencyBonus * 0.1;

      return { entry, score };
    });

    return scored
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map((s) => s.entry);
  }

  /**
   * Get all memory entries.
   */
  private getAllEntries(): MemoryEntry[] {
    return [
      ...Array.from(this.episodic.values()),
      ...Array.from(this.semantic.values()),
      ...this.working,
    ];
  }

  /**
   * Create a memory entry.
   */
  private createEntry(
    type: MemoryEntry['type'],
    content: string,
    metadata: Record<string, unknown>
  ): MemoryEntry {
    const now = new Date();
    return {
      id: `mem-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      type,
      content,
      importance: this.calculateImportance(content, type),
      createdAt: now,
      lastAccessed: now,
      accessCount: 0,
      metadata,
    };
  }

  /**
   * Calculate importance score.
   */
  private calculateImportance(content: string, type: MemoryEntry['type']): number {
    let score = 0.5;

    // Type-based importance
    if (type === 'semantic') score += 0.2;
    if (type === 'working') score += 0.1;

    // Content-based heuristics
    if (content.includes('important') || content.includes('critical')) score += 0.1;
    if (content.includes('error') || content.includes('failed')) score += 0.1;
    if (content.length > 200) score += 0.05;

    return Math.min(score, 1);
  }

  /**
   * Get memory statistics.
   */
  getStats(): { episodic: number; semantic: number; working: number; total: number } {
    return {
      episodic: this.episodic.size,
      semantic: this.semantic.size,
      working: this.working.length,
      total: this.episodic.size + this.semantic.size + this.working.length,
    };
  }

  /**
   * Clear all memory.
   */
  clear(): void {
    this.episodic.clear();
    this.semantic.clear();
    this.working = [];
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createMemoryManager(config: MemoryConfig): MemoryManager {
  return new MemoryManager(config);
}
