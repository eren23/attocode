/**
 * Isolation Provider Factory
 *
 * Creates the appropriate isolation provider based on configuration.
 */

export type { TaskEnvironment, TaskDescriptor, IsolationProvider, IsolationType, PoolStats, BatchConfig } from './types.js';
export { PoolManager } from './pool-manager.js';
export { WorktreeProvider } from './worktree-provider.js';
export { DockerProvider } from './docker-provider.js';

import type { IsolationProvider, IsolationType } from './types.js';
import { WorktreeProvider } from './worktree-provider.js';
import { DockerProvider } from './docker-provider.js';

/**
 * No-op isolation provider for legacy sequential mode.
 * Tasks use the working directory directly without any isolation.
 */
class NoneProvider implements IsolationProvider {
  readonly type = 'none' as const;

  async init(): Promise<void> {}

  async acquire(task: { id: string; workdir?: string }) {
    return {
      slotId: `none-${task.id}`,
      workspacePath: task.workdir || process.cwd(),
      metadata: {
        isolationType: 'none' as const,
        createdAt: Date.now(),
        reuseCount: 0,
      },
    };
  }

  async reset(): Promise<void> {}
  async release(): Promise<void> {}
  async destroyAll(): Promise<void> {}

  getStats() {
    return {
      totalSlots: 1,
      activeSlots: 0,
      availableSlots: 1,
      pendingAcquires: 0,
      totalAcquires: 0,
      totalResets: 0,
    };
  }
}

/**
 * Create an isolation provider based on type.
 */
export function createIsolationProvider(
  type: IsolationType,
  options?: { baseDir?: string; maxSlots?: number },
): IsolationProvider {
  switch (type) {
    case 'worktree':
      return new WorktreeProvider(options);
    case 'docker':
      return new DockerProvider();
    case 'none':
      return new NoneProvider();
    default:
      throw new Error(`Unknown isolation type: ${type}`);
  }
}
