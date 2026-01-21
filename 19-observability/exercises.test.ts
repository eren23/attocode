/**
 * Exercise Tests: Lesson 19 - Span Tracker
 */
import { describe, it, expect } from 'vitest';
import { SpanTracker } from './exercises/answers/exercise-1.js';

describe('SpanTracker', () => {
  it('should start and end spans', () => {
    const tracker = new SpanTracker();
    const span = tracker.startSpan('operation');

    expect(span.status).toBe('running');
    tracker.endSpan(span.id);
    expect(tracker.getSpan(span.id)?.status).toBe('ok');
  });

  it('should track parent-child relationships', () => {
    const tracker = new SpanTracker();
    const parent = tracker.startSpan('parent');
    const child = tracker.startSpan('child', parent.id);

    expect(child.parentId).toBe(parent.id);
    expect(tracker.getChildren(parent.id)).toHaveLength(1);
  });

  it('should set attributes', () => {
    const tracker = new SpanTracker();
    const span = tracker.startSpan('test');
    tracker.setAttribute(span.id, 'tokens', 100);

    expect(tracker.getSpan(span.id)?.attributes.tokens).toBe(100);
  });

  it('should calculate duration', async () => {
    const tracker = new SpanTracker();
    const span = tracker.startSpan('test');
    await new Promise(r => setTimeout(r, 50));
    tracker.endSpan(span.id);

    expect(tracker.getDuration(span.id)).toBeGreaterThanOrEqual(50);
  });

  it('should track error status', () => {
    const tracker = new SpanTracker();
    const span = tracker.startSpan('failing');
    tracker.endSpan(span.id, 'error');

    expect(tracker.getSpan(span.id)?.status).toBe('error');
  });
});
