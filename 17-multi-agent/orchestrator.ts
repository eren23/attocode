/**
 * Lesson 17: Orchestrator
 *
 * Coordinates multiple agents to complete tasks.
 * Handles task assignment, execution, and result aggregation.
 *
 * Enhanced with ResultSynthesizer integration for:
 * - Intelligent code merging from multiple agents
 * - Finding deduplication and synthesis
 * - Conflict detection and resolution
 */

import type {
  Orchestrator,
  AgentTeam,
  TeamTask,
  TeamTaskResult,
  TaskProgress,
  Agent,
  AgentResult,
  Subtask,
  Opinion,
  Decision,
  CoordinationEvent,
  CoordinationEventListener,
} from './types.js';
import { ConsensusEngine, createOpinion } from './consensus.js';
import {
  createTaskAssignment,
  createTaskComplete,
  createReviewRequest,
  createReviewFeedback,
  SimpleChannel,
} from './communication.js';
import { canPerform, getHighestAuthorityRole } from './agent-roles.js';

// =============================================================================
// RESULT SYNTHESIZER TYPES (inline to avoid circular dependencies)
// =============================================================================

/**
 * A result from an agent that can be synthesized.
 */
export interface SynthesizerInput {
  agentId: string;
  content: string;
  type: 'code' | 'research' | 'analysis' | 'review' | 'plan' | 'documentation' | 'mixed';
  confidence: number;
  authority?: number;
  filesModified?: Array<{ path: string; type: string; newContent: string }>;
  findings?: string[];
  errors?: string[];
}

/**
 * Configuration for orchestrator synthesis.
 */
export interface OrchestratorSynthesisConfig {
  /** Enable structured synthesis instead of simple consensus */
  enableSynthesis?: boolean;
  /** Conflict resolution strategy */
  conflictResolution?: 'highest_confidence' | 'highest_authority' | 'merge_both' | 'voting';
  /** Deduplication threshold (0-1) */
  deduplicationThreshold?: number;
  /** Enable LLM-assisted synthesis */
  useLLM?: boolean;
  /** LLM synthesis function */
  llmSynthesizer?: (inputs: SynthesizerInput[], conflicts: any[]) => Promise<any>;
}

// =============================================================================
// TEAM ORCHESTRATOR
// =============================================================================

/**
 * Coordinates team activities to complete tasks.
 *
 * Enhanced with ResultSynthesizer integration for intelligent
 * merging of multi-agent outputs.
 */
export class TeamOrchestrator implements Orchestrator {
  private consensus: ConsensusEngine;
  private listeners: Set<CoordinationEventListener> = new Set();
  private synthesisConfig: OrchestratorSynthesisConfig;

  constructor(
    consensusStrategy: 'authority' | 'voting' | 'unanimous' | 'debate' | 'weighted' = 'authority',
    synthesisConfig: OrchestratorSynthesisConfig = {}
  ) {
    this.consensus = new ConsensusEngine(consensusStrategy);
    this.synthesisConfig = {
      enableSynthesis: false,
      conflictResolution: 'highest_confidence',
      deduplicationThreshold: 0.8,
      useLLM: false,
      ...synthesisConfig,
    };
  }

  /**
   * Configure synthesis options.
   */
  configureSynthesis(config: Partial<OrchestratorSynthesisConfig>): void {
    this.synthesisConfig = { ...this.synthesisConfig, ...config };
  }

  // ===========================================================================
  // TASK ASSIGNMENT
  // ===========================================================================

  /**
   * Assign a task to appropriate agents.
   */
  async assignTask(task: TeamTask, team: AgentTeam): Promise<string[]> {
    const assignedIds: string[] = [];

    // If task has subtasks, assign each subtask
    if (task.subtasks.length > 0) {
      for (const subtask of task.subtasks) {
        const agent = this.findBestAgent(subtask.description, team);
        if (agent) {
          subtask.assignedTo = agent.id;
          subtask.status = 'assigned';
          assignedIds.push(agent.id);

          // Send assignment message
          await team.channel.send(
            createTaskAssignment('orchestrator', agent.id, subtask.id, subtask.description)
          );
        }
      }
    } else {
      // Assign whole task to best matching agent(s)
      for (const capability of task.requiredCapabilities) {
        const agent = this.findAgentWithCapability(capability, team);
        if (agent && !assignedIds.includes(agent.id)) {
          assignedIds.push(agent.id);

          await team.channel.send(
            createTaskAssignment('orchestrator', agent.id, task.id, task.description)
          );
        }
      }

      // If no capabilities specified, assign to all
      if (task.requiredCapabilities.length === 0) {
        for (const agent of team.agents) {
          assignedIds.push(agent.id);
        }
      }
    }

    task.assignedAgents = assignedIds;
    task.status = 'assigned';

    this.emit({ type: 'task.assigned', taskId: task.id, agentIds: assignedIds });

    return assignedIds;
  }

  /**
   * Find the best agent for a task.
   */
  private findBestAgent(taskDescription: string, team: AgentTeam): Agent | undefined {
    // Simple keyword matching to find suitable agent
    const keywords = taskDescription.toLowerCase().split(/\s+/);

    const scores = team.agents.map((agent) => {
      let score = 0;

      // Check if agent capabilities match task keywords
      for (const capability of agent.role.capabilities) {
        for (const keyword of keywords) {
          if (capability.includes(keyword) || keyword.includes(capability.split('_')[0])) {
            score += 1;
          }
        }
      }

      // Prefer idle agents
      if (agent.state === 'idle') score += 0.5;

      // Consider authority for complex tasks
      if (keywords.includes('design') || keywords.includes('architect')) {
        score += agent.role.authority * 0.2;
      }

      return { agent, score };
    });

    // Sort by score and return best match
    scores.sort((a, b) => b.score - a.score);

    return scores[0]?.score > 0 ? scores[0].agent : team.agents[0];
  }

  /**
   * Find an agent with a specific capability.
   */
  private findAgentWithCapability(capability: string, team: AgentTeam): Agent | undefined {
    return team.agents.find((agent) =>
      canPerform(agent.role, capability) && agent.state === 'idle'
    ) || team.agents.find((agent) => canPerform(agent.role, capability));
  }

  // ===========================================================================
  // TASK COORDINATION
  // ===========================================================================

  /**
   * Coordinate task execution among agents.
   */
  async coordinate(task: TeamTask, team: AgentTeam): Promise<TeamTaskResult> {
    const startTime = performance.now();

    this.emit({ type: 'task.started', taskId: task.id });
    task.status = 'in_progress';

    const results: AgentResult[] = [];

    // Execute subtasks
    if (task.subtasks.length > 0) {
      // Parallel execution if enabled
      if (team.config.parallelExecution) {
        const subtaskResults = await Promise.all(
          task.subtasks.map((subtask) =>
            this.executeSubtask(subtask, team, task)
          )
        );
        results.push(...subtaskResults.filter((r): r is AgentResult => r !== null));
      } else {
        // Sequential execution
        for (const subtask of task.subtasks) {
          const result = await this.executeSubtask(subtask, team, task);
          if (result) results.push(result);
        }
      }
    } else {
      // Execute as single task with assigned agents
      for (const agentId of task.assignedAgents) {
        const agent = team.agents.find((a) => a.id === agentId);
        if (agent) {
          const result = await this.simulateAgentWork(agent, task.description);
          results.push(result);
          task.results.set(agentId, result);
        }
      }
    }

    // If multiple results, use synthesis or consensus
    let consensus: Decision | undefined;
    let finalOutput: string;
    let synthesisResult: any | undefined;

    if (results.length > 1) {
      if (this.synthesisConfig.enableSynthesis) {
        // Use structured synthesis for intelligent merging
        synthesisResult = await this.synthesizeResults(results, team);
        finalOutput = synthesisResult.mergedOutput || synthesisResult.output;

        // If synthesis detected conflicts, emit event
        if (synthesisResult.conflicts?.length > 0) {
          this.emit({ type: 'conflict.detected', opinions: synthesisResult.conflicts });
        }
      } else {
        // Fall back to consensus-based approach
        const opinions = results.map((r) =>
          createOpinion(r.agentId, r.output, 'Based on task execution', r.confidence)
        );

        consensus = await this.consensus.decide(opinions, team.agents);
        finalOutput = consensus.decision;
      }
    } else if (results.length === 1) {
      finalOutput = results[0].output;
    } else {
      finalOutput = 'No results produced';
    }

    // Review phase (if reviewer available)
    const reviewer = team.agents.find((a) => a.role.name === 'Reviewer');
    if (reviewer) {
      await this.requestReview(finalOutput, reviewer, team, task);
    }

    task.status = 'completed';
    task.completedAt = new Date();

    const taskResult: TeamTaskResult = {
      taskId: task.id,
      output: finalOutput,
      success: results.some((r) => !r.errors || r.errors.length === 0),
      agentResults: results,
      consensus,
      durationMs: performance.now() - startTime,
      summary: this.summarizeExecution(task, results),
    };

    this.emit({ type: 'task.completed', taskId: task.id, result: taskResult });

    return taskResult;
  }

  /**
   * Execute a subtask.
   */
  private async executeSubtask(
    subtask: Subtask,
    team: AgentTeam,
    parentTask: TeamTask
  ): Promise<AgentResult | null> {
    if (!subtask.assignedTo) return null;

    const agent = team.agents.find((a) => a.id === subtask.assignedTo);
    if (!agent) return null;

    subtask.status = 'in_progress';
    agent.state = 'working';

    const result = await this.simulateAgentWork(agent, subtask.description);

    subtask.status = result.errors?.length ? 'failed' : 'completed';
    subtask.result = result;
    agent.state = 'idle';

    return result;
  }

  /**
   * Simulate agent work (in real system, this would call LLM).
   */
  private async simulateAgentWork(
    agent: Agent,
    taskDescription: string
  ): Promise<AgentResult> {
    // Simulate work time
    await new Promise((r) => setTimeout(r, 50 + Math.random() * 100));

    const startTime = performance.now();

    // Simulate output based on role
    let output: string;
    let confidence: number;

    switch (agent.role.name) {
      case 'Coder':
        output = `// Implementation for: ${taskDescription}\nfunction solution() {\n  // Code here\n}`;
        confidence = 0.85;
        break;
      case 'Reviewer':
        output = `Review of "${taskDescription}":\n- Code structure: Good\n- Suggestions: Consider edge cases`;
        confidence = 0.9;
        break;
      case 'Tester':
        output = `Test results for: ${taskDescription}\n- Unit tests: Passed\n- Coverage: 80%`;
        confidence = 0.8;
        break;
      case 'Architect':
        output = `Design for: ${taskDescription}\n- Components: Module A, Module B\n- Pattern: MVC`;
        confidence = 0.95;
        break;
      default:
        output = `Completed: ${taskDescription}`;
        confidence = 0.75;
    }

    return {
      agentId: agent.id,
      output,
      confidence,
      durationMs: performance.now() - startTime,
    };
  }

  /**
   * Request review from reviewer agent.
   */
  private async requestReview(
    content: string,
    reviewer: Agent,
    team: AgentTeam,
    task: TeamTask
  ): Promise<void> {
    await team.channel.send(
      createReviewRequest('orchestrator', reviewer.id, content, task.id)
    );

    // Simulate review
    await new Promise((r) => setTimeout(r, 50));

    await team.channel.send(
      createReviewFeedback(reviewer.id, 'orchestrator', 'Looks good!', true, task.id)
    );
  }

  // ===========================================================================
  // CONFLICT RESOLUTION
  // ===========================================================================

  /**
   * Resolve conflicts between agents.
   */
  async resolveConflict(
    opinions: Opinion[],
    team: AgentTeam
  ): Promise<Decision> {
    this.emit({ type: 'conflict.detected', opinions });

    const decision = await this.consensus.decide(opinions, team.agents);

    this.emit({ type: 'conflict.resolved', decision });

    return decision;
  }

  // ===========================================================================
  // RESULT SYNTHESIS
  // ===========================================================================

  /**
   * Synthesize results from multiple agents using structured merging.
   */
  private async synthesizeResults(
    results: AgentResult[],
    team: AgentTeam
  ): Promise<{
    output: string;
    mergedOutput?: string;
    conflicts?: Array<{ type: string; description: string; resolution: string }>;
    deduplicatedFindings?: string[];
  }> {
    // Convert AgentResults to SynthesizerInput format
    const inputs: SynthesizerInput[] = results.map((r) => {
      const agent = team.agents.find((a) => a.id === r.agentId);
      return {
        agentId: r.agentId,
        content: r.output,
        type: this.inferOutputType(r.output),
        confidence: r.confidence,
        authority: agent?.role.authority,
        findings: this.extractFindings(r.output),
        errors: r.errors,
      };
    });

    // Detect conflicts between results
    const conflicts = this.detectResultConflicts(inputs);

    // If LLM synthesis is enabled and configured, use it
    if (this.synthesisConfig.useLLM && this.synthesisConfig.llmSynthesizer) {
      try {
        const llmResult = await this.synthesisConfig.llmSynthesizer(inputs, conflicts);
        return {
          output: llmResult.output,
          mergedOutput: llmResult.mergedOutput,
          conflicts: llmResult.conflicts,
          deduplicatedFindings: llmResult.findings,
        };
      } catch (error) {
        console.warn('[Orchestrator] LLM synthesis failed, using heuristic:', error);
      }
    }

    // Heuristic synthesis
    return this.heuristicSynthesis(inputs, conflicts);
  }

  /**
   * Infer the output type from content.
   */
  private inferOutputType(output: string): SynthesizerInput['type'] {
    const lower = output.toLowerCase();

    if (
      output.includes('function ') ||
      output.includes('class ') ||
      output.includes('const ') ||
      output.includes('import ') ||
      /^\s*(\/\/|\/\*|\*|#)/.test(output)
    ) {
      return 'code';
    }

    if (lower.includes('review') || lower.includes('suggestion')) {
      return 'review';
    }

    if (lower.includes('analysis') || lower.includes('finding')) {
      return 'analysis';
    }

    if (lower.includes('plan') || lower.includes('step 1')) {
      return 'plan';
    }

    if (lower.includes('research') || lower.includes('discovered')) {
      return 'research';
    }

    return 'mixed';
  }

  /**
   * Extract findings from output text.
   */
  private extractFindings(output: string): string[] {
    const findings: string[] = [];
    const bulletRegex = /^[\s]*[-*]\s+(.+)$/gm;
    let match;
    while ((match = bulletRegex.exec(output)) !== null) {
      findings.push(match[1].trim());
    }
    return findings;
  }

  /**
   * Detect conflicts between synthesizer inputs.
   */
  private detectResultConflicts(
    inputs: SynthesizerInput[]
  ): Array<{ type: string; description: string; inputIds: string[] }> {
    const conflicts: Array<{ type: string; description: string; inputIds: string[] }> = [];

    const codeInputs = inputs.filter((i) => i.type === 'code');
    if (codeInputs.length > 1) {
      const signatures = codeInputs.map((i) => {
        const funcMatch = i.content.match(/function\s+(\w+)\s*\([^)]*\)/);
        return funcMatch ? funcMatch[0] : null;
      });

      const uniqueSignatures = new Set(signatures.filter(Boolean));
      if (uniqueSignatures.size > 1) {
        conflicts.push({
          type: 'approach_mismatch',
          description: 'Multiple agents produced code with different function signatures',
          inputIds: codeInputs.map((i) => i.agentId),
        });
      }
    }

    return conflicts;
  }

  /**
   * Heuristic-based synthesis when LLM is not available.
   */
  private heuristicSynthesis(
    inputs: SynthesizerInput[],
    conflicts: Array<{ type: string; description: string; inputIds: string[] }>
  ): {
    output: string;
    mergedOutput?: string;
    conflicts?: Array<{ type: string; description: string; resolution: string }>;
    deduplicatedFindings?: string[];
  } {
    const resolvedConflicts = conflicts.map((c) => ({
      ...c,
      resolution: this.resolveConflictByStrategy(c, inputs),
    }));

    const allFindings = inputs.flatMap((i) => i.findings || []);
    const deduplicatedFindings = this.deduplicateFindings(allFindings);

    let mergedOutput: string;
    const primaryType = this.determinePrimaryType(inputs);

    switch (primaryType) {
      case 'code':
        mergedOutput = this.mergeCodeOutputs(inputs, resolvedConflicts);
        break;
      case 'research':
      case 'analysis':
        mergedOutput = this.mergeResearchOutputs(inputs, deduplicatedFindings);
        break;
      default:
        mergedOutput = this.selectByConfidence(inputs);
    }

    return {
      output: mergedOutput,
      mergedOutput,
      conflicts: resolvedConflicts,
      deduplicatedFindings,
    };
  }

  /**
   * Resolve a conflict using the configured strategy.
   */
  private resolveConflictByStrategy(
    conflict: { type: string; inputIds: string[] },
    inputs: SynthesizerInput[]
  ): string {
    const conflictingInputs = inputs.filter((i) => conflict.inputIds.includes(i.agentId));

    switch (this.synthesisConfig.conflictResolution) {
      case 'highest_confidence': {
        const best = conflictingInputs.reduce((a, b) => (a.confidence > b.confidence ? a : b));
        return `Resolved by highest confidence (${best.agentId})`;
      }
      case 'highest_authority': {
        const best = conflictingInputs.reduce((a, b) =>
          (a.authority ?? 0) > (b.authority ?? 0) ? a : b
        );
        return `Resolved by highest authority (${best.agentId})`;
      }
      case 'voting':
        return 'Resolved by voting';
      case 'merge_both':
      default:
        return 'Resolved by merging both approaches';
    }
  }

  /**
   * Deduplicate findings using similarity threshold.
   */
  private deduplicateFindings(findings: string[]): string[] {
    const threshold = this.synthesisConfig.deduplicationThreshold ?? 0.8;
    const unique: string[] = [];

    for (const finding of findings) {
      const isDuplicate = unique.some((u) => this.similarity(u, finding) >= threshold);
      if (!isDuplicate) {
        unique.push(finding);
      }
    }

    return unique;
  }

  /**
   * Calculate Jaccard similarity between two strings.
   */
  private similarity(a: string, b: string): number {
    const aWords = new Set(a.toLowerCase().split(/\s+/));
    const bWords = new Set(b.toLowerCase().split(/\s+/));
    const intersection = [...aWords].filter((w) => bWords.has(w)).length;
    const union = new Set([...aWords, ...bWords]).size;
    return union > 0 ? intersection / union : 0;
  }

  /**
   * Determine the primary output type from inputs.
   */
  private determinePrimaryType(inputs: SynthesizerInput[]): SynthesizerInput['type'] {
    const typeCounts = new Map<SynthesizerInput['type'], number>();
    for (const input of inputs) {
      typeCounts.set(input.type, (typeCounts.get(input.type) ?? 0) + 1);
    }

    let maxType: SynthesizerInput['type'] = 'mixed';
    let maxCount = 0;
    for (const [type, count] of typeCounts) {
      if (count > maxCount) {
        maxCount = count;
        maxType = type;
      }
    }
    return maxType;
  }

  /**
   * Merge code outputs intelligently.
   */
  private mergeCodeOutputs(
    inputs: SynthesizerInput[],
    conflicts: Array<{ type: string; resolution: string }>
  ): string {
    const codeInputs = inputs.filter((i) => i.type === 'code');
    if (codeInputs.length === 0) return this.selectByConfidence(inputs);

    if (conflicts.length === 0 || this.synthesisConfig.conflictResolution === 'merge_both') {
      return codeInputs
        .map((i) => `// From ${i.agentId} (confidence: ${i.confidence.toFixed(2)})\n${i.content}`)
        .join('\n\n');
    }

    let best: SynthesizerInput;
    if (this.synthesisConfig.conflictResolution === 'highest_authority') {
      best = codeInputs.reduce((a, b) => ((a.authority ?? 0) > (b.authority ?? 0) ? a : b));
    } else {
      best = codeInputs.reduce((a, b) => (a.confidence > b.confidence ? a : b));
    }
    return best.content;
  }

  /**
   * Merge research/analysis outputs.
   */
  private mergeResearchOutputs(inputs: SynthesizerInput[], deduplicatedFindings: string[]): string {
    const sections: string[] = [];
    const best = inputs.reduce((a, b) => (a.confidence > b.confidence ? a : b));
    sections.push(`## Summary\n${best.content.split('\n').slice(0, 5).join('\n')}`);

    if (deduplicatedFindings.length > 0) {
      sections.push(`## Key Findings\n${deduplicatedFindings.map((f) => `- ${f}`).join('\n')}`);
    }

    return sections.join('\n\n');
  }

  /**
   * Select output by highest confidence.
   */
  private selectByConfidence(inputs: SynthesizerInput[]): string {
    if (inputs.length === 0) return 'No results to synthesize';
    const best = inputs.reduce((a, b) => (a.confidence > b.confidence ? a : b));
    return best.content;
  }

  // ===========================================================================
  // PROGRESS TRACKING
  // ===========================================================================

  /**
   * Get task progress.
   */
  getProgress(task: TeamTask): TaskProgress {
    const subtasks = {
      total: task.subtasks.length,
      completed: task.subtasks.filter((s) => s.status === 'completed').length,
      inProgress: task.subtasks.filter((s) => s.status === 'in_progress').length,
      failed: task.subtasks.filter((s) => s.status === 'failed').length,
    };

    const percentage = subtasks.total > 0
      ? Math.round((subtasks.completed / subtasks.total) * 100)
      : task.status === 'completed' ? 100 : 0;

    return {
      percentage,
      phase: task.status,
      subtasks,
      agents: [], // Would include actual agent status
    };
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  /**
   * Summarize task execution.
   */
  private summarizeExecution(task: TeamTask, results: AgentResult[]): string {
    const successCount = results.filter((r) => !r.errors?.length).length;
    const totalDuration = results.reduce((sum, r) => sum + r.durationMs, 0);

    return `Task "${task.description}" completed. ${successCount}/${results.length} agents successful. Total time: ${totalDuration.toFixed(0)}ms`;
  }

  // ===========================================================================
  // EVENT HANDLING
  // ===========================================================================

  /**
   * Subscribe to events.
   */
  on(listener: CoordinationEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: CoordinationEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Error in coordination event listener:', err);
      }
    }
  }
}

// =============================================================================
// TEAM BUILDER
// =============================================================================

/**
 * Builds and configures agent teams.
 */
export class TeamBuilder {
  private agents: Agent[] = [];
  private config: Partial<import('./types.js').TeamConfig> = {};
  private name = 'Team';

  /**
   * Add an agent.
   */
  addAgent(agent: Agent): TeamBuilder {
    this.agents.push(agent);
    return this;
  }

  /**
   * Add multiple agents.
   */
  addAgents(agents: Agent[]): TeamBuilder {
    this.agents.push(...agents);
    return this;
  }

  /**
   * Set team name.
   */
  setName(name: string): TeamBuilder {
    this.name = name;
    return this;
  }

  /**
   * Configure consensus strategy.
   */
  setConsensusStrategy(strategy: import('./types.js').ConsensusStrategy): TeamBuilder {
    this.config.consensusStrategy = strategy;
    return this;
  }

  /**
   * Enable/disable parallel execution.
   */
  setParallelExecution(enabled: boolean): TeamBuilder {
    this.config.parallelExecution = enabled;
    return this;
  }

  /**
   * Build the team.
   */
  build(): AgentTeam {
    return {
      id: `team-${Date.now()}`,
      name: this.name,
      agents: this.agents,
      channel: new SimpleChannel(),
      config: {
        maxAgents: this.config.maxAgents ?? 5,
        consensusStrategy: this.config.consensusStrategy ?? 'authority',
        responseTimeout: this.config.responseTimeout ?? 30000,
        maxDebateRounds: this.config.maxDebateRounds ?? 3,
        parallelExecution: this.config.parallelExecution ?? true,
      },
    };
  }
}

// =============================================================================
// TASK BUILDER
// =============================================================================

let taskCounter = 0;

/**
 * Create a team task.
 */
export function createTeamTask(
  description: string,
  options: {
    requiredCapabilities?: string[];
    priority?: TeamTask['priority'];
    subtasks?: string[];
  } = {}
): TeamTask {
  taskCounter++;

  const subtasks: Subtask[] = (options.subtasks || []).map((desc, i) => ({
    id: `subtask-${taskCounter}-${i + 1}`,
    description: desc,
    status: 'pending',
  }));

  return {
    id: `task-${taskCounter}`,
    description,
    requiredCapabilities: options.requiredCapabilities || [],
    priority: options.priority || 'medium',
    status: 'pending',
    assignedAgents: [],
    subtasks,
    results: new Map(),
    createdAt: new Date(),
  };
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createOrchestrator(
  strategy: import('./types.js').ConsensusStrategy = 'authority',
  synthesisConfig?: OrchestratorSynthesisConfig
): TeamOrchestrator {
  return new TeamOrchestrator(strategy, synthesisConfig);
}

export function createTeamBuilder(): TeamBuilder {
  return new TeamBuilder();
}
