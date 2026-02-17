/**
 * Trick T: Serialization Diversity
 *
 * Introduces controlled variation in how context is serialized to prevent
 * few-shot pattern collapse and over-fitting to specific formats.
 *
 * Problem: When tool results and context are always serialized identically,
 * the model may develop rigid patterns - expecting certain fields in certain
 * orders, or failing when encountering slight variations.
 *
 * Solution: Introduce controlled diversity in serialization:
 * - Vary key ordering
 * - Use different quote styles
 * - Alternate between compact and pretty printing
 * - Randomize array orderings where semantically equivalent
 *
 * This helps the model stay robust to format variations.
 *
 * @example
 * ```typescript
 * import { createDiverseSerializer, serializeWithVariation } from './serialization-diversity';
 *
 * const serializer = createDiverseSerializer({
 *   variationLevel: 0.3,  // 30% variation
 *   preserveSemantics: true,
 * });
 *
 * // Each call may produce slightly different (but equivalent) output
 * const json1 = serializer.serialize(data);
 * const json2 = serializer.serialize(data);
 * // json1 and json2 are semantically equivalent but may differ in format
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for serialization diversity.
 */
export interface DiverseSerializerConfig {
  /** Level of variation (0-1). Higher = more variation. Default: 0.3 */
  variationLevel?: number;

  /** Whether to preserve semantic meaning (never break validity) */
  preserveSemantics?: boolean;

  /** Whether to vary key ordering */
  varyKeyOrder?: boolean;

  /** Whether to vary indentation */
  varyIndentation?: boolean;

  /** Whether to vary spacing */
  varySpacing?: boolean;

  /** Whether to sometimes omit null/undefined values */
  omitNullish?: boolean;

  /** Whether to vary array element formatting */
  varyArrayFormat?: boolean;

  /** Seed for deterministic variation (useful for testing) */
  seed?: number;
}

/**
 * Serialization style options.
 */
export interface SerializationStyle {
  /** Indentation: 0 (compact), 2, 4, or 'tab' */
  indent: number | 'tab';

  /** Whether to sort keys */
  sortKeys: boolean;

  /** Key sort order: 'asc', 'desc', or 'random' */
  keySortOrder: 'asc' | 'desc' | 'random';

  /** Whether to include trailing commas (for template literals) */
  trailingComma: boolean;

  /** Space after colons */
  spaceAfterColon: boolean;

  /** Space inside brackets/braces */
  spaceInsideBrackets: boolean;

  /** Whether to omit null values */
  omitNull: boolean;

  /** Whether to omit undefined values */
  omitUndefined: boolean;

  /** Array style: 'compact', 'expanded', 'mixed' */
  arrayStyle: 'compact' | 'expanded' | 'mixed';
}

/**
 * Statistics about serialization diversity.
 */
export interface DiversityStats {
  /** Total serializations performed */
  totalSerializations: number;

  /** Distribution of styles used */
  styleDistribution: Map<string, number>;

  /** Average variation score */
  averageVariation: number;
}

/**
 * Events emitted by diverse serializer.
 */
export type SerializerEvent =
  | { type: 'serialization.performed'; style: Partial<SerializationStyle>; variation: number }
  | { type: 'style.changed'; newStyle: Partial<SerializationStyle> };

export type SerializerEventListener = (event: SerializerEvent) => void;

// =============================================================================
// RANDOM UTILITIES
// =============================================================================

/**
 * Simple seeded random number generator.
 */
class SeededRandom {
  private seed: number;

  constructor(seed?: number) {
    this.seed = seed ?? Date.now();
  }

  /**
   * Get next random number between 0 and 1.
   */
  next(): number {
    this.seed = (this.seed * 1103515245 + 12345) & 0x7fffffff;
    return this.seed / 0x7fffffff;
  }

  /**
   * Get random integer in range [min, max].
   */
  nextInt(min: number, max: number): number {
    return Math.floor(this.next() * (max - min + 1)) + min;
  }

  /**
   * Get random boolean with given probability.
   */
  nextBool(probability: number = 0.5): boolean {
    return this.next() < probability;
  }

  /**
   * Shuffle array in place.
   */
  shuffle<T>(array: T[]): T[] {
    for (let i = array.length - 1; i > 0; i--) {
      const j = this.nextInt(0, i);
      [array[i], array[j]] = [array[j], array[i]];
    }
    return array;
  }

  /**
   * Pick random element from array.
   */
  pick<T>(array: T[]): T {
    return array[this.nextInt(0, array.length - 1)];
  }
}

// =============================================================================
// DIVERSE SERIALIZER
// =============================================================================

/**
 * Serializer that introduces controlled variation.
 */
export class DiverseSerializer {
  private config: Required<DiverseSerializerConfig>;
  private random: SeededRandom;
  private stats = {
    totalSerializations: 0,
    styleDistribution: new Map<string, number>(),
  };
  private listeners: SerializerEventListener[] = [];

  constructor(config: DiverseSerializerConfig = {}) {
    this.config = {
      variationLevel: config.variationLevel ?? 0.3,
      preserveSemantics: config.preserveSemantics ?? true,
      varyKeyOrder: config.varyKeyOrder ?? true,
      varyIndentation: config.varyIndentation ?? true,
      varySpacing: config.varySpacing ?? true,
      omitNullish: config.omitNullish ?? true,
      varyArrayFormat: config.varyArrayFormat ?? true,
      seed: config.seed ?? Date.now(),
    };
    this.random = new SeededRandom(this.config.seed);
  }

  /**
   * Serialize data with controlled variation.
   */
  serialize(data: unknown): string {
    const style = this.generateStyle();
    const result = this.serializeWithStyle(data, style);

    this.stats.totalSerializations++;
    const styleKey = this.getStyleKey(style);
    this.stats.styleDistribution.set(
      styleKey,
      (this.stats.styleDistribution.get(styleKey) || 0) + 1,
    );

    const variation = this.calculateVariation(style);
    this.emit({ type: 'serialization.performed', style, variation });

    return result;
  }

  /**
   * Serialize with a specific style.
   */
  serializeWithStyle(data: unknown, style: Partial<SerializationStyle>): string {
    const fullStyle = this.mergeWithDefaults(style);
    return this.doSerialize(data, fullStyle, 0);
  }

  /**
   * Generate a random style based on variation level.
   */
  generateStyle(): Partial<SerializationStyle> {
    const level = this.config.variationLevel;
    const style: Partial<SerializationStyle> = {};

    // Indentation
    if (this.config.varyIndentation && this.random.nextBool(level)) {
      style.indent = this.random.pick([0, 2, 4, 'tab']);
    }

    // Key ordering
    if (this.config.varyKeyOrder && this.random.nextBool(level)) {
      style.sortKeys = this.random.nextBool(0.5);
      style.keySortOrder = this.random.pick(['asc', 'desc', 'random']);
    }

    // Spacing
    if (this.config.varySpacing && this.random.nextBool(level)) {
      style.spaceAfterColon = this.random.nextBool(0.8);
      style.spaceInsideBrackets = this.random.nextBool(0.2);
    }

    // Null handling
    if (this.config.omitNullish && this.random.nextBool(level * 0.5)) {
      style.omitNull = this.random.nextBool(0.5);
      style.omitUndefined = true; // Always omit undefined in JSON
    }

    // Array formatting
    if (this.config.varyArrayFormat && this.random.nextBool(level)) {
      style.arrayStyle = this.random.pick(['compact', 'expanded', 'mixed']);
    }

    return style;
  }

  /**
   * Get a consistent style for deterministic output.
   */
  getConsistentStyle(): SerializationStyle {
    return {
      indent: 2,
      sortKeys: true,
      keySortOrder: 'asc',
      trailingComma: false,
      spaceAfterColon: true,
      spaceInsideBrackets: false,
      omitNull: false,
      omitUndefined: true,
      arrayStyle: 'expanded',
    };
  }

  /**
   * Get serialization statistics.
   */
  getStats(): DiversityStats {
    const variations: number[] = [];
    for (const [styleKey, count] of this.stats.styleDistribution) {
      const style = this.parseStyleKey(styleKey);
      variations.push(...Array(count).fill(this.calculateVariation(style)));
    }

    return {
      totalSerializations: this.stats.totalSerializations,
      styleDistribution: new Map(this.stats.styleDistribution),
      averageVariation:
        variations.length > 0 ? variations.reduce((a, b) => a + b, 0) / variations.length : 0,
    };
  }

  /**
   * Reset statistics.
   */
  resetStats(): void {
    this.stats.totalSerializations = 0;
    this.stats.styleDistribution.clear();
  }

  /**
   * Update variation level.
   */
  setVariationLevel(level: number): void {
    this.config.variationLevel = Math.max(0, Math.min(1, level));
  }

  /**
   * Subscribe to events.
   */
  on(listener: SerializerEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // Internal methods

  private mergeWithDefaults(style: Partial<SerializationStyle>): SerializationStyle {
    return {
      indent: style.indent ?? 2,
      sortKeys: style.sortKeys ?? true,
      keySortOrder: style.keySortOrder ?? 'asc',
      trailingComma: style.trailingComma ?? false,
      spaceAfterColon: style.spaceAfterColon ?? true,
      spaceInsideBrackets: style.spaceInsideBrackets ?? false,
      omitNull: style.omitNull ?? false,
      omitUndefined: style.omitUndefined ?? true,
      arrayStyle: style.arrayStyle ?? 'expanded',
    };
  }

  private doSerialize(data: unknown, style: SerializationStyle, depth: number): string {
    if (data === null) {
      return style.omitNull ? '' : 'null';
    }

    if (data === undefined) {
      return ''; // Always omit undefined in JSON
    }

    if (typeof data === 'string') {
      return JSON.stringify(data);
    }

    if (typeof data === 'number' || typeof data === 'boolean') {
      return String(data);
    }

    if (Array.isArray(data)) {
      return this.serializeArray(data, style, depth);
    }

    if (typeof data === 'object') {
      return this.serializeObject(data as Record<string, unknown>, style, depth);
    }

    return JSON.stringify(data);
  }

  private serializeArray(arr: unknown[], style: SerializationStyle, depth: number): string {
    if (arr.length === 0) {
      return style.spaceInsideBrackets ? '[ ]' : '[]';
    }

    const indent = this.getIndentString(style.indent);
    const newline = style.indent === 0 ? '' : '\n';
    const currentIndent = indent.repeat(depth);
    const itemIndent = indent.repeat(depth + 1);

    // Determine if compact
    const useCompact =
      style.arrayStyle === 'compact' ||
      (style.arrayStyle === 'mixed' &&
        arr.length <= 3 &&
        arr.every((item) => typeof item !== 'object' || item === null));

    if (useCompact || style.indent === 0) {
      const items = arr.map((item) => this.doSerialize(item, style, depth + 1)).filter(Boolean);
      const inner = items.join(', ');
      return style.spaceInsideBrackets ? `[ ${inner} ]` : `[${inner}]`;
    }

    const items = arr
      .map((item) => this.doSerialize(item, style, depth + 1))
      .filter(Boolean)
      .map((item) => `${itemIndent}${item}`);

    return `[${newline}${items.join(`,${newline}`)}${newline}${currentIndent}]`;
  }

  private serializeObject(
    obj: Record<string, unknown>,
    style: SerializationStyle,
    depth: number,
  ): string {
    let keys = Object.keys(obj);

    // Filter keys based on style
    keys = keys.filter((key) => {
      const value = obj[key];
      if (value === undefined) return false;
      if (value === null && style.omitNull) return false;
      return true;
    });

    if (keys.length === 0) {
      return style.spaceInsideBrackets ? '{ }' : '{}';
    }

    // Sort keys based on style
    if (style.sortKeys) {
      if (style.keySortOrder === 'random') {
        this.random.shuffle(keys);
      } else {
        keys.sort();
        if (style.keySortOrder === 'desc') {
          keys.reverse();
        }
      }
    }

    const indent = this.getIndentString(style.indent);
    const newline = style.indent === 0 ? '' : '\n';
    const currentIndent = indent.repeat(depth);
    const propIndent = indent.repeat(depth + 1);
    const colonSpace = style.spaceAfterColon ? ' ' : '';

    if (style.indent === 0) {
      const pairs = keys.map((key) => {
        const value = this.doSerialize(obj[key], style, depth + 1);
        return `${JSON.stringify(key)}:${colonSpace}${value}`;
      });
      return `{${pairs.join(',')}}`;
    }

    const pairs = keys.map((key) => {
      const value = this.doSerialize(obj[key], style, depth + 1);
      return `${propIndent}${JSON.stringify(key)}:${colonSpace}${value}`;
    });

    return `{${newline}${pairs.join(`,${newline}`)}${newline}${currentIndent}}`;
  }

  private getIndentString(indent: number | 'tab'): string {
    if (indent === 'tab') return '\t';
    return ' '.repeat(indent);
  }

  private getStyleKey(style: Partial<SerializationStyle>): string {
    return `${style.indent ?? 2}-${style.sortKeys ?? true}-${style.keySortOrder ?? 'asc'}`;
  }

  private parseStyleKey(key: string): Partial<SerializationStyle> {
    const [indent, sortKeys, keySortOrder] = key.split('-');
    return {
      indent: indent === 'tab' ? 'tab' : parseInt(indent, 10),
      sortKeys: sortKeys === 'true',
      keySortOrder: keySortOrder as 'asc' | 'desc' | 'random',
    };
  }

  private calculateVariation(style: Partial<SerializationStyle>): number {
    let variation = 0;
    const defaults = this.getConsistentStyle();

    if (style.indent !== undefined && style.indent !== defaults.indent) variation += 0.2;
    if (style.sortKeys !== undefined && style.sortKeys !== defaults.sortKeys) variation += 0.2;
    if (style.keySortOrder !== undefined && style.keySortOrder !== defaults.keySortOrder)
      variation += 0.2;
    if (style.spaceAfterColon !== undefined && style.spaceAfterColon !== defaults.spaceAfterColon)
      variation += 0.1;
    if (style.omitNull !== undefined && style.omitNull !== defaults.omitNull) variation += 0.1;
    if (style.arrayStyle !== undefined && style.arrayStyle !== defaults.arrayStyle)
      variation += 0.2;

    return Math.min(1, variation);
  }

  private emit(event: SerializerEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a diverse serializer.
 *
 * @example
 * ```typescript
 * const serializer = createDiverseSerializer({
 *   variationLevel: 0.3,
 *   preserveSemantics: true,
 * });
 *
 * // Serialize tool results with variation
 * const result1 = serializer.serialize({ files: ['a.ts', 'b.ts'], count: 2 });
 * const result2 = serializer.serialize({ files: ['a.ts', 'b.ts'], count: 2 });
 *
 * // Results are semantically equivalent but may differ in format:
 * // result1: {"count": 2, "files": ["a.ts", "b.ts"]}
 * // result2: {"files": ["a.ts", "b.ts"], "count": 2}
 * ```
 */
export function createDiverseSerializer(config: DiverseSerializerConfig = {}): DiverseSerializer {
  return new DiverseSerializer(config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Quick helper to serialize with variation.
 */
export function serializeWithVariation(data: unknown, variationLevel: number = 0.3): string {
  const serializer = createDiverseSerializer({ variationLevel });
  return serializer.serialize(data);
}

/**
 * Generate multiple serializations of the same data.
 * Useful for training data or testing robustness.
 */
export function generateVariations(
  data: unknown,
  count: number,
  variationLevel: number = 0.5,
): string[] {
  const serializer = createDiverseSerializer({ variationLevel });
  const results: string[] = [];

  for (let i = 0; i < count; i++) {
    results.push(serializer.serialize(data));
  }

  return results;
}

/**
 * Apply diversity to tool call arguments.
 */
export function diversifyToolArgs(
  args: Record<string, unknown>,
  variationLevel: number = 0.3,
): string {
  const serializer = createDiverseSerializer({
    variationLevel,
    preserveSemantics: true,
  });
  return serializer.serialize(args);
}

/**
 * Apply diversity to tool results.
 */
export function diversifyToolResult(result: unknown, variationLevel: number = 0.3): string {
  const serializer = createDiverseSerializer({
    variationLevel,
    preserveSemantics: true,
    varyArrayFormat: true,
  });
  return serializer.serialize(result);
}

/**
 * Format diversity stats for display.
 */
export function formatDiversityStats(stats: DiversityStats): string {
  const lines = [
    `Serialization Diversity Statistics:`,
    `  Total serializations: ${stats.totalSerializations}`,
    `  Average variation: ${(stats.averageVariation * 100).toFixed(1)}%`,
    '',
    '  Style distribution:',
  ];

  for (const [style, count] of stats.styleDistribution) {
    const percent = ((count / stats.totalSerializations) * 100).toFixed(1);
    lines.push(`    ${style}: ${count} (${percent}%)`);
  }

  return lines.join('\n');
}

/**
 * Validate that two serializations are semantically equivalent.
 */
export function areSemanticEquivalent(json1: string, json2: string): boolean {
  try {
    const obj1 = JSON.parse(json1);
    const obj2 = JSON.parse(json2);
    return (
      JSON.stringify(obj1, Object.keys(obj1).sort()) ===
      JSON.stringify(obj2, Object.keys(obj2).sort())
    );
  } catch {
    return false;
  }
}
