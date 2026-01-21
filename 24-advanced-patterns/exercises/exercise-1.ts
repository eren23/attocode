/**
 * Exercise 24: Checkpoint Store
 * Implement state checkpointing for recovery and rollback.
 */

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  timestamp: Date;
}

export interface Checkpoint {
  id: string;
  label?: string;
  threadId: string;
  messages: Message[];
  createdAt: Date;
}

/**
 * TODO: Implement CheckpointStore
 */
export class CheckpointStore {
  private checkpoints: Map<string, Checkpoint> = new Map();
  private counter = 0;

  createCheckpoint(_threadId: string, _messages: Message[], _label?: string): Checkpoint {
    // TODO: Create and store a checkpoint
    // Generate unique ID with counter
    throw new Error('TODO: Implement createCheckpoint');
  }

  getCheckpoint(_checkpointId: string): Checkpoint | undefined {
    // TODO: Return checkpoint by ID
    throw new Error('TODO: Implement getCheckpoint');
  }

  getByLabel(_label: string): Checkpoint | undefined {
    // TODO: Find checkpoint by label
    throw new Error('TODO: Implement getByLabel');
  }

  getThreadCheckpoints(_threadId: string): Checkpoint[] {
    // TODO: Get all checkpoints for a thread, sorted by creation time
    throw new Error('TODO: Implement getThreadCheckpoints');
  }

  deleteCheckpoint(_checkpointId: string): boolean {
    // TODO: Delete a checkpoint
    throw new Error('TODO: Implement deleteCheckpoint');
  }

  pruneOldCheckpoints(_maxPerThread: number): number {
    // TODO: Keep only N most recent checkpoints per thread
    // Return number of checkpoints deleted
    throw new Error('TODO: Implement pruneOldCheckpoints');
  }
}
