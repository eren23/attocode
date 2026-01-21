/**
 * Exercise 13: Session Manager
 * Implement session management for client-server communication.
 */

export interface SessionConfig {
  timeoutMs: number;
}

export type SessionState = 'active' | 'idle' | 'terminated';

export interface Session {
  id: string;
  state: SessionState;
  context: Record<string, unknown>;
  createdAt: number;
  lastActivityAt: number;
}

/**
 * TODO: Implement SessionManager
 *
 * 1. create(context): Create new session with unique ID
 * 2. get(id): Get session by ID
 * 3. update(id, updates): Update session context/activity
 * 4. terminate(id): Mark session as terminated
 * 5. cleanup(): Remove expired sessions
 */
export class SessionManager {
  // TODO: private sessions: Map<string, Session> = new Map();
  // TODO: private config: SessionConfig;

  constructor(_config: SessionConfig) {
    throw new Error('TODO: Implement constructor');
  }

  create(_context: Record<string, unknown>): Session {
    // TODO: Generate unique ID, create session
    throw new Error('TODO: Implement create');
  }

  get(_id: string): Session | undefined {
    throw new Error('TODO: Implement get');
  }

  update(_id: string, _updates: Partial<Pick<Session, 'context' | 'lastActivityAt'>>): boolean {
    throw new Error('TODO: Implement update');
  }

  terminate(_id: string): boolean {
    throw new Error('TODO: Implement terminate');
  }

  cleanup(): number {
    // TODO: Remove sessions that have exceeded timeout
    throw new Error('TODO: Implement cleanup');
  }

  getActiveSessions(): Session[] {
    throw new Error('TODO: Implement getActiveSessions');
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 15);
}
