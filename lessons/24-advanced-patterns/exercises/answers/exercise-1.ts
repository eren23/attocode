/**
 * Exercise 24: Checkpoint Store - REFERENCE SOLUTION
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

export class CheckpointStore {
  private checkpoints: Map<string, Checkpoint> = new Map();
  private counter = 0;

  createCheckpoint(threadId: string, messages: Message[], label?: string): Checkpoint {
    const checkpoint: Checkpoint = {
      id: `ckpt_${++this.counter}_${Date.now()}`,
      label,
      threadId,
      messages: messages.map(m => ({ ...m })),
      createdAt: new Date(),
    };

    this.checkpoints.set(checkpoint.id, checkpoint);
    return checkpoint;
  }

  getCheckpoint(checkpointId: string): Checkpoint | undefined {
    return this.checkpoints.get(checkpointId);
  }

  getByLabel(label: string): Checkpoint | undefined {
    for (const checkpoint of this.checkpoints.values()) {
      if (checkpoint.label === label) {
        return checkpoint;
      }
    }
    return undefined;
  }

  getThreadCheckpoints(threadId: string): Checkpoint[] {
    return Array.from(this.checkpoints.values())
      .filter(c => c.threadId === threadId)
      .sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime());
  }

  deleteCheckpoint(checkpointId: string): boolean {
    return this.checkpoints.delete(checkpointId);
  }

  pruneOldCheckpoints(maxPerThread: number): number {
    const byThread = new Map<string, Checkpoint[]>();

    // Group by thread
    for (const checkpoint of this.checkpoints.values()) {
      const list = byThread.get(checkpoint.threadId) || [];
      list.push(checkpoint);
      byThread.set(checkpoint.threadId, list);
    }

    let pruned = 0;

    // Prune each thread
    for (const checkpoints of byThread.values()) {
      // Sort by creation time (newest first)
      checkpoints.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());

      // Delete old ones
      for (let i = maxPerThread; i < checkpoints.length; i++) {
        this.checkpoints.delete(checkpoints[i].id);
        pruned++;
      }
    }

    return pruned;
  }
}
