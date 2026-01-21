/**
 * Exercise 12: Rules Merger
 * Implement configuration merging with priority.
 */

export interface RuleSource {
  name: string;
  rules: Record<string, unknown>;
  priority: number;
}

/**
 * TODO: Implement RulesMerger
 *
 * 1. addSource(name, rules, priority): Add rule source
 * 2. removeSource(name): Remove source
 * 3. merge(): Merge all sources by priority
 * 4. get(path): Get value at path from merged rules
 */
export class RulesMerger {
  // TODO: private sources: Map<string, RuleSource> = new Map();

  addSource(_name: string, _rules: Record<string, unknown>, _priority: number): void {
    throw new Error('TODO: Implement addSource');
  }

  removeSource(_name: string): boolean {
    throw new Error('TODO: Implement removeSource');
  }

  merge(): Record<string, unknown> {
    // TODO: Sort by priority (higher wins), deep merge
    throw new Error('TODO: Implement merge');
  }

  get(_path: string): unknown {
    // TODO: Get nested value using dot notation
    throw new Error('TODO: Implement get');
  }

  getSources(): RuleSource[] {
    throw new Error('TODO: Implement getSources');
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
