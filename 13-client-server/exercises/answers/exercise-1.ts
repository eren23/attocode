/**
 * Exercise 13: Session Manager - REFERENCE SOLUTION
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

export class SessionManager {
  private sessions: Map<string, Session> = new Map();
  private config: SessionConfig;

  constructor(config: SessionConfig) {
    this.config = config;
  }

  create(context: Record<string, unknown>): Session {
    const now = Date.now();
    const session: Session = {
      id: generateId(),
      state: 'active',
      context,
      createdAt: now,
      lastActivityAt: now,
    };
    this.sessions.set(session.id, session);
    return session;
  }

  get(id: string): Session | undefined {
    return this.sessions.get(id);
  }

  update(id: string, updates: Partial<Pick<Session, 'context' | 'lastActivityAt'>>): boolean {
    const session = this.sessions.get(id);
    if (!session || session.state === 'terminated') return false;

    if (updates.context) {
      session.context = { ...session.context, ...updates.context };
    }
    session.lastActivityAt = updates.lastActivityAt ?? Date.now();
    session.state = 'active';

    return true;
  }

  terminate(id: string): boolean {
    const session = this.sessions.get(id);
    if (!session) return false;
    session.state = 'terminated';
    return true;
  }

  cleanup(): number {
    const now = Date.now();
    let removed = 0;

    for (const [id, session] of this.sessions) {
      const expired = now - session.lastActivityAt > this.config.timeoutMs;
      if (session.state === 'terminated' || expired) {
        this.sessions.delete(id);
        removed++;
      }
    }

    return removed;
  }

  getActiveSessions(): Session[] {
    return Array.from(this.sessions.values())
      .filter(s => s.state === 'active');
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 15);
}
