/**
 * Git Worktree Isolation Provider
 *
 * Creates isolated filesystem environments using git worktrees.
 * Each task gets its own worktree with a separate checkout, enabling
 * true parallel execution without cross-task contamination.
 *
 * Architecture:
 *   1. For each unique repo, create a bare clone (shared cache)
 *   2. Create worktree slots from the bare clone
 *   3. For each task: checkout the correct commit in an available slot
 *   4. After task: git reset --hard && git clean -fdx to recycle
 */

import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { existsSync, mkdirSync } from 'node:fs';
import { PoolManager } from './pool-manager.js';
import type {
  IsolationProvider,
  TaskDescriptor,
  TaskEnvironment,
  PoolStats,
} from './types.js';

const execFileAsync = promisify(execFile);

// =============================================================================
// TYPES
// =============================================================================

interface WorktreeSlot {
  /** Absolute path to the worktree directory */
  path: string;
  /** Repo key this worktree belongs to */
  repoKey: string;
  /** Path to the bare clone this worktree was created from */
  bareClonePath: string;
}

interface RepoCache {
  /** Repository URL */
  repoUrl: string;
  /** Path to the bare clone */
  bareClonePath: string;
  /** Set of commits that have been fetched */
  fetchedCommits: Set<string>;
}

// =============================================================================
// WORKTREE PROVIDER
// =============================================================================

export class WorktreeProvider implements IsolationProvider {
  readonly type = 'worktree' as const;

  private poolManager: PoolManager<WorktreeSlot> | null = null;
  private repoCache: Map<string, RepoCache> = new Map();
  private baseDir: string;
  private maxSlots: number;

  constructor(options: { baseDir?: string; maxSlots?: number } = {}) {
    this.baseDir = options.baseDir || path.join('/tmp', `attocode-eval-${Date.now()}`);
    this.maxSlots = options.maxSlots || 10;
  }

  // ---------------------------------------------------------------------------
  // IsolationProvider Implementation
  // ---------------------------------------------------------------------------

  async init(tasks: TaskDescriptor[]): Promise<void> {
    // Ensure base directory exists
    mkdirSync(this.baseDir, { recursive: true });

    // Identify unique repos
    const repos = new Map<string, { url: string; commits: Set<string> }>();
    for (const task of tasks) {
      if (task.repo) {
        const key = this.repoKey(task.repo);
        if (!repos.has(key)) {
          repos.set(key, { url: task.repo, commits: new Set() });
        }
        if (task.baseCommit) {
          repos.get(key)!.commits.add(task.baseCommit);
        }
      }
    }

    // Create bare clones for each unique repo
    for (const [key, { url, commits }] of repos) {
      console.log(`[WorktreeProvider] Cloning ${url} (bare)...`);
      const bareClonePath = path.join(this.baseDir, 'repos', key);
      await this.createBareClone(url, bareClonePath);

      this.repoCache.set(key, {
        repoUrl: url,
        bareClonePath,
        fetchedCommits: commits,
      });
    }

    // Initialize pool manager
    this.poolManager = new PoolManager<WorktreeSlot>({
      maxSlots: this.maxSlots,
      create: async (slotId) => this.createWorktreeSlot(slotId),
      reset: async (_slotId, resource) => this.resetWorktree(resource),
      destroy: async (_slotId, resource) => this.destroyWorktree(resource),
    });

    // Pre-warm with some worktree slots
    const warmupCount = Math.min(this.maxSlots, tasks.length);
    if (repos.size > 0) {
      console.log(`[WorktreeProvider] Pre-warming ${warmupCount} worktree slots...`);
      await this.poolManager.warmup(warmupCount);
    }

    console.log(`[WorktreeProvider] Initialized: ${repos.size} repos, ${warmupCount} slots`);
  }

  async acquire(task: TaskDescriptor): Promise<TaskEnvironment> {
    if (!this.poolManager) {
      throw new Error('WorktreeProvider not initialized. Call init() first.');
    }

    const slot = await this.poolManager.acquire();

    // If task has a repo+commit, checkout the right state
    if (task.repo && task.baseCommit) {
      const key = this.repoKey(task.repo);
      const cache = this.repoCache.get(key);

      if (cache) {
        // Ensure worktree is from the right repo
        if (slot.resource.repoKey !== key) {
          // Need to recreate this worktree from the correct bare clone
          await this.destroyWorktree(slot.resource);
          slot.resource = await this.createWorktreeSlotForRepo(slot.id, key, cache.bareClonePath);
        }

        await this.checkoutCommit(slot.resource.path, task.baseCommit);
      }
    }

    // Run setup commands
    if (task.setupCommands) {
      for (const cmd of task.setupCommands) {
        await execFileAsync('sh', ['-c', cmd], {
          cwd: slot.resource.path,
          timeout: 120000,
        });
      }
    }

    // Create setup files
    if (task.setupFiles) {
      for (const [filePath, content] of Object.entries(task.setupFiles)) {
        const fullPath = path.join(slot.resource.path, filePath);
        await fs.mkdir(path.dirname(fullPath), { recursive: true });
        await fs.writeFile(fullPath, content);
      }
    }

    // Determine the effective workspace path
    const workspacePath = task.workdir
      ? path.join(slot.resource.path, task.workdir)
      : slot.resource.path;

    return {
      slotId: slot.id,
      workspacePath,
      metadata: {
        isolationType: 'worktree',
        branch: `slot-${slot.id}`,
        createdAt: slot.createdAt,
        reuseCount: slot.reuseCount,
      },
    };
  }

  async reset(_env: TaskEnvironment): Promise<void> {
    // Reset is handled inside pool.release via the reset callback
  }

  async release(env: TaskEnvironment): Promise<void> {
    if (!this.poolManager) return;
    await this.poolManager.release(env.slotId);
  }

  async destroyAll(): Promise<void> {
    if (this.poolManager) {
      await this.poolManager.destroyAll();
      this.poolManager = null;
    }

    // Clean up base directory
    try {
      await fs.rm(this.baseDir, { recursive: true, force: true });
    } catch (err) {
      console.warn(`[WorktreeProvider] Failed to clean up ${this.baseDir}:`, err);
    }

    this.repoCache.clear();
  }

  getStats(): PoolStats {
    if (!this.poolManager) {
      return {
        totalSlots: 0,
        activeSlots: 0,
        availableSlots: 0,
        pendingAcquires: 0,
        totalAcquires: 0,
        totalResets: 0,
      };
    }
    return this.poolManager.getStats();
  }

  // ---------------------------------------------------------------------------
  // PRIVATE: Git Operations
  // ---------------------------------------------------------------------------

  private repoKey(repo: string): string {
    // Normalize repo URL to a filesystem-safe key
    // "sympy/sympy" or "https://github.com/sympy/sympy.git" → "sympy__sympy"
    return repo
      .replace(/^https?:\/\/github\.com\//, '')
      .replace(/\.git$/, '')
      .replace(/\//g, '__');
  }

  private async createBareClone(repoUrl: string, targetPath: string): Promise<void> {
    if (existsSync(targetPath)) {
      // Bare clone already exists, fetch latest
      await execFileAsync('git', ['fetch', '--all'], {
        cwd: targetPath,
        timeout: 300000,
      });
      return;
    }

    // Normalize repo URL
    const fullUrl = repoUrl.includes('://')
      ? repoUrl
      : `https://github.com/${repoUrl}.git`;

    await fs.mkdir(path.dirname(targetPath), { recursive: true });
    await execFileAsync('git', ['clone', '--bare', fullUrl, targetPath], {
      timeout: 600000, // 10 min for large repos
    });
  }

  private async createWorktreeSlot(slotId: string): Promise<WorktreeSlot> {
    // Use the first repo in the cache (default)
    const firstRepo = this.repoCache.entries().next().value;
    if (!firstRepo) {
      // No repos - create a plain directory
      const wtPath = path.join(this.baseDir, 'worktrees', slotId);
      mkdirSync(wtPath, { recursive: true });
      return { path: wtPath, repoKey: '', bareClonePath: '' };
    }

    const [key, cache] = firstRepo;
    return this.createWorktreeSlotForRepo(slotId, key, cache.bareClonePath);
  }

  private async createWorktreeSlotForRepo(
    slotId: string,
    repoKey: string,
    bareClonePath: string,
  ): Promise<WorktreeSlot> {
    const wtPath = path.join(this.baseDir, 'worktrees', slotId);

    // Remove if exists (from previous creation)
    if (existsSync(wtPath)) {
      try {
        await execFileAsync('git', ['worktree', 'remove', '--force', wtPath], {
          cwd: bareClonePath,
          timeout: 30000,
        });
      } catch {
        await fs.rm(wtPath, { recursive: true, force: true });
      }
    }

    // Create a detached worktree
    await execFileAsync(
      'git',
      ['worktree', 'add', '--detach', wtPath],
      { cwd: bareClonePath, timeout: 60000 },
    );

    return { path: wtPath, repoKey, bareClonePath };
  }

  private async checkoutCommit(worktreePath: string, commit: string): Promise<void> {
    await execFileAsync('git', ['checkout', '--force', commit], {
      cwd: worktreePath,
      timeout: 60000,
    });
  }

  private async resetWorktree(slot: WorktreeSlot): Promise<void> {
    if (!existsSync(slot.path)) return;

    // Non-git slot (golden tasks etc.) — just clear contents
    if (!slot.bareClonePath) {
      const entries = await fs.readdir(slot.path);
      for (const entry of entries) {
        await fs.rm(path.join(slot.path, entry), { recursive: true, force: true });
      }
      return;
    }

    try {
      await execFileAsync('git', ['reset', '--hard', 'HEAD'], {
        cwd: slot.path,
        timeout: 30000,
      });
      await execFileAsync('git', ['clean', '-fdx'], {
        cwd: slot.path,
        timeout: 30000,
      });
    } catch (err) {
      console.warn(`[WorktreeProvider] Reset failed for ${slot.path}:`, err);
    }
  }

  private async destroyWorktree(slot: WorktreeSlot): Promise<void> {
    if (!existsSync(slot.path)) return;

    try {
      if (slot.bareClonePath) {
        await execFileAsync('git', ['worktree', 'remove', '--force', slot.path], {
          cwd: slot.bareClonePath,
          timeout: 30000,
        });
      } else {
        await fs.rm(slot.path, { recursive: true, force: true });
      }
    } catch {
      // Force remove as fallback
      try {
        await fs.rm(slot.path, { recursive: true, force: true });
      } catch {
        // Best effort
      }
    }
  }
}
