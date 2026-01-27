/**
 * Lesson 14: Episodic Memory
 *
 * Manages interaction history as episodes.
 * Episodes are sequences of interactions with outcomes.
 */

import type {
  MemoryStore,
  MemoryEntry,
  Episode,
  Interaction,
  ToolCallRecord,
  MemoryMetadata,
} from './types.js';
import { generateMemoryId } from './memory-store.js';

// =============================================================================
// EPISODIC MEMORY MANAGER
// =============================================================================

/**
 * Manages episodic memory (interaction history).
 */
export class EpisodicMemory {
  private store: MemoryStore;
  private currentEpisode: Episode | null = null;
  private sessionId: string;

  constructor(store: MemoryStore, sessionId?: string) {
    this.store = store;
    this.sessionId = sessionId || generateMemoryId('session');
  }

  // ===========================================================================
  // EPISODE MANAGEMENT
  // ===========================================================================

  /**
   * Start a new episode.
   */
  startEpisode(): Episode {
    // End current episode if exists
    if (this.currentEpisode) {
      this.endEpisode('abandoned');
    }

    this.currentEpisode = {
      id: generateMemoryId('episode'),
      sessionId: this.sessionId,
      interactions: [],
      startedAt: new Date(),
      outcome: 'ongoing',
    };

    return this.currentEpisode;
  }

  /**
   * End the current episode.
   */
  async endEpisode(
    outcome: Episode['outcome'] = 'success'
  ): Promise<Episode | null> {
    if (!this.currentEpisode) return null;

    this.currentEpisode.endedAt = new Date();
    this.currentEpisode.outcome = outcome;

    // Generate summary
    this.currentEpisode.summary = this.summarizeEpisode(this.currentEpisode);

    // Store as memory
    await this.storeEpisodeAsMemory(this.currentEpisode);

    const episode = this.currentEpisode;
    this.currentEpisode = null;

    return episode;
  }

  /**
   * Get current episode.
   */
  getCurrentEpisode(): Episode | null {
    return this.currentEpisode;
  }

  // ===========================================================================
  // INTERACTION RECORDING
  // ===========================================================================

  /**
   * Record a user interaction.
   */
  recordUserMessage(content: string): Interaction {
    if (!this.currentEpisode) {
      this.startEpisode();
    }

    const interaction: Interaction = {
      id: generateMemoryId('int'),
      role: 'user',
      content,
      timestamp: new Date(),
      sentiment: this.detectSentiment(content),
    };

    this.currentEpisode!.interactions.push(interaction);
    return interaction;
  }

  /**
   * Record an assistant response.
   */
  recordAssistantMessage(
    content: string,
    toolCalls?: ToolCallRecord[]
  ): Interaction {
    if (!this.currentEpisode) {
      this.startEpisode();
    }

    const interaction: Interaction = {
      id: generateMemoryId('int'),
      role: 'assistant',
      content,
      timestamp: new Date(),
      toolCalls,
    };

    this.currentEpisode!.interactions.push(interaction);
    return interaction;
  }

  /**
   * Record a system message.
   */
  recordSystemMessage(content: string): Interaction {
    if (!this.currentEpisode) {
      this.startEpisode();
    }

    const interaction: Interaction = {
      id: generateMemoryId('int'),
      role: 'system',
      content,
      timestamp: new Date(),
    };

    this.currentEpisode!.interactions.push(interaction);
    return interaction;
  }

  // ===========================================================================
  // EPISODE RETRIEVAL
  // ===========================================================================

  /**
   * Get recent episodes.
   */
  async getRecentEpisodes(limit = 10): Promise<Episode[]> {
    const memories = await this.store.query({
      type: 'episodic',
      sortBy: 'createdAt',
      sortOrder: 'desc',
      limit,
    });

    return memories.map((m) => this.memoryToEpisode(m));
  }

  /**
   * Get episodes by outcome.
   */
  async getEpisodesByOutcome(
    outcome: Episode['outcome'],
    limit = 10
  ): Promise<Episode[]> {
    const memories = await this.store.query({
      type: 'episodic',
      sortBy: 'createdAt',
      sortOrder: 'desc',
      limit: limit * 2, // Fetch more to filter
    });

    return memories
      .map((m) => this.memoryToEpisode(m))
      .filter((e) => e.outcome === outcome)
      .slice(0, limit);
  }

  /**
   * Search episodes by content.
   */
  async searchEpisodes(query: string, limit = 10): Promise<Episode[]> {
    const memories = await this.store.query({
      type: 'episodic',
      sortBy: 'createdAt',
      sortOrder: 'desc',
    });

    const queryLower = query.toLowerCase();

    return memories
      .map((m) => this.memoryToEpisode(m))
      .filter((e) => {
        // Search in summary
        if (e.summary?.toLowerCase().includes(queryLower)) return true;

        // Search in interactions
        return e.interactions.some((i) =>
          i.content.toLowerCase().includes(queryLower)
        );
      })
      .slice(0, limit);
  }

  /**
   * Get similar episodes (based on interactions).
   */
  async getSimilarEpisodes(episode: Episode, limit = 5): Promise<Episode[]> {
    // Extract key topics from episode
    const topics = this.extractTopics(episode);

    // Search for episodes with similar topics
    const memories = await this.store.query({
      type: 'episodic',
      sortBy: 'createdAt',
      sortOrder: 'desc',
    });

    const scored = memories
      .map((m) => {
        const e = this.memoryToEpisode(m);
        const eTopics = this.extractTopics(e);
        const overlap = topics.filter((t) => eTopics.includes(t)).length;
        return { episode: e, score: overlap };
      })
      .filter((s) => s.episode.id !== episode.id && s.score > 0)
      .sort((a, b) => b.score - a.score);

    return scored.slice(0, limit).map((s) => s.episode);
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  /**
   * Store episode as a memory entry.
   */
  private async storeEpisodeAsMemory(episode: Episode): Promise<void> {
    const importance = this.calculateEpisodeImportance(episode);

    const entry: MemoryEntry = {
      id: episode.id,
      type: 'episodic',
      content: JSON.stringify(episode),
      importance,
      createdAt: episode.startedAt,
      lastAccessed: new Date(),
      accessCount: 0,
      metadata: {
        source: 'agent',
        sessionId: episode.sessionId,
        interactionCount: episode.interactions.length,
        outcome: episode.outcome,
        summary: episode.summary,
      },
      tags: this.extractTopics(episode),
      relatedTo: [],
      decayRate: 0.95,
    };

    await this.store.store(entry);
  }

  /**
   * Convert memory entry back to episode.
   */
  private memoryToEpisode(memory: MemoryEntry): Episode {
    try {
      const episode = JSON.parse(memory.content) as Episode;
      // Reconstruct Date objects
      episode.startedAt = new Date(episode.startedAt);
      if (episode.endedAt) episode.endedAt = new Date(episode.endedAt);
      for (const interaction of episode.interactions) {
        interaction.timestamp = new Date(interaction.timestamp);
      }
      return episode;
    } catch {
      // Return minimal episode on parse error
      return {
        id: memory.id,
        sessionId: memory.metadata.sessionId as string || 'unknown',
        interactions: [],
        startedAt: memory.createdAt,
        summary: memory.content,
      };
    }
  }

  /**
   * Summarize an episode.
   */
  private summarizeEpisode(episode: Episode): string {
    const userMessages = episode.interactions.filter((i) => i.role === 'user');
    const assistantMessages = episode.interactions.filter((i) => i.role === 'assistant');
    const toolCalls = episode.interactions
      .flatMap((i) => i.toolCalls || [])
      .map((t) => t.tool);

    const uniqueTools = [...new Set(toolCalls)];

    let summary = `Episode with ${userMessages.length} user messages and ${assistantMessages.length} responses.`;

    if (uniqueTools.length > 0) {
      summary += ` Tools used: ${uniqueTools.join(', ')}.`;
    }

    if (userMessages.length > 0) {
      const firstMessage = userMessages[0].content.slice(0, 100);
      summary += ` Started with: "${firstMessage}${userMessages[0].content.length > 100 ? '...' : ''}"`;
    }

    summary += ` Outcome: ${episode.outcome || 'unknown'}.`;

    return summary;
  }

  /**
   * Calculate episode importance.
   */
  private calculateEpisodeImportance(episode: Episode): number {
    let importance = 0.5; // Base importance

    // More interactions = more important
    const interactionBonus = Math.min(0.2, episode.interactions.length * 0.02);
    importance += interactionBonus;

    // Tool usage indicates more complex interaction
    const toolCount = episode.interactions
      .flatMap((i) => i.toolCalls || [])
      .length;
    importance += Math.min(0.15, toolCount * 0.03);

    // Successful outcomes are more important to remember
    if (episode.outcome === 'success') {
      importance += 0.1;
    } else if (episode.outcome === 'failure') {
      importance += 0.15; // Failures are important to learn from
    }

    return Math.min(1, importance);
  }

  /**
   * Extract topics from episode.
   */
  private extractTopics(episode: Episode): string[] {
    const topics = new Set<string>();
    const stopWords = new Set(['the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because', 'until', 'while', 'this', 'that', 'these', 'those', 'it', 'its']);

    for (const interaction of episode.interactions) {
      // Extract words from content
      const words = interaction.content.toLowerCase()
        .split(/\W+/)
        .filter((w) => w.length > 3 && !stopWords.has(w));

      words.slice(0, 10).forEach((w) => topics.add(w));

      // Add tool names as topics
      for (const tool of interaction.toolCalls || []) {
        topics.add(tool.tool.toLowerCase());
      }
    }

    return Array.from(topics).slice(0, 15);
  }

  /**
   * Simple sentiment detection.
   */
  private detectSentiment(content: string): Interaction['sentiment'] {
    const lower = content.toLowerCase();

    const positiveWords = ['thanks', 'thank', 'great', 'good', 'excellent', 'perfect', 'awesome', 'love', 'helpful', 'appreciate'];
    const negativeWords = ['bad', 'wrong', 'error', 'fail', 'issue', 'problem', 'broken', 'hate', 'terrible', 'awful'];

    const positiveCount = positiveWords.filter((w) => lower.includes(w)).length;
    const negativeCount = negativeWords.filter((w) => lower.includes(w)).length;

    if (positiveCount > negativeCount) return 'positive';
    if (negativeCount > positiveCount) return 'negative';
    return 'neutral';
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createEpisodicMemory(
  store: MemoryStore,
  sessionId?: string
): EpisodicMemory {
  return new EpisodicMemory(store, sessionId);
}
