/**
 * Exercise 12: Rules Merger - REFERENCE SOLUTION
 */

export interface RuleSource {
  name: string;
  rules: Record<string, unknown>;
  priority: number;
}

export class RulesMerger {
  private sources: Map<string, RuleSource> = new Map();
  private cachedMerge: Record<string, unknown> | null = null;

  addSource(name: string, rules: Record<string, unknown>, priority: number): void {
    this.sources.set(name, { name, rules, priority });
    this.cachedMerge = null;
  }

  removeSource(name: string): boolean {
    const result = this.sources.delete(name);
    if (result) this.cachedMerge = null;
    return result;
  }

  merge(): Record<string, unknown> {
    if (this.cachedMerge) return this.cachedMerge;

    const sorted = Array.from(this.sources.values())
      .sort((a, b) => a.priority - b.priority);

    let result: Record<string, unknown> = {};
    for (const source of sorted) {
      result = deepMerge(result, source.rules);
    }

    this.cachedMerge = result;
    return result;
  }

  get(path: string): unknown {
    const merged = this.merge();
    const parts = path.split('.');
    let current: unknown = merged;

    for (const part of parts) {
      if (current === null || typeof current !== 'object') return undefined;
      current = (current as Record<string, unknown>)[part];
    }

    return current;
  }

  getSources(): RuleSource[] {
    return Array.from(this.sources.values());
  }
}

export function deepMerge(target: Record<string, unknown>, source: Record<string, unknown>): Record<string, unknown> {
  const result = { ...target };
  for (const key of Object.keys(source)) {
    if (isObject(source[key]) && isObject(target[key])) {
      result[key] = deepMerge(target[key] as Record<string, unknown>, source[key] as Record<string, unknown>);
    } else {
      result[key] = source[key];
    }
  }
  return result;
}

function isObject(item: unknown): item is Record<string, unknown> {
  return item !== null && typeof item === 'object' && !Array.isArray(item);
}
