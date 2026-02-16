/**
 * Interactive Planning Integration
 *
 * Combines conversational refinement with structural editing for plans.
 * Supports a Draft → Discuss → Execute → Checkpoint cycle.
 *
 * Features:
 * - Natural language plan editing ("add X after step 3", "skip step 2")
 * - Decision points where agent pauses for user input
 * - Automatic checkpoints before each step
 * - Rollback capability to any checkpoint
 *
 * @example
 * ```typescript
 * const planner = createInteractivePlanner({
 *   autoCheckpoint: true,
 *   confirmBeforeExecute: true,
 * });
 *
 * // Create and discuss a plan
 * const plan = await planner.draft('Add authentication to the API', llmCall);
 *
 * // User refines via conversation
 * planner.edit('add rate limiting after step 3');
 * planner.edit('skip the testing step for now');
 *
 * // Execute with checkpoints
 * for await (const step of planner.execute()) {
 *   console.log(`Executing: ${step.description}`);
 *   await executeStep(step);
 *   await planner.checkpoint();
 * }
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Status of the interactive plan.
 */
export type PlanStatus =
  | 'draft'        // Being drafted, not yet approved
  | 'discussing'   // Under discussion/refinement
  | 'approved'     // Approved, ready to execute
  | 'executing'    // Currently executing
  | 'paused'       // Paused at decision point
  | 'completed'    // All steps completed
  | 'failed'       // Execution failed
  | 'cancelled';   // User cancelled

/**
 * A step in the plan.
 */
export interface PlanStep {
  /** Unique ID */
  id: string;

  /** Step number (1-indexed for display) */
  number: number;

  /** Description of what to do */
  description: string;

  /** Dependencies (step IDs that must complete first) */
  dependencies: string[];

  /** Current status */
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';

  /** Reason for any status change */
  statusReason?: string;

  /** Checkpoint ID created before this step */
  checkpointId?: string;

  /** Output/result from execution */
  output?: string;

  /** Whether this is a decision point requiring user input */
  isDecisionPoint?: boolean;

  /** Decision options if this is a decision point */
  decisionOptions?: string[];

  /** User's decision choice */
  decisionChoice?: string;

  /** Estimated complexity (1-5) */
  complexity?: number;
}

/**
 * A checkpoint for rollback.
 */
export interface PlanCheckpoint {
  /** Unique ID */
  id: string;

  /** When created */
  timestamp: string;

  /** Label/description */
  label: string;

  /** Step ID this checkpoint is before */
  beforeStepId: string;

  /** Snapshot of plan state */
  planState: {
    steps: PlanStep[];
    status: PlanStatus;
    currentStepIndex: number;
  };

  /** Additional context to restore */
  context?: Record<string, unknown>;
}

/**
 * The interactive plan.
 */
export interface InteractivePlan {
  /** Unique ID */
  id: string;

  /** Original goal/task */
  goal: string;

  /** Plan steps */
  steps: PlanStep[];

  /** Current status */
  status: PlanStatus;

  /** Current step index (0-indexed) */
  currentStepIndex: number;

  /** Checkpoints for rollback */
  checkpoints: PlanCheckpoint[];

  /** Creation timestamp */
  createdAt: string;

  /** Last update timestamp */
  updatedAt: string;

  /** Conversation history for the plan */
  discussionHistory: Array<{ role: 'user' | 'assistant'; content: string }>;

  /** Agent's reasoning for the plan */
  reasoning?: string;
}

/**
 * Configuration for interactive planning.
 */
export interface InteractivePlannerConfig {
  /** Auto-create checkpoint before each step */
  autoCheckpoint?: boolean;

  /** Require confirmation before execution */
  confirmBeforeExecute?: boolean;

  /** Max checkpoints to keep */
  maxCheckpoints?: number;

  /** Auto-pause at decision points */
  autoPauseAtDecisions?: boolean;
}

/**
 * An edit command for the plan.
 */
export interface EditCommand {
  /** Type of edit */
  type: 'add' | 'remove' | 'move' | 'update' | 'skip' | 'unskip';

  /** Target step number or ID */
  target?: string | number;

  /** For add: position relative to target */
  position?: 'before' | 'after';

  /** New description or content */
  content?: string;

  /** For move: destination position */
  destination?: number;
}

/**
 * Result of parsing a natural language edit.
 */
export interface ParsedEdit {
  /** The edit command */
  command: EditCommand;

  /** Confidence in the parse (0-1) */
  confidence: number;

  /** Original input */
  original: string;

  /** Clarification question if confidence is low */
  clarificationNeeded?: string;
}

/**
 * LLM call function for planning.
 */
export type PlannerLLMCall = (
  systemPrompt: string,
  userMessage: string
) => Promise<{ content: string }>;

/**
 * Events emitted by the interactive planner.
 */
export type InteractivePlannerEvent =
  | { type: 'plan.created'; plan: InteractivePlan }
  | { type: 'plan.updated'; changes: string }
  | { type: 'plan.approved' }
  | { type: 'step.started'; step: PlanStep }
  | { type: 'step.completed'; step: PlanStep }
  | { type: 'step.failed'; step: PlanStep; error: string }
  | { type: 'step.skipped'; step: PlanStep; reason: string }
  | { type: 'decision.required'; step: PlanStep; options: string[] }
  | { type: 'decision.made'; step: PlanStep; choice: string }
  | { type: 'checkpoint.created'; checkpoint: PlanCheckpoint }
  | { type: 'rollback.started'; toCheckpoint: string }
  | { type: 'rollback.completed'; toCheckpoint: string }
  | { type: 'plan.completed' }
  | { type: 'plan.cancelled'; reason: string }
  | { type: 'edit.applied'; edit: EditCommand }
  | { type: 'edit.failed'; edit: EditCommand; reason: string };

export type InteractivePlannerEventListener = (event: InteractivePlannerEvent) => void;

// =============================================================================
// PROMPTS
// =============================================================================

const DRAFT_PLAN_PROMPT = `You are a planning assistant. Create a step-by-step plan for the given task.

Return a JSON object with this structure:
{
  "reasoning": "Brief explanation of your approach",
  "steps": [
    {
      "description": "Clear description of this step",
      "dependencies": [],
      "isDecisionPoint": false,
      "decisionOptions": [],
      "complexity": 1-5
    }
  ]
}

Guidelines:
- Keep steps atomic and actionable
- Mark decision points where user input might be needed
- Provide decision options for decision points
- Order steps logically with proper dependencies
- Include verification steps where appropriate

Task: {TASK}`;

const EDIT_PARSE_PROMPT = `Parse this edit command for a plan. Return JSON:
{
  "type": "add|remove|move|update|skip|unskip",
  "target": number or null,
  "position": "before|after" or null,
  "content": "new description" or null,
  "destination": number or null,
  "confidence": 0.0-1.0,
  "clarificationNeeded": "question if confidence < 0.7" or null
}

Current plan steps:
{STEPS}

Edit command: {COMMAND}`;

// =============================================================================
// INTERACTIVE PLANNER
// =============================================================================

/**
 * Manages interactive planning with conversation and checkpoints.
 */
export class InteractivePlanner {
  private config: Required<InteractivePlannerConfig>;
  private plan: InteractivePlan | null = null;
  private listeners: InteractivePlannerEventListener[] = [];

  constructor(config: InteractivePlannerConfig = {}) {
    this.config = {
      autoCheckpoint: config.autoCheckpoint ?? true,
      confirmBeforeExecute: config.confirmBeforeExecute ?? true,
      maxCheckpoints: config.maxCheckpoints ?? 20,
      autoPauseAtDecisions: config.autoPauseAtDecisions ?? true,
    };
  }

  /**
   * Get the current plan.
   */
  getPlan(): InteractivePlan | null {
    return this.plan;
  }

  /**
   * Draft a new plan.
   */
  async draft(goal: string, llmCall: PlannerLLMCall): Promise<InteractivePlan> {
    const systemPrompt = DRAFT_PLAN_PROMPT.replace('{TASK}', goal);

    const response = await llmCall(systemPrompt, `Create a plan for: ${goal}`);

    const parsed = this.parsePlanResponse(response.content);

    this.plan = {
      id: `plan-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      goal,
      steps: parsed.steps.map((s, i) => ({
        id: `step-${i + 1}`,
        number: i + 1,
        description: s.description,
        dependencies: s.dependencies || [],
        status: 'pending' as const,
        isDecisionPoint: s.isDecisionPoint || false,
        decisionOptions: s.decisionOptions || [],
        complexity: s.complexity || 1,
      })),
      status: 'draft',
      currentStepIndex: 0,
      checkpoints: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      discussionHistory: [],
      reasoning: parsed.reasoning,
    };

    this.emit({ type: 'plan.created', plan: this.plan });

    return this.plan;
  }

  /**
   * Parse an LLM plan response.
   */
  private parsePlanResponse(content: string): {
    reasoning?: string;
    steps: Array<{
      description: string;
      dependencies?: string[];
      isDecisionPoint?: boolean;
      decisionOptions?: string[];
      complexity?: number;
    }>;
  } {
    try {
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        return JSON.parse(jsonMatch[0]);
      }
    } catch {
      // Parse failed
    }

    // Fallback: extract numbered steps
    const stepMatches = content.match(/\d+\.\s+[^\n]+/g) || [];
    return {
      steps: stepMatches.map((s) => ({
        description: s.replace(/^\d+\.\s+/, '').trim(),
      })),
    };
  }

  /**
   * Edit the plan using natural language.
   */
  async edit(command: string, llmCall?: PlannerLLMCall): Promise<ParsedEdit> {
    if (!this.plan) {
      throw new Error('No plan to edit');
    }

    // Try to parse without LLM first
    const directParse = this.parseEditDirectly(command);
    if (directParse.confidence >= 0.8) {
      this.applyEdit(directParse.command);
      return directParse;
    }

    // Use LLM to parse if available
    if (llmCall) {
      const stepsText = this.plan.steps
        .map((s) => `${s.number}. ${s.description} [${s.status}]`)
        .join('\n');

      const prompt = EDIT_PARSE_PROMPT
        .replace('{STEPS}', stepsText)
        .replace('{COMMAND}', command);

      const response = await llmCall(prompt, command);
      const parsed = this.parseEditResponse(response.content, command);

      if (parsed.confidence >= 0.7 && !parsed.clarificationNeeded) {
        this.applyEdit(parsed.command);
      }

      return parsed;
    }

    // Return direct parse even if low confidence
    return directParse;
  }

  /**
   * Parse edit command directly without LLM.
   */
  private parseEditDirectly(command: string): ParsedEdit {
    const lower = command.toLowerCase().trim();

    // Unskip step N (check before skip to avoid false match)
    const unskipMatch = lower.match(/unskip\s+step\s+(\d+)/);
    if (unskipMatch) {
      return {
        command: { type: 'unskip', target: parseInt(unskipMatch[1], 10) },
        confidence: 0.95,
        original: command,
      };
    }

    // Skip step N
    const skipMatch = lower.match(/skip\s+step\s+(\d+)/);
    if (skipMatch) {
      return {
        command: { type: 'skip', target: parseInt(skipMatch[1], 10) },
        confidence: 0.95,
        original: command,
      };
    }

    // Remove step N
    const removeMatch = lower.match(/(?:remove|delete)\s+step\s+(\d+)/);
    if (removeMatch) {
      return {
        command: { type: 'remove', target: parseInt(removeMatch[1], 10) },
        confidence: 0.95,
        original: command,
      };
    }

    // Add X after/before step N
    const addMatch = lower.match(/add\s+(.+?)\s+(before|after)\s+step\s+(\d+)/);
    if (addMatch) {
      return {
        command: {
          type: 'add',
          content: addMatch[1],
          position: addMatch[2] as 'before' | 'after',
          target: parseInt(addMatch[3], 10),
        },
        confidence: 0.9,
        original: command,
      };
    }

    // Move step N to position M
    const moveMatch = lower.match(/move\s+step\s+(\d+)\s+to\s+(?:position\s+)?(\d+)/);
    if (moveMatch) {
      return {
        command: {
          type: 'move',
          target: parseInt(moveMatch[1], 10),
          destination: parseInt(moveMatch[2], 10),
        },
        confidence: 0.9,
        original: command,
      };
    }

    // Update step N to X
    const updateMatch = lower.match(/(?:update|change)\s+step\s+(\d+)\s+to\s+(.+)/);
    if (updateMatch) {
      return {
        command: {
          type: 'update',
          target: parseInt(updateMatch[1], 10),
          content: updateMatch[2],
        },
        confidence: 0.85,
        original: command,
      };
    }

    // Low confidence fallback
    return {
      command: { type: 'update', content: command },
      confidence: 0.3,
      original: command,
      clarificationNeeded: 'Could you be more specific? Try "skip step 3" or "add X after step 2"',
    };
  }

  /**
   * Parse edit response from LLM.
   */
  private parseEditResponse(content: string, original: string): ParsedEdit {
    try {
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        const parsed = JSON.parse(jsonMatch[0]);
        return {
          command: {
            type: parsed.type || 'update',
            target: parsed.target,
            position: parsed.position,
            content: parsed.content,
            destination: parsed.destination,
          },
          confidence: parsed.confidence || 0.5,
          original,
          clarificationNeeded: parsed.clarificationNeeded,
        };
      }
    } catch {
      // Parse failed
    }

    return {
      command: { type: 'update' },
      confidence: 0.3,
      original,
      clarificationNeeded: 'Could not parse the edit command. Please try again.',
    };
  }

  /**
   * Apply an edit command to the plan.
   */
  private applyEdit(edit: EditCommand): void {
    if (!this.plan) return;

    const targetIndex = typeof edit.target === 'number'
      ? edit.target - 1
      : this.plan.steps.findIndex((s) => s.id === edit.target);

    switch (edit.type) {
      case 'skip': {
        if (targetIndex >= 0 && targetIndex < this.plan.steps.length) {
          this.plan.steps[targetIndex].status = 'skipped';
          this.plan.steps[targetIndex].statusReason = 'User skipped';
        }
        break;
      }

      case 'unskip': {
        if (targetIndex >= 0 && targetIndex < this.plan.steps.length) {
          this.plan.steps[targetIndex].status = 'pending';
          this.plan.steps[targetIndex].statusReason = undefined;
        }
        break;
      }

      case 'remove': {
        if (targetIndex >= 0 && targetIndex < this.plan.steps.length) {
          this.plan.steps.splice(targetIndex, 1);
          this.renumberSteps();
        }
        break;
      }

      case 'add': {
        if (edit.content && targetIndex >= 0) {
          const insertIndex = edit.position === 'before' ? targetIndex : targetIndex + 1;
          const newStep: PlanStep = {
            id: `step-new-${Date.now()}`,
            number: insertIndex + 1,
            description: edit.content,
            dependencies: [],
            status: 'pending',
          };
          this.plan.steps.splice(insertIndex, 0, newStep);
          this.renumberSteps();
        }
        break;
      }

      case 'move': {
        if (targetIndex >= 0 && edit.destination !== undefined) {
          const step = this.plan.steps.splice(targetIndex, 1)[0];
          const destIndex = Math.min(edit.destination - 1, this.plan.steps.length);
          this.plan.steps.splice(destIndex, 0, step);
          this.renumberSteps();
        }
        break;
      }

      case 'update': {
        if (targetIndex >= 0 && edit.content) {
          this.plan.steps[targetIndex].description = edit.content;
        }
        break;
      }
    }

    this.plan.updatedAt = new Date().toISOString();
    this.emit({ type: 'edit.applied', edit });
    this.emit({ type: 'plan.updated', changes: `${edit.type} applied` });
  }

  /**
   * Renumber steps after modification.
   */
  private renumberSteps(): void {
    if (!this.plan) return;

    this.plan.steps.forEach((step, i) => {
      step.number = i + 1;
    });
  }

  /**
   * Approve the plan for execution.
   */
  approve(): void {
    if (!this.plan) {
      throw new Error('No plan to approve');
    }

    if (this.plan.status !== 'draft' && this.plan.status !== 'discussing') {
      throw new Error(`Cannot approve plan in status: ${this.plan.status}`);
    }

    this.plan.status = 'approved';
    this.plan.updatedAt = new Date().toISOString();
    this.emit({ type: 'plan.approved' });
  }

  /**
   * Start execution of the plan.
   */
  *execute(): Generator<PlanStep, void, void> {
    if (!this.plan) {
      throw new Error('No plan to execute');
    }

    if (this.plan.status !== 'approved') {
      if (this.config.confirmBeforeExecute) {
        throw new Error('Plan must be approved before execution');
      }
      this.plan.status = 'approved';
    }

    this.plan.status = 'executing';
    this.plan.updatedAt = new Date().toISOString();

    while (this.plan.currentStepIndex < this.plan.steps.length) {
      const step = this.plan.steps[this.plan.currentStepIndex];

      // Skip already completed or skipped steps
      if (step.status === 'completed' || step.status === 'skipped') {
        this.plan.currentStepIndex++;
        continue;
      }

      // Check dependencies
      const depsComplete = step.dependencies.every((depId) => {
        const dep = this.plan!.steps.find((s) => s.id === depId);
        return dep?.status === 'completed' || dep?.status === 'skipped';
      });

      if (!depsComplete) {
        throw new Error(`Step ${step.number} has unmet dependencies`);
      }

      // Auto-checkpoint before step
      if (this.config.autoCheckpoint) {
        this.createCheckpoint(`Before step ${step.number}`);
        step.checkpointId = this.plan.checkpoints[this.plan.checkpoints.length - 1]?.id;
      }

      // Check for decision point
      if (step.isDecisionPoint && this.config.autoPauseAtDecisions && !step.decisionChoice) {
        this.plan.status = 'paused';
        this.emit({
          type: 'decision.required',
          step,
          options: step.decisionOptions || [],
        });
        return;
      }

      // Mark step as in progress
      step.status = 'in_progress';
      this.emit({ type: 'step.started', step });

      // Yield the step for execution
      yield step;
    }

    this.plan.status = 'completed';
    this.plan.updatedAt = new Date().toISOString();
    this.emit({ type: 'plan.completed' });
  }

  /**
   * Mark the current step as completed.
   */
  completeStep(output?: string): void {
    if (!this.plan || this.plan.currentStepIndex >= this.plan.steps.length) {
      return;
    }

    const step = this.plan.steps[this.plan.currentStepIndex];
    step.status = 'completed';
    step.output = output;
    this.plan.currentStepIndex++;
    this.plan.updatedAt = new Date().toISOString();

    this.emit({ type: 'step.completed', step });
  }

  /**
   * Mark the current step as failed.
   */
  failStep(error: string): void {
    if (!this.plan || this.plan.currentStepIndex >= this.plan.steps.length) {
      return;
    }

    const step = this.plan.steps[this.plan.currentStepIndex];
    step.status = 'failed';
    step.statusReason = error;
    this.plan.status = 'failed';
    this.plan.updatedAt = new Date().toISOString();

    this.emit({ type: 'step.failed', step, error });
  }

  /**
   * Make a decision for a decision point.
   */
  makeDecision(choice: string): void {
    if (!this.plan || this.plan.status !== 'paused') {
      throw new Error('No decision pending');
    }

    const step = this.plan.steps[this.plan.currentStepIndex];
    step.decisionChoice = choice;
    this.plan.status = 'executing';
    this.plan.updatedAt = new Date().toISOString();

    this.emit({ type: 'decision.made', step, choice });
  }

  /**
   * Create a checkpoint.
   */
  createCheckpoint(label: string): PlanCheckpoint {
    if (!this.plan) {
      throw new Error('No plan for checkpoint');
    }

    const checkpoint: PlanCheckpoint = {
      id: `cp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      timestamp: new Date().toISOString(),
      label,
      beforeStepId: this.plan.steps[this.plan.currentStepIndex]?.id || 'end',
      planState: {
        steps: JSON.parse(JSON.stringify(this.plan.steps)),
        status: this.plan.status,
        currentStepIndex: this.plan.currentStepIndex,
      },
    };

    this.plan.checkpoints.push(checkpoint);

    // Enforce max checkpoints
    while (this.plan.checkpoints.length > this.config.maxCheckpoints) {
      this.plan.checkpoints.shift();
    }

    this.emit({ type: 'checkpoint.created', checkpoint });

    return checkpoint;
  }

  /**
   * Rollback to a checkpoint.
   */
  rollback(checkpointId: string): void {
    if (!this.plan) {
      throw new Error('No plan to rollback');
    }

    const checkpoint = this.plan.checkpoints.find((cp) => cp.id === checkpointId);
    if (!checkpoint) {
      throw new Error(`Checkpoint ${checkpointId} not found`);
    }

    this.emit({ type: 'rollback.started', toCheckpoint: checkpointId });

    // Restore state
    this.plan.steps = JSON.parse(JSON.stringify(checkpoint.planState.steps));
    this.plan.status = checkpoint.planState.status;
    this.plan.currentStepIndex = checkpoint.planState.currentStepIndex;
    this.plan.updatedAt = new Date().toISOString();

    // Remove checkpoints after this one
    const cpIndex = this.plan.checkpoints.findIndex((cp) => cp.id === checkpointId);
    this.plan.checkpoints = this.plan.checkpoints.slice(0, cpIndex + 1);

    this.emit({ type: 'rollback.completed', toCheckpoint: checkpointId });
  }

  /**
   * Cancel the plan.
   */
  cancel(reason: string): void {
    if (!this.plan) {
      return;
    }

    this.plan.status = 'cancelled';
    this.plan.updatedAt = new Date().toISOString();
    this.emit({ type: 'plan.cancelled', reason });
  }

  /**
   * Add a message to discussion history.
   */
  addDiscussion(role: 'user' | 'assistant', content: string): void {
    if (!this.plan) {
      return;
    }

    this.plan.discussionHistory.push({ role, content });

    if (this.plan.status === 'draft') {
      this.plan.status = 'discussing';
    }
  }

  /**
   * Get checkpoints for display.
   */
  getCheckpoints(): PlanCheckpoint[] {
    return this.plan?.checkpoints || [];
  }

  /**
   * Clear the current plan.
   */
  clear(): void {
    this.plan = null;
  }

  /**
   * Subscribe to events.
   */
  on(listener: InteractivePlannerEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  private emit(event: InteractivePlannerEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create an interactive planner.
 */
export function createInteractivePlanner(
  config: InteractivePlannerConfig = {}
): InteractivePlanner {
  return new InteractivePlanner(config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format plan for display.
 */
export function formatPlan(plan: InteractivePlan): string {
  const lines = [
    `Plan: ${plan.goal}`,
    `Status: ${plan.status}`,
    `Steps: ${plan.steps.length}`,
    '',
  ];

  if (plan.reasoning) {
    lines.push(`Reasoning: ${plan.reasoning}`);
    lines.push('');
  }

  for (const step of plan.steps) {
    const statusIcon = {
      pending: '○',
      in_progress: '◐',
      completed: '●',
      failed: '✗',
      skipped: '⊘',
    }[step.status];

    let line = `${statusIcon} ${step.number}. ${step.description}`;

    if (step.isDecisionPoint) {
      line += ' [DECISION]';
    }

    if (step.status === 'failed' && step.statusReason) {
      line += ` (${step.statusReason})`;
    }

    lines.push(line);
  }

  if (plan.checkpoints.length > 0) {
    lines.push('');
    lines.push(`Checkpoints: ${plan.checkpoints.length}`);
  }

  return lines.join('\n');
}

/**
 * Format step for display.
 */
export function formatStep(step: PlanStep): string {
  let text = `Step ${step.number}: ${step.description}`;

  if (step.isDecisionPoint) {
    text += '\n  Decision options:';
    for (const option of step.decisionOptions || []) {
      text += `\n    - ${option}`;
    }
    if (step.decisionChoice) {
      text += `\n  Choice: ${step.decisionChoice}`;
    }
  }

  if (step.output) {
    text += `\n  Output: ${step.output.slice(0, 100)}${step.output.length > 100 ? '...' : ''}`;
  }

  return text;
}
