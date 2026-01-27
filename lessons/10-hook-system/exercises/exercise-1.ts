/**
 * Exercise 10: Hook Registration
 * Implement an event hook system with priority ordering.
 */

export interface HookHandler<T = unknown> {
  (event: T): Promise<boolean | void>;
}

export interface Hook<T = unknown> {
  name: string;
  handler: HookHandler<T>;
  priority: number;
}

export interface HookEvent {
  type: string;
  data: Record<string, unknown>;
  blocked?: boolean;
}

/**
 * TODO: Implement HookRegistry
 *
 * 1. register(name, handler, priority): Add hook
 * 2. unregister(name): Remove hook by name
 * 3. execute(eventType, data): Run all hooks in priority order
 * 4. getHooks(): Return all registered hooks
 */
export class HookRegistry {
  // TODO: private hooks: Map<string, Hook> = new Map();

  register<T>(_name: string, _handler: HookHandler<T>, _priority: number = 10): void {
    throw new Error('TODO: Implement register');
  }

  unregister(_name: string): boolean {
    throw new Error('TODO: Implement unregister');
  }

  async execute(_eventType: string, _data: Record<string, unknown>): Promise<HookEvent> {
    // TODO: Sort hooks by priority, execute in order
    // Return event with blocked=true if any hook returns false
    throw new Error('TODO: Implement execute');
  }

  getHooks(): Hook[] {
    throw new Error('TODO: Implement getHooks');
  }

  clear(): void {
    throw new Error('TODO: Implement clear');
  }
}
