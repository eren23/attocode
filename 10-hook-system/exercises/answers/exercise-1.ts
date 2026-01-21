/**
 * Exercise 10: Hook Registration - REFERENCE SOLUTION
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

export class HookRegistry {
  private hooks: Map<string, Hook> = new Map();

  register<T>(name: string, handler: HookHandler<T>, priority: number = 10): void {
    this.hooks.set(name, { name, handler: handler as HookHandler, priority });
  }

  unregister(name: string): boolean {
    return this.hooks.delete(name);
  }

  async execute(eventType: string, data: Record<string, unknown>): Promise<HookEvent> {
    const event: HookEvent = { type: eventType, data, blocked: false };

    // Sort by priority (lower = higher priority)
    const sortedHooks = Array.from(this.hooks.values())
      .sort((a, b) => a.priority - b.priority);

    for (const hook of sortedHooks) {
      const result = await hook.handler(event);
      if (result === false) {
        event.blocked = true;
        break;
      }
    }

    return event;
  }

  getHooks(): Hook[] {
    return Array.from(this.hooks.values());
  }

  clear(): void {
    this.hooks.clear();
  }
}
