/**
 * Exercise Tests: Lesson 10 - Hook Registration
 */
import { describe, it, expect, vi } from 'vitest';
import { HookRegistry } from './exercises/answers/exercise-1.js';

describe('HookRegistry', () => {
  it('should register and execute hooks', async () => {
    const registry = new HookRegistry();
    const handler = vi.fn().mockResolvedValue(undefined);

    registry.register('test', handler, 10);
    await registry.execute('event', { foo: 'bar' });

    expect(handler).toHaveBeenCalled();
  });

  it('should execute hooks in priority order', async () => {
    const registry = new HookRegistry();
    const order: number[] = [];

    registry.register('low', async () => { order.push(3); }, 30);
    registry.register('high', async () => { order.push(1); }, 10);
    registry.register('mid', async () => { order.push(2); }, 20);

    await registry.execute('test', {});

    expect(order).toEqual([1, 2, 3]);
  });

  it('should block event when hook returns false', async () => {
    const registry = new HookRegistry();

    registry.register('blocker', async () => false, 10);
    registry.register('after', async () => {}, 20);

    const event = await registry.execute('test', {});

    expect(event.blocked).toBe(true);
  });

  it('should unregister hooks', () => {
    const registry = new HookRegistry();
    registry.register('test', async () => {}, 10);

    expect(registry.unregister('test')).toBe(true);
    expect(registry.getHooks()).toHaveLength(0);
  });

  it('should return all hooks', () => {
    const registry = new HookRegistry();
    registry.register('a', async () => {}, 10);
    registry.register('b', async () => {}, 20);

    expect(registry.getHooks()).toHaveLength(2);
  });
});
