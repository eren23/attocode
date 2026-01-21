/**
 * Lesson 17: Orchestrator
 *
 * Coordinates multiple agents to complete tasks.
 * Handles task assignment, execution, and result aggregation.
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
// TEAM ORCHESTRATOR
// =============================================================================

/**
 * Coordinates team activities to complete tasks.
 */
export class TeamOrchestrator implements Orchestrator {
  private consensus: ConsensusEngine;
  private listeners: Set<CoordinationEventListener> = new Set();

  constructor(consensusStrategy: 'authority' | 'voting' | 'unanimous' | 'debate' | 'weighted' = 'authority') {
    this.consensus = new ConsensusEngine(consensusStrategy);
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

    // If multiple results, reach consensus on final output
    let consensus: Decision | undefined;
    let finalOutput: string;

    if (results.length > 1) {
      const opinions = results.map((r) =>
        createOpinion(r.agentId, r.output, 'Based on task execution', r.confidence)
      );

      consensus = await this.consensus.decide(opinions, team.agents);
      finalOutput = consensus.decision;
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
  strategy: import('./types.js').ConsensusStrategy = 'authority'
): TeamOrchestrator {
  return new TeamOrchestrator(strategy);
}

export function createTeamBuilder(): TeamBuilder {
  return new TeamBuilder();
}
