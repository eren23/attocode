/**
 * Lock-free monotonic counter for generating unique submission identifiers.
 * Uses bigint for virtually unlimited range without overflow concerns.
 */
export class AtomicCounter {
  private counter: bigint;

  /**
   * Creates a new AtomicCounter instance.
   * @param initial - Optional initial value (default: 0n)
   */
  constructor(initial: bigint = 0n) {
    this.counter = initial;
  }

  /**
   * Generates the next unique submission ID.
   * Increments the internal counter and returns an ID in format `sub-{base36}`.
   * @returns Unique string ID (e.g., 'sub-0', 'sub-1', 'sub-a', 'sub-1s')
   */
  next(): string {
    const id = this.counter;
    this.counter += 1n;
    return `sub-${id.toString(36)}`;
  }

  /**
   * Returns the current counter value without incrementing.
   * Useful for inspection and debugging.
   * @returns Current counter value as bigint
   */
  current(): bigint {
    return this.counter;
  }

  /**
   * Resets the counter to a specified value or zero.
   * Primarily useful for testing scenarios.
   * @param value - Optional value to reset to (default: 0n)
   */
  reset(value: bigint = 0n): void {
    this.counter = value;
  }
}

/**
 * Global singleton counter instance for generating unique submission IDs
 * across the application.
 */
export const globalCounter = new AtomicCounter();
