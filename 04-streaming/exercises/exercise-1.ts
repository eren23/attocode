/**
 * Exercise 4: Streaming Buffer
 *
 * Implement a line buffer that collects streaming chunks
 * and emits complete lines via an async iterator.
 */

// =============================================================================
// TODO: Implement LineBuffer
// =============================================================================

/**
 * A buffer that collects text chunks and emits complete lines.
 *
 * Usage:
 *   const buffer = new LineBuffer();
 *   buffer.push('Hello ');
 *   buffer.push('World\n');
 *   buffer.end();
 *   for await (const line of buffer) { console.log(line); }
 *
 * TODO: Implement this class with the following:
 *
 * 1. Private state:
 *    - pending: string - Text waiting for newline
 *    - lines: string[] - Queue of complete lines ready to emit
 *    - ended: boolean - Whether end() has been called
 *    - waitingResolve: function | null - Resolver for waiting consumer
 *
 * 2. push(chunk: string):
 *    - Append chunk to pending
 *    - Split on newlines
 *    - Add complete lines to queue
 *    - Keep incomplete portion in pending
 *    - Wake up waiting consumer if any
 *
 * 3. end():
 *    - Mark as ended
 *    - Emit any remaining pending data as final line
 *    - Wake up waiting consumer
 *
 * 4. [Symbol.asyncIterator]():
 *    - Return async generator that yields lines
 *    - Wait when queue is empty (unless ended)
 *    - Stop when ended and queue is empty
 */
export class LineBuffer implements AsyncIterable<string> {
  // TODO: Add private fields
  // private pending: string = '';
  // private lines: string[] = [];
  // private ended: boolean = false;
  // private waitingResolve: (() => void) | null = null;

  /**
   * Push a chunk of text into the buffer.
   * Complete lines will be queued for emission.
   */
  push(chunk: string): void {
    // TODO: Implement push
    // 1. Append chunk to pending
    // 2. Split pending by newlines
    // 3. All but last segment are complete lines - add to queue
    // 4. Last segment becomes new pending
    // 5. If there's a waiting consumer, wake them up
    throw new Error('TODO: Implement push');
  }

  /**
   * Signal that no more chunks will be pushed.
   * Any remaining buffered data will be emitted.
   */
  end(): void {
    // TODO: Implement end
    // 1. Mark as ended
    // 2. If there's pending data, add it as final line
    // 3. Clear pending
    // 4. Wake up waiting consumer
    throw new Error('TODO: Implement end');
  }

  /**
   * Async iterator that yields complete lines.
   */
  async *[Symbol.asyncIterator](): AsyncIterator<string> {
    // TODO: Implement async generator
    // while (true) {
    //   // If we have lines, yield them
    //   while (this.lines.length > 0) {
    //     yield this.lines.shift()!;
    //   }
    //
    //   // If ended and no more lines, stop
    //   if (this.ended) {
    //     return;
    //   }
    //
    //   // Wait for more data
    //   await new Promise<void>(resolve => {
    //     this.waitingResolve = resolve;
    //   });
    // }
    throw new Error('TODO: Implement async iterator');
  }
}

// =============================================================================
// HELPER: Collect all lines from a buffer (for testing)
// =============================================================================

export async function collectLines(buffer: AsyncIterable<string>): Promise<string[]> {
  const lines: string[] = [];
  for await (const line of buffer) {
    lines.push(line);
  }
  return lines;
}
