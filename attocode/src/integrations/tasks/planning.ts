/**
 * Lesson 23: Planning Integration
 *
 * Integrates planning (Lesson 15) and reflection (Lesson 16) into the production agent.
 * Provides task decomposition and self-improvement capabilities.
 */

import type {
  PlanningConfig,
  ReflectionConfig,
  AgentPlan,
  PlanTask,
  LLMProvider,
  Message,
} from '../../types.js';
import { logger } from '../utilities/logger.js';

// =============================================================================
// PLANNING MANAGER
// =============================================================================

/**
 * Manages planning and reflection for the agent.
 */
export class PlanningManager {
  private planningConfig: PlanningConfig;
  private reflectionConfig: ReflectionConfig;
  private currentPlan: AgentPlan | null = null;

  constructor(planningConfig: PlanningConfig, reflectionConfig: ReflectionConfig) {
    this.planningConfig = planningConfig;
    this.reflectionConfig = reflectionConfig;
  }

  /**
   * Determine if task needs planning.
   */
  shouldPlan(task: string): boolean {
    if (!this.planningConfig.autoplan) return false;

    const complexity = this.estimateComplexity(task);
    return complexity >= (this.planningConfig.complexityThreshold || 5);
  }

  /**
   * Estimate task complexity (1-10 scale).
   */
  estimateComplexity(task: string): number {
    let score = 1;

    // Length-based complexity
    if (task.length > 100) score += 1;
    if (task.length > 200) score += 1;

    // Keyword-based complexity
    const complexKeywords = [
      'implement', 'refactor', 'migrate', 'integrate', 'build',
      'create', 'design', 'architect', 'optimize', 'debug',
      'multiple', 'several', 'all', 'entire', 'complete',
    ];

    for (const keyword of complexKeywords) {
      if (task.toLowerCase().includes(keyword)) {
        score += 0.5;
      }
    }

    // Multi-step indicators
    if (task.includes(' and ') || task.includes(' then ')) score += 1;
    if (task.includes('1.') || task.includes('first')) score += 1;

    // Cap at 10
    return Math.min(Math.round(score), 10);
  }

  /**
   * Create a plan for a task.
   */
  async createPlan(task: string, provider: LLMProvider): Promise<AgentPlan> {
    const planPrompt = `Break down this task into concrete steps:

Task: ${task}

Return a JSON array of steps, each with:
- id: unique identifier (step-1, step-2, etc.)
- description: what needs to be done
- dependencies: array of step IDs this depends on (empty for first steps)

Example format:
[
  { "id": "step-1", "description": "Analyze current code", "dependencies": [] },
  { "id": "step-2", "description": "Design new structure", "dependencies": ["step-1"] }
]

Return ONLY the JSON array, no other text.`;

    const messages: Message[] = [
      { role: 'user', content: planPrompt },
    ];

    try {
      const response = await provider.chat(messages);
      const tasks = this.parsePlanResponse(response.content, task);

      this.currentPlan = {
        goal: task,
        tasks,
        currentTaskIndex: 0,
      };

      return this.currentPlan;
    } catch (err) {
      // Fallback to simple plan
      logger.warn('Failed to create detailed plan, using fallback');
      return this.createFallbackPlan(task);
    }
  }

  /**
   * Parse plan response from LLM.
   *
   * Handles multiple response formats:
   * - Markdown code blocks: ```json [...] ```
   * - Plain JSON arrays: [...]
   * - Text before/after JSON
   */
  private parsePlanResponse(content: string, goal: string): PlanTask[] {
    try {
      let jsonStr = content;

      // Step 1: Try extracting from markdown code blocks first
      const codeBlockMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/);
      if (codeBlockMatch) {
        jsonStr = codeBlockMatch[1].trim();
      }

      // Step 2: Try to find a JSON array (non-greedy to get first complete array)
      // Use a bracket-balanced approach for robustness
      const arrayStart = jsonStr.indexOf('[');
      if (arrayStart === -1) {
        throw new Error('No JSON array found');
      }

      // Find the matching closing bracket using bracket counting
      let depth = 0;
      let arrayEnd = -1;
      for (let i = arrayStart; i < jsonStr.length; i++) {
        const char = jsonStr[i];
        if (char === '[') depth++;
        else if (char === ']') {
          depth--;
          if (depth === 0) {
            arrayEnd = i;
            break;
          }
        }
      }

      if (arrayEnd === -1) {
        throw new Error('No valid JSON array found - unbalanced brackets');
      }

      const extractedJson = jsonStr.slice(arrayStart, arrayEnd + 1);
      const parsed = JSON.parse(extractedJson);

      if (!Array.isArray(parsed)) {
        throw new Error('Response is not an array');
      }

      return parsed.map((item: Record<string, unknown>, index: number) => ({
        id: String(item.id || `step-${index + 1}`),
        description: String(item.description || `Step ${index + 1}`),
        status: 'pending' as const,
        dependencies: Array.isArray(item.dependencies)
          ? item.dependencies.map(String)
          : [],
      }));
    } catch (err) {
      logger.warn('Failed to parse plan', { error: String(err) });
      return this.createFallbackPlan(goal).tasks;
    }
  }

  /**
   * Create a simple fallback plan.
   */
  private createFallbackPlan(task: string): AgentPlan {
    return {
      goal: task,
      tasks: [
        { id: 'step-1', description: 'Understand the requirements', status: 'pending', dependencies: [] },
        { id: 'step-2', description: 'Execute the task', status: 'pending', dependencies: ['step-1'] },
        { id: 'step-3', description: 'Verify the results', status: 'pending', dependencies: ['step-2'] },
      ],
      currentTaskIndex: 0,
    };
  }

  /**
   * Get the current plan.
   */
  getCurrentPlan(): AgentPlan | null {
    return this.currentPlan;
  }

  /**
   * Get the current task to work on.
   */
  getCurrentTask(): PlanTask | null {
    if (!this.currentPlan) return null;

    const { tasks, currentTaskIndex } = this.currentPlan;
    if (currentTaskIndex >= tasks.length) return null;

    return tasks[currentTaskIndex];
  }

  /**
   * Get next available task (dependencies satisfied).
   */
  getNextTask(): PlanTask | null {
    if (!this.currentPlan) return null;

    for (const task of this.currentPlan.tasks) {
      if (task.status !== 'pending') continue;

      // Check dependencies
      const depsComplete = task.dependencies.every((depId) => {
        const dep = this.currentPlan!.tasks.find((t) => t.id === depId);
        return dep?.status === 'completed';
      });

      if (depsComplete) {
        return task;
      }
    }

    return null;
  }

  /**
   * Mark a task as started.
   */
  startTask(taskId: string): void {
    if (!this.currentPlan) return;

    const task = this.currentPlan.tasks.find((t) => t.id === taskId);
    if (task) {
      task.status = 'in_progress';
    }
  }

  /**
   * Mark a task as completed.
   */
  completeTask(taskId: string): void {
    if (!this.currentPlan) return;

    const task = this.currentPlan.tasks.find((t) => t.id === taskId);
    if (task) {
      task.status = 'completed';
      this.currentPlan.currentTaskIndex++;
    }
  }

  /**
   * Mark a task as failed.
   */
  failTask(taskId: string): void {
    if (!this.currentPlan) return;

    const task = this.currentPlan.tasks.find((t) => t.id === taskId);
    if (task) {
      task.status = 'failed';
    }
  }

  /**
   * Check if plan is complete.
   */
  isPlanComplete(): boolean {
    if (!this.currentPlan) return true;

    return this.currentPlan.tasks.every(
      (t) => t.status === 'completed' || t.status === 'failed'
    );
  }

  /**
   * Get groups of tasks that can be executed in parallel.
   * Groups tasks by dependency level - tasks in the same group have
   * no dependencies on each other and can run concurrently.
   *
   * @returns Array of task arrays, where each inner array contains
   *          tasks that can be executed in parallel
   */
  getParallelizableTasks(): PlanTask[][] {
    if (!this.currentPlan) return [];

    const groups: PlanTask[][] = [];
    const pending = this.currentPlan.tasks.filter(t => t.status === 'pending');
    const processed = new Set<string>();

    // Find tasks whose dependencies are all completed
    while (processed.size < pending.length) {
      const canRun = pending.filter(t => {
        // Skip already processed
        if (processed.has(t.id)) return false;

        // Check all dependencies are completed
        return t.dependencies.every(depId => {
          const dep = this.currentPlan!.tasks.find(x => x.id === depId);
          return dep?.status === 'completed' || processed.has(depId);
        });
      });

      if (canRun.length === 0) {
        // No more tasks can run (circular dependency or all processed)
        break;
      }

      groups.push(canRun);
      canRun.forEach(t => processed.add(t.id));
    }

    return groups;
  }

  /**
   * Get the next group of tasks that can be run in parallel.
   * Returns tasks whose dependencies are all completed.
   */
  getNextParallelGroup(): PlanTask[] {
    const groups = this.getParallelizableTasks();
    return groups[0] || [];
  }

  /**
   * Clear the current plan.
   */
  clearPlan(): void {
    this.currentPlan = null;
  }

  /**
   * Load a plan from a checkpoint.
   */
  loadPlan(plan: AgentPlan): void {
    this.currentPlan = { ...plan };
  }

  // ===========================================================================
  // REFLECTION
  // ===========================================================================

  /**
   * Reflect on an output and determine if it's satisfactory.
   */
  async reflect(
    goal: string,
    output: string,
    provider: LLMProvider
  ): Promise<ReflectionResult> {
    const reflectionPrompt = `Evaluate this output against the goal.

Goal: ${goal}

Output:
${output}

Evaluate:
1. Does the output fully address the goal?
2. Are there any errors or issues?
3. What could be improved?

Respond in JSON format:
{
  "satisfied": true/false,
  "confidence": 0.0-1.0,
  "critique": "brief critique",
  "suggestions": ["suggestion 1", "suggestion 2"]
}

Return ONLY the JSON, no other text.`;

    const messages: Message[] = [
      { role: 'user', content: reflectionPrompt },
    ];

    try {
      const response = await provider.chat(messages);
      return this.parseReflectionResponse(response.content);
    } catch (err) {
      logger.warn('Failed to reflect', { error: String(err) });
      return {
        satisfied: true,
        confidence: 0.5,
        critique: 'Unable to reflect on output',
        suggestions: [],
      };
    }
  }

  /**
   * Parse reflection response.
   */
  private parseReflectionResponse(content: string): ReflectionResult {
    try {
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (!jsonMatch) {
        throw new Error('No JSON object found');
      }

      const parsed = JSON.parse(jsonMatch[0]);

      return {
        satisfied: Boolean(parsed.satisfied),
        confidence: Number(parsed.confidence) || 0.5,
        critique: String(parsed.critique || ''),
        suggestions: Array.isArray(parsed.suggestions)
          ? parsed.suggestions.map(String)
          : [],
      };
    } catch (err) {
      return {
        satisfied: true,
        confidence: 0.5,
        critique: 'Unable to parse reflection',
        suggestions: [],
      };
    }
  }

  /**
   * Run a reflection loop on a task.
   */
  async reflectionLoop(
    task: () => Promise<string>,
    goal: string,
    provider: LLMProvider
  ): Promise<{ output: string; attempts: number; reflections: ReflectionResult[] }> {
    const maxAttempts = this.reflectionConfig.maxAttempts || 3;
    const threshold = this.reflectionConfig.confidenceThreshold || 0.8;
    const reflections: ReflectionResult[] = [];

    let output = '';
    let attempts = 0;

    while (attempts < maxAttempts) {
      attempts++;
      output = await task();

      if (!this.reflectionConfig.autoReflect && attempts === 1) {
        // No auto-reflection, return first output
        break;
      }

      const reflection = await this.reflect(goal, output, provider);
      reflections.push(reflection);

      if (reflection.satisfied && reflection.confidence >= threshold) {
        break;
      }

      if (attempts < maxAttempts) {
        logger.info('Reflection attempt not satisfactory, retrying', { attempt: attempts });
      }
    }

    return { output, attempts, reflections };
  }
}

// =============================================================================
// TYPES
// =============================================================================

export interface ReflectionResult {
  satisfied: boolean;
  confidence: number;
  critique: string;
  suggestions: string[];
}

// =============================================================================
// FACTORY
// =============================================================================

export function createPlanningManager(
  planningConfig: PlanningConfig,
  reflectionConfig: ReflectionConfig
): PlanningManager {
  return new PlanningManager(planningConfig, reflectionConfig);
}
