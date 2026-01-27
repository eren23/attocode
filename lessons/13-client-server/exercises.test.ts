/**
 * Exercise Tests: Lesson 13 - Session Manager
 */
import { describe, it, expect } from 'vitest';
import { SessionManager } from './exercises/answers/exercise-1.js';

describe('SessionManager', () => {
  it('should create sessions with unique IDs', () => {
    const manager = new SessionManager({ timeoutMs: 30000 });
    const s1 = manager.create({ user: 'a' });
    const s2 = manager.create({ user: 'b' });

    expect(s1.id).not.toBe(s2.id);
    expect(s1.state).toBe('active');
  });

  it('should get session by ID', () => {
    const manager = new SessionManager({ timeoutMs: 30000 });
    const session = manager.create({ data: 'test' });

    expect(manager.get(session.id)).toBe(session);
    expect(manager.get('nonexistent')).toBeUndefined();
  });

  it('should update session context', () => {
    const manager = new SessionManager({ timeoutMs: 30000 });
    const session = manager.create({ count: 1 });

    manager.update(session.id, { context: { count: 2 } });

    expect(manager.get(session.id)?.context.count).toBe(2);
  });

  it('should terminate sessions', () => {
    const manager = new SessionManager({ timeoutMs: 30000 });
    const session = manager.create({});

    manager.terminate(session.id);

    expect(manager.get(session.id)?.state).toBe('terminated');
  });

  it('should not update terminated sessions', () => {
    const manager = new SessionManager({ timeoutMs: 30000 });
    const session = manager.create({});
    manager.terminate(session.id);

    expect(manager.update(session.id, { context: { x: 1 } })).toBe(false);
  });

  it('should cleanup expired sessions', async () => {
    const manager = new SessionManager({ timeoutMs: 50 });
    manager.create({});

    await new Promise(r => setTimeout(r, 60));
    const removed = manager.cleanup();

    expect(removed).toBe(1);
    expect(manager.getActiveSessions()).toHaveLength(0);
  });

  it('should return active sessions only', () => {
    const manager = new SessionManager({ timeoutMs: 30000 });
    manager.create({});
    const toTerminate = manager.create({});
    manager.terminate(toTerminate.id);

    expect(manager.getActiveSessions()).toHaveLength(1);
  });
});
