/**
 * Exercise 19: Span Tracker
 * Implement distributed tracing with spans.
 */

export interface Span {
  id: string;
  name: string;
  parentId?: string;
  startTime: number;
  endTime?: number;
  attributes: Record<string, unknown>;
  status: 'running' | 'ok' | 'error';
}

/**
 * TODO: Implement SpanTracker
 */
export class SpanTracker {
  private spans: Map<string, Span> = new Map();

  startSpan(_name: string, _parentId?: string): Span {
    throw new Error('TODO: Implement startSpan');
  }

  endSpan(_spanId: string, _status?: 'ok' | 'error'): void {
    throw new Error('TODO: Implement endSpan');
  }

  setAttribute(_spanId: string, _key: string, _value: unknown): void {
    throw new Error('TODO: Implement setAttribute');
  }

  getSpan(_spanId: string): Span | undefined {
    throw new Error('TODO: Implement getSpan');
  }

  getChildren(_spanId: string): Span[] {
    throw new Error('TODO: Implement getChildren');
  }

  getDuration(_spanId: string): number | undefined {
    throw new Error('TODO: Implement getDuration');
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 10);
}
