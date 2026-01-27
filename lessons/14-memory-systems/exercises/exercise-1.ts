/**
 * Exercise 14: Memory Retrieval
 * Implement a memory store with importance scoring.
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

/**
 * TODO: Implement MemoryStore
 */
export class MemoryStore {
  add(_content: string, _importance: number, _tags: string[] = []): Memory {
    throw new Error('TODO: Implement add');
  }

  retrieve(_query: string, _options?: RetrievalOptions): Memory[] {
    // TODO: Score by relevance (content match) and importance
    throw new Error('TODO: Implement retrieve');
  }

  getById(_id: string): Memory | undefined {
    throw new Error('TODO: Implement getById');
  }

  remove(_id: string): boolean {
    throw new Error('TODO: Implement remove');
  }

  getAll(): Memory[] {
    throw new Error('TODO: Implement getAll');
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 15);
}
