/**
 * Exercise 18: ReAct Step Tracker
 * Implement Reasoning + Acting pattern tracking.
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

/**
 * TODO: Implement ReActTracker
 */
export class ReActTracker {
  private traces: Map<string, ReActTrace> = new Map();

  startTrace(_goal: string): ReActTrace {
    throw new Error('TODO: Implement startTrace');
  }

  addThought(_traceId: string, _thought: string): ReActStep {
    throw new Error('TODO: Implement addThought');
  }

  addAction(_traceId: string, _action: { name: string; input: Record<string, unknown> }): void {
    throw new Error('TODO: Implement addAction');
  }

  addObservation(_traceId: string, _observation: string): void {
    throw new Error('TODO: Implement addObservation');
  }

  complete(_traceId: string, _result: string): void {
    throw new Error('TODO: Implement complete');
  }

  fail(_traceId: string, _error: string): void {
    throw new Error('TODO: Implement fail');
  }

  getTrace(_traceId: string): ReActTrace | undefined {
    throw new Error('TODO: Implement getTrace');
  }

  formatTrace(_traceId: string): string {
    throw new Error('TODO: Implement formatTrace');
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 10);
}
