/**
 * Lesson 17: Multi-Agent Coordination Types
 *
 * Type definitions for multi-agent systems - roles, communication,
 * and coordination protocols.
 */

// =============================================================================
// AGENT TYPES
// =============================================================================

/**
 * Represents an agent with a specific role.
 */
export interface Agent {
  /** Unique agent identifier */
  id: string;

  /** Agent's role */
  role: AgentRole;

  /** Agent's current state */
  state: AgentState;

  /** Agent's memory/context */
  memory: AgentMemory[];
}

/**
 * Defines an agent's role and capabilities.
 */
export interface AgentRole {
  /** Role name */
  name: string;

  /** Description of the role */
  description: string;

  /** What this role can do */
  capabilities: string[];

  /** System prompt for this role */
  systemPrompt: string;

  /** Tools available to this role */
  tools: string[];

  /** Priority in decision making (higher = more authority) */
  authority: number;

  /** Maximum concurrent tasks */
  maxConcurrentTasks: number;
}

/**
 * Agent's current state.
 */
export type AgentState =
  | 'idle'
  | 'working'
  | 'waiting'
  | 'blocked'
  | 'completed'
  | 'failed';

/**
 * A memory entry for an agent.
 */
export interface AgentMemory {
  /** Content of the memory */
  content: string;

  /** When created */
  timestamp: Date;

  /** Source (self, other agent, system) */
  source: string;
}

// =============================================================================
// TEAM TYPES
// =============================================================================

/**
 * A team of agents working together.
 */
export interface AgentTeam {
  /** Team identifier */
  id: string;

  /** Team name */
  name: string;

  /** Agents in the team */
  agents: Agent[];

  /** Communication channel */
  channel: CommunicationChannel;

  /** Team's current task */
  currentTask?: TeamTask;

  /** Team configuration */
  config: TeamConfig;
}

/**
 * Configuration for a team.
 */
export interface TeamConfig {
  /** Maximum team size */
  maxAgents: number;

  /** Consensus strategy for decisions */
  consensusStrategy: ConsensusStrategy;

  /** Timeout for agent responses (ms) */
  responseTimeout: number;

  /** Maximum rounds of debate */
  maxDebateRounds: number;

  /** Enable parallel execution */
  parallelExecution: boolean;
}

/**
 * Default team configuration.
 */
export const DEFAULT_TEAM_CONFIG: TeamConfig = {
  maxAgents: 5,
  consensusStrategy: 'authority',
  responseTimeout: 30000,
  maxDebateRounds: 3,
  parallelExecution: true,
};

// =============================================================================
// TASK TYPES
// =============================================================================

/**
 * A task assigned to the team.
 */
export interface TeamTask {
  /** Task identifier */
  id: string;

  /** Task description */
  description: string;

  /** Required capabilities */
  requiredCapabilities: string[];

  /** Task priority */
  priority: 'low' | 'medium' | 'high' | 'critical';

  /** Current status */
  status: TaskStatus;

  /** Assigned agents */
  assignedAgents: string[];

  /** Subtasks */
  subtasks: Subtask[];

  /** Results from each agent */
  results: Map<string, AgentResult>;

  /** Created timestamp */
  createdAt: Date;

  /** Completed timestamp */
  completedAt?: Date;
}

/**
 * A subtask within a team task.
 */
export interface Subtask {
  /** Subtask identifier */
  id: string;

  /** Description */
  description: string;

  /** Assigned agent ID */
  assignedTo?: string;

  /** Status */
  status: TaskStatus;

  /** Result */
  result?: AgentResult;
}

/**
 * Task status.
 */
export type TaskStatus =
  | 'pending'
  | 'assigned'
  | 'in_progress'
  | 'review'
  | 'completed'
  | 'failed';

/**
 * Result from an agent.
 */
export interface AgentResult {
  /** Agent who produced this */
  agentId: string;

  /** The output */
  output: string;

  /** Confidence in the result (0-1) */
  confidence: number;

  /** Time taken (ms) */
  durationMs: number;

  /** Any artifacts produced */
  artifacts?: Artifact[];

  /** Errors encountered */
  errors?: string[];
}

/**
 * An artifact produced by an agent.
 */
export interface Artifact {
  /** Artifact type */
  type: 'code' | 'document' | 'data' | 'image' | 'other';

  /** Artifact name */
  name: string;

  /** Content or path */
  content: string;
}

// =============================================================================
// COMMUNICATION TYPES
// =============================================================================

/**
 * A channel for agent communication.
 */
export interface CommunicationChannel {
  /** Channel identifier */
  id: string;

  /** Message history */
  messages: Message[];

  /** Subscribe to messages */
  subscribe(listener: MessageListener): () => void;

  /** Send a message */
  send(message: Message): Promise<void>;

  /** Broadcast to all agents */
  broadcast(content: string, from: string): Promise<void>;
}

/**
 * A message between agents.
 */
export interface Message {
  /** Message identifier */
  id: string;

  /** Sender agent ID */
  from: string;

  /** Recipient agent ID (or 'all' for broadcast) */
  to: string;

  /** Message type */
  type: MessageType;

  /** Message content */
  content: string;

  /** Additional data */
  data?: Record<string, unknown>;

  /** Timestamp */
  timestamp: Date;

  /** Whether acknowledged */
  acknowledged: boolean;
}

/**
 * Types of messages.
 */
export type MessageType =
  | 'task_assignment'    // Assigning a task
  | 'task_update'        // Progress update
  | 'task_complete'      // Task finished
  | 'question'           // Asking for input
  | 'answer'             // Response to question
  | 'opinion'            // Sharing perspective
  | 'vote'               // Casting a vote
  | 'review_request'     // Requesting review
  | 'review_feedback'    // Providing review
  | 'conflict'           // Reporting conflict
  | 'resolution'         // Conflict resolution
  | 'system';            // System message

/**
 * Listener for messages.
 */
export type MessageListener = (message: Message) => void;

// =============================================================================
// CONSENSUS TYPES
// =============================================================================

/**
 * Strategies for reaching consensus.
 */
export type ConsensusStrategy =
  | 'authority'   // Highest authority agent decides
  | 'voting'      // Majority vote
  | 'unanimous'   // All must agree
  | 'debate'      // Discuss until agreement
  | 'weighted';   // Weighted by confidence/authority

/**
 * An opinion from an agent.
 */
export interface Opinion {
  /** Agent who holds this opinion */
  agentId: string;

  /** The opinion/decision */
  position: string;

  /** Reasoning */
  reasoning: string;

  /** Confidence level (0-1) */
  confidence: number;

  /** Supporting evidence */
  evidence?: string[];
}

/**
 * A decision made by consensus.
 */
export interface Decision {
  /** The decision made */
  decision: string;

  /** How it was decided */
  method: ConsensusStrategy;

  /** Opinions considered */
  opinions: Opinion[];

  /** Support level (0-1) */
  support: number;

  /** Dissenting opinions */
  dissent: Opinion[];

  /** Timestamp */
  timestamp: Date;
}

/**
 * Result of a vote.
 */
export interface VoteResult {
  /** The options voted on */
  options: string[];

  /** Votes per option */
  votes: Map<string, string[]>; // option -> agent IDs

  /** Winner */
  winner: string;

  /** Whether unanimous */
  unanimous: boolean;

  /** Support percentage */
  supportPercentage: number;
}

// =============================================================================
// ORCHESTRATION TYPES
// =============================================================================

/**
 * Orchestrator interface.
 */
export interface Orchestrator {
  /** Assign a task to the appropriate agent(s) */
  assignTask(task: TeamTask, team: AgentTeam): Promise<string[]>;

  /** Coordinate task execution */
  coordinate(task: TeamTask, team: AgentTeam): Promise<TeamTaskResult>;

  /** Resolve conflicts between agents */
  resolveConflict(opinions: Opinion[], team: AgentTeam): Promise<Decision>;

  /** Monitor team progress */
  getProgress(task: TeamTask): TaskProgress;
}

/**
 * Result of a team task.
 */
export interface TeamTaskResult {
  /** Task ID */
  taskId: string;

  /** Final output */
  output: string;

  /** Success status */
  success: boolean;

  /** Individual results */
  agentResults: AgentResult[];

  /** Consensus decision (if any) */
  consensus?: Decision;

  /** Total duration */
  durationMs: number;

  /** Summary of execution */
  summary: string;
}

/**
 * Progress of a task.
 */
export interface TaskProgress {
  /** Overall progress (0-100) */
  percentage: number;

  /** Current phase */
  phase: string;

  /** Subtask progress */
  subtasks: {
    total: number;
    completed: number;
    inProgress: number;
    failed: number;
  };

  /** Agent status */
  agents: {
    agentId: string;
    state: AgentState;
    currentSubtask?: string;
  }[];
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Events in multi-agent coordination.
 */
export type CoordinationEvent =
  | { type: 'team.created'; team: AgentTeam }
  | { type: 'agent.joined'; agentId: string; teamId: string }
  | { type: 'agent.left'; agentId: string; teamId: string }
  | { type: 'task.assigned'; taskId: string; agentIds: string[] }
  | { type: 'task.started'; taskId: string }
  | { type: 'task.progress'; taskId: string; progress: TaskProgress }
  | { type: 'task.completed'; taskId: string; result: TeamTaskResult }
  | { type: 'conflict.detected'; opinions: Opinion[] }
  | { type: 'conflict.resolved'; decision: Decision }
  | { type: 'message.sent'; message: Message };

/**
 * Listener for coordination events.
 */
export type CoordinationEventListener = (event: CoordinationEvent) => void;
