/**
 * Exercise 14: Memory Retrieval - REFERENCE SOLUTION
 */

export interface Memory {
  id: string;
  content: string;
  importance: number;
  timestamp: number;
  tags: string[];
}

export interface RetrievalOptions {
  limit?: number;
  minImportance?: number;
  tags?: string[];
}

export class MemoryStore {
  private memories: Map<string, Memory> = new Map();

  add(content: string, importance: number, tags: string[] = []): Memory {
    const memory: Memory = {
      id: generateId(),
      content,
      importance,
      timestamp: Date.now(),
      tags,
    };
    this.memories.set(memory.id, memory);
    return memory;
  }

  retrieve(query: string, options: RetrievalOptions = {}): Memory[] {
    const { limit = 10, minImportance = 0, tags } = options;
    const queryLower = query.toLowerCase();

    let results = Array.from(this.memories.values())
      .filter(m => m.importance >= minImportance)
      .filter(m => !tags || tags.some(t => m.tags.includes(t)))
      .map(m => ({
        memory: m,
        score: this.calculateScore(m, queryLower),
      }))
      .filter(r => r.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map(r => r.memory);

    return results;
  }

  private calculateScore(memory: Memory, query: string): number {
    const contentLower = memory.content.toLowerCase();
    let score = 0;

    if (contentLower.includes(query)) score += 10;
    const words = query.split(/\s+/);
    for (const word of words) {
      if (contentLower.includes(word)) score += 2;
    }
    score *= (1 + memory.importance / 10);

    return score;
  }

  getById(id: string): Memory | undefined {
    return this.memories.get(id);
  }

  remove(id: string): boolean {
    return this.memories.delete(id);
  }

  getAll(): Memory[] {
    return Array.from(this.memories.values());
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 15);
}
