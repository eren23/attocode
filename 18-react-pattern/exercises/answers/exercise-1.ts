/**
 * Exercise 18: ReAct Step Tracker - REFERENCE SOLUTION
 */

export interface ReActStep {
  stepNumber: number;
  thought: string;
  action: { name: string; input: Record<string, unknown> } | null;
  observation: string | null;
  timestamp: number;
}

export interface ReActTrace {
  id: string;
  goal: string;
  steps: ReActStep[];
  status: 'running' | 'completed' | 'failed';
  result?: string;
}

export class ReActTracker {
  private traces: Map<string, ReActTrace> = new Map();

  startTrace(goal: string): ReActTrace {
    const trace: ReActTrace = {
      id: generateId(),
      goal,
      steps: [],
      status: 'running',
    };
    this.traces.set(trace.id, trace);
    return trace;
  }

  addThought(traceId: string, thought: string): ReActStep {
    const trace = this.traces.get(traceId);
    if (!trace) throw new Error('Trace not found');

    const step: ReActStep = {
      stepNumber: trace.steps.length + 1,
      thought,
      action: null,
      observation: null,
      timestamp: Date.now(),
    };
    trace.steps.push(step);
    return step;
  }

  addAction(traceId: string, action: { name: string; input: Record<string, unknown> }): void {
    const trace = this.traces.get(traceId);
    if (!trace || trace.steps.length === 0) throw new Error('No step to add action to');
    trace.steps[trace.steps.length - 1].action = action;
  }

  addObservation(traceId: string, observation: string): void {
    const trace = this.traces.get(traceId);
    if (!trace || trace.steps.length === 0) throw new Error('No step to add observation to');
    trace.steps[trace.steps.length - 1].observation = observation;
  }

  complete(traceId: string, result: string): void {
    const trace = this.traces.get(traceId);
    if (!trace) throw new Error('Trace not found');
    trace.status = 'completed';
    trace.result = result;
  }

  fail(traceId: string, error: string): void {
    const trace = this.traces.get(traceId);
    if (!trace) throw new Error('Trace not found');
    trace.status = 'failed';
    trace.result = error;
  }

  getTrace(traceId: string): ReActTrace | undefined {
    return this.traces.get(traceId);
  }

  formatTrace(traceId: string): string {
    const trace = this.traces.get(traceId);
    if (!trace) return 'Trace not found';

    const lines = [`Goal: ${trace.goal}`, ''];
    for (const step of trace.steps) {
      lines.push(`Step ${step.stepNumber}:`);
      lines.push(`  Thought: ${step.thought}`);
      if (step.action) lines.push(`  Action: ${step.action.name}(${JSON.stringify(step.action.input)})`);
      if (step.observation) lines.push(`  Observation: ${step.observation}`);
      lines.push('');
    }
    lines.push(`Status: ${trace.status}`);
    if (trace.result) lines.push(`Result: ${trace.result}`);
    return lines.join('\n');
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 10);
}
