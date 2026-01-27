/**
 * Exercise Tests: Lesson 24 - Checkpoint Store
 */
import { describe, it, expect } from 'vitest';
import { CheckpointStore, Message } from './exercises/answers/exercise-1.js';

describe('CheckpointStore', () => {
  const createMessages = (count: number): Message[] =>
    Array.from({ length: count }, (_, i) => ({
      id: `msg_${i}`,
      role: 'user' as const,
      content: `Message ${i}`,
      timestamp: new Date(),
    }));

  it('should create checkpoints with unique IDs', () => {
    const store = new CheckpointStore();
    const messages = createMessages(3);

    const cp1 = store.createCheckpoint('thread1', messages);
    const cp2 = store.createCheckpoint('thread1', messages);

    expect(cp1.id).not.toBe(cp2.id);
    expect(cp1.id).toContain('ckpt_');
  });

  it('should retrieve checkpoint by ID', () => {
    const store = new CheckpointStore();
    const messages = createMessages(2);

    const checkpoint = store.createCheckpoint('thread1', messages, 'test');
    const retrieved = store.getCheckpoint(checkpoint.id);

    expect(retrieved).toBeDefined();
    expect(retrieved?.label).toBe('test');
    expect(retrieved?.messages).toHaveLength(2);
  });

  it('should retrieve checkpoint by label', () => {
    const store = new CheckpointStore();
    store.createCheckpoint('thread1', [], 'start');
    store.createCheckpoint('thread1', [], 'middle');

    const found = store.getByLabel('start');
    expect(found?.label).toBe('start');
  });

  it('should get all checkpoints for a thread sorted by time', () => {
    const store = new CheckpointStore();

    store.createCheckpoint('thread1', [], 'first');
    store.createCheckpoint('thread2', [], 'other');
    store.createCheckpoint('thread1', [], 'second');

    const thread1Checkpoints = store.getThreadCheckpoints('thread1');
    expect(thread1Checkpoints).toHaveLength(2);
    expect(thread1Checkpoints[0].label).toBe('first');
  });

  it('should prune old checkpoints per thread', () => {
    const store = new CheckpointStore();

    // Create 5 checkpoints for thread1
    for (let i = 0; i < 5; i++) {
      store.createCheckpoint('thread1', [], `cp${i}`);
    }
    // Create 3 for thread2
    for (let i = 0; i < 3; i++) {
      store.createCheckpoint('thread2', [], `cp${i}`);
    }

    const pruned = store.pruneOldCheckpoints(2);

    expect(pruned).toBe(4); // 3 from thread1 + 1 from thread2
    expect(store.getThreadCheckpoints('thread1')).toHaveLength(2);
    expect(store.getThreadCheckpoints('thread2')).toHaveLength(2);
  });

  it('should delete checkpoints', () => {
    const store = new CheckpointStore();
    const cp = store.createCheckpoint('thread1', []);

    expect(store.deleteCheckpoint(cp.id)).toBe(true);
    expect(store.getCheckpoint(cp.id)).toBeUndefined();
  });
});
