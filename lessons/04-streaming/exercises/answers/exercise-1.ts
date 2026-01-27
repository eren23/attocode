/**
 * Exercise 4: Streaming Buffer - REFERENCE SOLUTION
 */

// =============================================================================
// SOLUTION: LineBuffer
// =============================================================================

export class LineBuffer implements AsyncIterable<string> {
  private pending: string = '';
  private lines: string[] = [];
  private ended: boolean = false;
  private waitingResolve: (() => void) | null = null;

  push(chunk: string): void {
    // Append chunk to pending buffer
    this.pending += chunk;

    // Split by newlines
    const parts = this.pending.split('\n');

    // All but the last part are complete lines
    for (let i = 0; i < parts.length - 1; i++) {
      this.lines.push(parts[i]);
    }

    // Last part is the new pending (incomplete line)
    this.pending = parts[parts.length - 1];

    // Wake up waiting consumer if any
    if (this.waitingResolve && this.lines.length > 0) {
      const resolve = this.waitingResolve;
      this.waitingResolve = null;
      resolve();
    }
  }

  end(): void {
    this.ended = true;

    // Emit any remaining pending data as final line
    if (this.pending.length > 0) {
      this.lines.push(this.pending);
      this.pending = '';
    }

    // Wake up waiting consumer
    if (this.waitingResolve) {
      const resolve = this.waitingResolve;
      this.waitingResolve = null;
      resolve();
    }
  }

  async *[Symbol.asyncIterator](): AsyncIterator<string> {
    while (true) {
      // Yield all available lines
      while (this.lines.length > 0) {
        yield this.lines.shift()!;
      }

      // If ended and no more lines, stop
      if (this.ended) {
        return;
      }

      // Wait for more data
      await new Promise<void>(resolve => {
        this.waitingResolve = resolve;
      });
    }
  }
}

// =============================================================================
// HELPER
// =============================================================================

export async function collectLines(buffer: AsyncIterable<string>): Promise<string[]> {
  const lines: string[] = [];
  for await (const line of buffer) {
    lines.push(line);
  }
  return lines;
}
