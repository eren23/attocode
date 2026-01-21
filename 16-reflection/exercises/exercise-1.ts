/**
 * Exercise 16: Reflection Loop
 * Implement iterative self-improvement with confidence scoring.
 */

export interface Critique {
  issues: string[];
  suggestions: string[];
  confidence: number; // 0-1
}

export interface ReflectionResult<T> {
  output: T;
  iterations: number;
  critiques: Critique[];
  finalConfidence: number;
}

export interface ReflectionConfig {
  maxIterations: number;
  targetConfidence: number;
}

/**
 * TODO: Implement ReflectionLoop
 */
export class ReflectionLoop<T> {
  constructor(private _config: ReflectionConfig) {}

  async run(
    _generate: () => Promise<T>,
    _critique: (output: T) => Promise<Critique>,
    _improve: (output: T, critique: Critique) => Promise<T>
  ): Promise<ReflectionResult<T>> {
    // TODO: Loop until confidence met or max iterations
    throw new Error('TODO: Implement run');
  }
}
