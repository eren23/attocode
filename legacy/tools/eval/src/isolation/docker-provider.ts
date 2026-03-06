/**
 * Docker Session Isolation Provider (Stub)
 *
 * Placeholder for future Docker-based isolation.
 * Unlike the existing DockerSandbox (src/integrations/sandbox/docker.ts) which runs
 * `docker run --rm` per command (stateless), this provider would:
 *   - `docker create` + `docker start` once per slot (persistent session)
 *   - `docker exec` for each agent command
 *   - Mount worktrees as /workspace volumes
 */

import type {
  IsolationProvider,
  TaskDescriptor,
  TaskEnvironment,
  PoolStats,
} from './types.js';

export class DockerProvider implements IsolationProvider {
  readonly type = 'docker' as const;

  async init(_tasks: TaskDescriptor[]): Promise<void> {
    throw new Error(
      'Docker isolation is not yet implemented. Use --isolation worktree instead.\n' +
      'See: tools/eval/src/isolation/docker-provider.ts for the planned architecture.',
    );
  }

  async acquire(_task: TaskDescriptor): Promise<TaskEnvironment> {
    throw new Error('Docker isolation not implemented');
  }

  async reset(_env: TaskEnvironment): Promise<void> {
    throw new Error('Docker isolation not implemented');
  }

  async release(_env: TaskEnvironment): Promise<void> {
    throw new Error('Docker isolation not implemented');
  }

  async destroyAll(): Promise<void> {
    // No-op for stub
  }

  getStats(): PoolStats {
    return {
      totalSlots: 0,
      activeSlots: 0,
      availableSlots: 0,
      pendingAcquires: 0,
      totalAcquires: 0,
      totalResets: 0,
    };
  }
}
