/**
 * Agent Harness
 *
 * Top-level orchestrator for agent sessions, subagent spawning,
 * and resource management.
 */

import { Session, createSession } from './session.js';
import { SubagentSpawner, createSubagentSpawner, type SubagentConfig, type SubagentResult, type ParallelTask } from './subagent.js';
import { EventBus, globalEventBus, sessionStartEvent, sessionEndEvent, type AgentEvent } from './communication.js';
import { FilesystemContextStorage } from '../context/filesystem-context.js';
import type { LLMProviderWithTools } from '../../02-provider-abstraction/types.js';
import type { ToolRegistry } from '../../03-tool-system/registry.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Harness configuration.
 */
export interface HarnessConfig {
  /** LLM provider */
  provider: LLMProviderWithTools;
  /** Tool registry */
  toolRegistry: ToolRegistry;
  /** Default model */
  model?: string;
  /** Storage directory for sessions */
  storageDir?: string;
  /** Maximum concurrent subagents */
  maxConcurrentSubagents?: number;
  /** Default subagent timeout */
  subagentTimeout?: number;
  /** Event bus (uses global if not provided) */
  eventBus?: EventBus;
}

// =============================================================================
// AGENT HARNESS
// =============================================================================

/**
 * Central orchestrator for agent operations.
 *
 * The harness provides:
 * - Session lifecycle management
 * - Subagent spawning and coordination
 * - Resource cleanup
 * - Event broadcasting
 *
 * @example
 * ```typescript
 * const harness = new AgentHarness({
 *   provider,
 *   toolRegistry,
 *   storageDir: './.agent-sessions',
 * });
 *
 * // Create a new session
 * const session = await harness.createSession();
 *
 * // Spawn a subagent
 * const result = await harness.spawnSubagent(session, {
 *   task: 'Find all TODO comments in the codebase',
 * });
 *
 * // Run parallel tasks
 * const results = await harness.runParallel(session, [
 *   { id: 'todos', config: { task: 'Find TODOs' } },
 *   { id: 'tests', config: { task: 'List test files' } },
 * ]);
 *
 * // Clean up
 * await harness.cleanup(session.id);
 * ```
 */
export class AgentHarness {
  private config: Omit<Required<Omit<HarnessConfig, 'eventBus' | 'model'>>, never> & { eventBus: EventBus; model?: string };
  private sessions: Map<string, Session> = new Map();
  private spawners: Map<string, SubagentSpawner> = new Map();
  private storage: FilesystemContextStorage;

  constructor(config: HarnessConfig) {
    this.config = {
      provider: config.provider,
      toolRegistry: config.toolRegistry,
      model: config.model ?? undefined,
      storageDir: config.storageDir ?? './.agent-sessions',
      maxConcurrentSubagents: config.maxConcurrentSubagents ?? 5,
      subagentTimeout: config.subagentTimeout ?? 60000,
      eventBus: config.eventBus ?? globalEventBus,
    };

    this.storage = new FilesystemContextStorage(this.config.storageDir);
  }

  // ===========================================================================
  // SESSION MANAGEMENT
  // ===========================================================================

  /**
   * Create a new session.
   */
  async createSession(sessionId?: string): Promise<Session> {
    const session = createSession({
      id: sessionId,
      provider: this.config.provider,
      toolRegistry: this.config.toolRegistry,
      model: this.config.model,
      storageDir: this.config.storageDir,
    });

    await session.initialize();
    this.sessions.set(session.id, session);

    // Create spawner for this session
    const spawner = createSubagentSpawner(session, {
      maxConcurrent: this.config.maxConcurrentSubagents,
      defaultTimeout: this.config.subagentTimeout,
    });
    this.spawners.set(session.id, spawner);

    // Emit event
    this.config.eventBus.emit(sessionStartEvent(session.id, false));

    return session;
  }

  /**
   * Get an existing session.
   */
  getSession(sessionId: string): Session | undefined {
    return this.sessions.get(sessionId);
  }

  /**
   * Load a session from storage.
   */
  async loadSession(sessionId: string): Promise<Session | null> {
    // Check if already loaded
    const existing = this.sessions.get(sessionId);
    if (existing) {
      return existing;
    }

    // Try to load from storage
    const session = createSession({
      id: sessionId,
      provider: this.config.provider,
      toolRegistry: this.config.toolRegistry,
      model: this.config.model,
      storageDir: this.config.storageDir,
    });

    const loaded = await session.initialize();
    if (!loaded) {
      return null;
    }

    this.sessions.set(session.id, session);

    // Create spawner
    const spawner = createSubagentSpawner(session, {
      maxConcurrent: this.config.maxConcurrentSubagents,
      defaultTimeout: this.config.subagentTimeout,
    });
    this.spawners.set(session.id, spawner);

    this.config.eventBus.emit(sessionStartEvent(session.id, false));

    return session;
  }

  /**
   * List all available sessions.
   */
  async listSessions(): Promise<Array<{
    id: string;
    active: boolean;
    messageCount: number;
    updatedAt: number;
  }>> {
    const storedSessions = await this.storage.listSessions();

    return storedSessions.map(meta => ({
      id: meta.id,
      active: this.sessions.has(meta.id),
      messageCount: meta.messageCount,
      updatedAt: meta.updatedAt,
    }));
  }

  /**
   * Clean up a session and its resources.
   */
  async cleanup(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      return;
    }

    // Cancel any active subagents
    const spawner = this.spawners.get(sessionId);
    if (spawner) {
      await spawner.cancelAll();
      this.spawners.delete(sessionId);
    }

    // Get stats before cleanup
    const stats = session.getStats();

    // Clean up session
    await session.cleanup();
    this.sessions.delete(sessionId);

    // Emit event
    this.config.eventBus.emit(sessionEndEvent(sessionId, 'completed', {
      messagesCount: stats.messagesCount,
      toolCallsCount: stats.toolCallsCount,
      totalTokens: stats.totalInputTokens + stats.totalOutputTokens,
    }));
  }

  /**
   * Clean up all sessions.
   */
  async cleanupAll(): Promise<void> {
    const sessionIds = Array.from(this.sessions.keys());
    await Promise.all(sessionIds.map(id => this.cleanup(id)));
  }

  // ===========================================================================
  // SUBAGENT OPERATIONS
  // ===========================================================================

  /**
   * Spawn a subagent for a session.
   */
  async spawnSubagent(
    session: Session,
    config: SubagentConfig
  ): Promise<SubagentResult> {
    const spawner = this.spawners.get(session.id);
    if (!spawner) {
      throw new Error(`No spawner found for session ${session.id}`);
    }

    return spawner.spawn(config);
  }

  /**
   * Run multiple tasks in parallel.
   */
  async runParallel(
    session: Session,
    tasks: ParallelTask[]
  ): Promise<Map<string, SubagentResult>> {
    const spawner = this.spawners.get(session.id);
    if (!spawner) {
      throw new Error(`No spawner found for session ${session.id}`);
    }

    return spawner.runParallel(tasks);
  }

  // ===========================================================================
  // EVENT HANDLING
  // ===========================================================================

  /**
   * Subscribe to events.
   */
  subscribe(handler: (event: AgentEvent) => void): () => void {
    return this.config.eventBus.subscribe(handler);
  }

  /**
   * Subscribe to events for a specific session.
   */
  subscribeToSession(
    sessionId: string,
    handler: (event: AgentEvent) => void
  ): () => void {
    return this.config.eventBus.subscribeToSession(sessionId, handler);
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  /**
   * Get harness statistics.
   */
  getStats(): {
    activeSessions: number;
    totalSubagents: number;
    totalTokens: number;
  } {
    let totalSubagents = 0;
    let totalTokens = 0;

    for (const session of this.sessions.values()) {
      const stats = session.getStats();
      totalSubagents += stats.subagentCount;
      totalTokens += stats.totalInputTokens + stats.totalOutputTokens;
    }

    return {
      activeSessions: this.sessions.size,
      totalSubagents,
      totalTokens,
    };
  }

  /**
   * Clean up old sessions from storage.
   */
  async cleanupOldSessions(maxAgeDays: number = 30): Promise<number> {
    return this.storage.cleanup(maxAgeDays);
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create an agent harness.
 */
export function createAgentHarness(config: HarnessConfig): AgentHarness {
  return new AgentHarness(config);
}
