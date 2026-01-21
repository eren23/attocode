/**
 * Exercise 19: Span Tracker - REFERENCE SOLUTION
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

export class SpanTracker {
  private spans: Map<string, Span> = new Map();

  startSpan(name: string, parentId?: string): Span {
    const span: Span = {
      id: generateId(),
      name,
      parentId,
      startTime: Date.now(),
      attributes: {},
      status: 'running',
    };
    this.spans.set(span.id, span);
    return span;
  }

  endSpan(spanId: string, status: 'ok' | 'error' = 'ok'): void {
    const span = this.spans.get(spanId);
    if (!span) throw new Error('Span not found');
    span.endTime = Date.now();
    span.status = status;
  }

  setAttribute(spanId: string, key: string, value: unknown): void {
    const span = this.spans.get(spanId);
    if (!span) throw new Error('Span not found');
    span.attributes[key] = value;
  }

  getSpan(spanId: string): Span | undefined {
    return this.spans.get(spanId);
  }

  getChildren(spanId: string): Span[] {
    return Array.from(this.spans.values()).filter(s => s.parentId === spanId);
  }

  getDuration(spanId: string): number | undefined {
    const span = this.spans.get(spanId);
    if (!span || !span.endTime) return undefined;
    return span.endTime - span.startTime;
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 10);
}
