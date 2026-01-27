/**
 * Exercise 16: Reflection Loop - REFERENCE SOLUTION
 */

export interface Critique {
  issues: string[];
  suggestions: string[];
  confidence: number;
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

export class ReflectionLoop<T> {
  constructor(private config: ReflectionConfig) {}

  async run(
    generate: () => Promise<T>,
    critique: (output: T) => Promise<Critique>,
    improve: (output: T, critique: Critique) => Promise<T>
  ): Promise<ReflectionResult<T>> {
    let output = await generate();
    const critiques: Critique[] = [];
    let iterations = 0;

    while (iterations < this.config.maxIterations) {
      iterations++;
      const critiqueResult = await critique(output);
      critiques.push(critiqueResult);

      if (critiqueResult.confidence >= this.config.targetConfidence) {
        break;
      }

      if (iterations < this.config.maxIterations) {
        output = await improve(output, critiqueResult);
      }
    }

    return {
      output,
      iterations,
      critiques,
      finalConfidence: critiques[critiques.length - 1]?.confidence ?? 0,
    };
  }
}
