/**
 * Exercise Tests: Lesson 18 - ReAct Step Tracker
 */
import { describe, it, expect } from 'vitest';
import { ReActTracker } from './exercises/answers/exercise-1.js';

describe('ReActTracker', () => {
  it('should start a trace', () => {
    const tracker = new ReActTracker();
    const trace = tracker.startTrace('Find the bug');

    expect(trace.goal).toBe('Find the bug');
    expect(trace.status).toBe('running');
  });

  it('should add thought-action-observation steps', () => {
    const tracker = new ReActTracker();
    const trace = tracker.startTrace('Test goal');

    const step = tracker.addThought(trace.id, 'I need to read the file');
    tracker.addAction(trace.id, { name: 'read_file', input: { path: 'test.ts' } });
    tracker.addObservation(trace.id, 'File contains: console.log("hello")');

    expect(step.thought).toBe('I need to read the file');
    expect(tracker.getTrace(trace.id)?.steps[0].action?.name).toBe('read_file');
    expect(tracker.getTrace(trace.id)?.steps[0].observation).toContain('hello');
  });

  it('should complete trace', () => {
    const tracker = new ReActTracker();
    const trace = tracker.startTrace('Goal');

    tracker.addThought(trace.id, 'Done');
    tracker.complete(trace.id, 'Success!');

    expect(tracker.getTrace(trace.id)?.status).toBe('completed');
    expect(tracker.getTrace(trace.id)?.result).toBe('Success!');
  });

  it('should fail trace', () => {
    const tracker = new ReActTracker();
    const trace = tracker.startTrace('Goal');

    tracker.fail(trace.id, 'Error occurred');

    expect(tracker.getTrace(trace.id)?.status).toBe('failed');
  });

  it('should format trace for display', () => {
    const tracker = new ReActTracker();
    const trace = tracker.startTrace('Test');

    tracker.addThought(trace.id, 'Thinking...');
    tracker.addAction(trace.id, { name: 'test', input: {} });
    tracker.complete(trace.id, 'Done');

    const formatted = tracker.formatTrace(trace.id);
    expect(formatted).toContain('Goal: Test');
    expect(formatted).toContain('Thought: Thinking...');
    expect(formatted).toContain('Status: completed');
  });
});
