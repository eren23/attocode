/**
 * Op/Event Protocol Types
 *
 * Codex-inspired protocol layer for clean UI/agent separation.
 * Operations flow from client to agent, Events flow from agent to client.
 */

import { z } from 'zod';
import type { TokenUsage } from '../../types.js';

// =============================================================================
// BASIC TYPES
// =============================================================================

/**
 * Unique identifier for a submission (operation sent to agent).
 */
export type SubmissionId = string;

/**
 * Risk level for tool execution.
 */
export type RiskLevel = 'safe' | 'moderate' | 'dangerous';

/**
 * Attachment for user messages (images, files).
 */
export interface Attachment {
  type: 'image' | 'file';
  path?: string;
  data?: string; // base64 encoded
  mimeType?: string;
}

// =============================================================================
// OPERATIONS (Client -> Agent)
// =============================================================================

/**
 * User sends a message/turn to the agent.
 */
export interface OpUserTurn {
  type: 'user_turn';
  content: string;
  attachments?: Attachment[];
}

/**
 * User requests to interrupt the current operation.
 */
export interface OpInterrupt {
  type: 'interrupt';
  reason?: string;
}

/**
 * User responds to an execution approval request.
 */
export interface OpExecApproval {
  type: 'exec_approval';
  toolCallId: string;
  approved: boolean;
  /** If true, auto-approve similar operations in this session */
  persistent?: boolean;
}

/**
 * User responds to a context compaction approval request.
 */
export interface OpCompactApproval {
  type: 'compact_approval';
  approved: boolean;
  strategy?: 'summarize' | 'truncate' | 'hybrid';
}

/**
 * User configures session settings.
 */
export interface OpConfigureSession {
  type: 'configure_session';
  config: {
    model?: string;
    maxIterations?: number;
    autoCompact?: boolean;
    approvalPolicy?: 'never' | 'on_request' | 'always';
  };
}

/**
 * User switches to a different session.
 */
export interface OpSwitchSession {
  type: 'switch_session';
  sessionId: string;
}

/**
 * User forks the current session.
 */
export interface OpForkSession {
  type: 'fork_session';
  name?: string;
}

/**
 * Union of all operation types.
 */
export type Operation =
  | OpUserTurn
  | OpInterrupt
  | OpExecApproval
  | OpCompactApproval
  | OpConfigureSession
  | OpSwitchSession
  | OpForkSession;

/**
 * A submission wraps an operation with metadata.
 */
export interface Submission {
  id: SubmissionId;
  op: Operation;
  timestamp: number;
  /** Optional correlation ID for request/response tracking */
  correlationId?: string;
}

// =============================================================================
// EVENTS (Agent -> Client)
// =============================================================================

/**
 * Agent sends a message (streaming or complete).
 */
export interface EventAgentMessage {
  type: 'agent_message';
  content: string;
  /** True when message is complete (no more chunks) */
  done: boolean;
  model?: string;
}

/**
 * Agent requests approval to execute a tool.
 */
export interface EventExecApprovalRequest {
  type: 'exec_approval_request';
  toolCallId: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  risk: RiskLevel;
  description?: string;
}

/**
 * Agent requests approval to compact context.
 */
export interface EventCompactApprovalRequest {
  type: 'compact_approval_request';
  currentTokens: number;
  maxTokens: number;
  proposedStrategy: 'summarize' | 'truncate' | 'hybrid';
  estimatedTokensAfter: number;
  summaryPreview?: string;
}

/**
 * Agent signals task completion.
 */
export interface EventTaskComplete {
  type: 'task_complete';
  usage: TokenUsage;
  status: 'success' | 'interrupted' | 'error';
  durationMs: number;
}

/**
 * Streaming output from tool execution (stdout/stderr).
 */
export interface EventExecOutput {
  type: 'exec_output';
  toolCallId: string;
  stream: 'stdout' | 'stderr';
  data: string;
}

/**
 * Tool execution result.
 */
export interface EventToolResult {
  type: 'tool_result';
  toolCallId: string;
  toolName: string;
  result: unknown;
  error?: string;
  durationMs: number;
}

/**
 * Error event.
 */
export interface EventError {
  type: 'error';
  code: string;
  message: string;
  recoverable: boolean;
  stack?: string;
}

/**
 * Token count update.
 */
export interface EventTokenCount {
  type: 'token_count';
  input: number;
  output: number;
  cached?: number;
  total: number;
}

/**
 * Session lifecycle events.
 */
export interface EventSession {
  type: 'session';
  action: 'created' | 'loaded' | 'switched' | 'forked' | 'compacted';
  sessionId: string;
  parentSessionId?: string;
  name?: string;
}

/**
 * Union of all event types.
 */
export type AgentEvent =
  | EventAgentMessage
  | EventExecApprovalRequest
  | EventCompactApprovalRequest
  | EventTaskComplete
  | EventExecOutput
  | EventToolResult
  | EventError
  | EventTokenCount
  | EventSession;

/**
 * An event envelope wraps an event with metadata.
 */
export interface EventEnvelope {
  submissionId: SubmissionId;
  event: AgentEvent;
  timestamp: number;
}

// =============================================================================
// ZOD SCHEMAS (Runtime Validation)
// =============================================================================

/**
 * Schema for Attachment.
 */
export const AttachmentSchema = z.object({
  type: z.enum(['image', 'file']),
  path: z.string().optional(),
  data: z.string().optional(),
  mimeType: z.string().optional(),
});

/**
 * Schema for OpUserTurn - content must be non-empty.
 */
export const OpUserTurnSchema = z.object({
  type: z.literal('user_turn'),
  content: z.string().min(1, 'Content must not be empty'),
  attachments: z.array(AttachmentSchema).optional(),
});

/**
 * Schema for OpInterrupt.
 */
export const OpInterruptSchema = z.object({
  type: z.literal('interrupt'),
  reason: z.string().optional(),
});

/**
 * Schema for OpExecApproval.
 */
export const OpExecApprovalSchema = z.object({
  type: z.literal('exec_approval'),
  toolCallId: z.string(),
  approved: z.boolean(),
  persistent: z.boolean().optional(),
});

/**
 * Schema for OpCompactApproval.
 */
export const OpCompactApprovalSchema = z.object({
  type: z.literal('compact_approval'),
  approved: z.boolean(),
  strategy: z.enum(['summarize', 'truncate', 'hybrid']).optional(),
});

/**
 * Schema for OpConfigureSession.
 */
export const OpConfigureSessionSchema = z.object({
  type: z.literal('configure_session'),
  config: z.object({
    model: z.string().optional(),
    maxIterations: z.number().int().positive().optional(),
    autoCompact: z.boolean().optional(),
    approvalPolicy: z.enum(['never', 'on_request', 'always']).optional(),
  }),
});

/**
 * Schema for OpSwitchSession.
 */
export const OpSwitchSessionSchema = z.object({
  type: z.literal('switch_session'),
  sessionId: z.string(),
});

/**
 * Schema for OpForkSession.
 */
export const OpForkSessionSchema = z.object({
  type: z.literal('fork_session'),
  name: z.string().optional(),
});

/**
 * Discriminated union schema for all operations.
 */
export const OperationSchema = z.discriminatedUnion('type', [
  OpUserTurnSchema,
  OpInterruptSchema,
  OpExecApprovalSchema,
  OpCompactApprovalSchema,
  OpConfigureSessionSchema,
  OpSwitchSessionSchema,
  OpForkSessionSchema,
]);

// =============================================================================
// TYPE GUARDS
// =============================================================================

// Operation type guards

/**
 * Type guard for OpUserTurn.
 */
export function isUserTurn(op: Operation): op is OpUserTurn {
  return op.type === 'user_turn';
}

/**
 * Type guard for OpInterrupt.
 */
export function isInterrupt(op: Operation): op is OpInterrupt {
  return op.type === 'interrupt';
}

/**
 * Type guard for OpExecApproval.
 */
export function isExecApproval(op: Operation): op is OpExecApproval {
  return op.type === 'exec_approval';
}

/**
 * Type guard for OpCompactApproval.
 */
export function isCompactApproval(op: Operation): op is OpCompactApproval {
  return op.type === 'compact_approval';
}

// Event type guards

/**
 * Type guard for EventAgentMessage.
 */
export function isAgentMessage(event: AgentEvent): event is EventAgentMessage {
  return event.type === 'agent_message';
}

/**
 * Type guard for EventExecApprovalRequest.
 */
export function isExecApprovalRequest(event: AgentEvent): event is EventExecApprovalRequest {
  return event.type === 'exec_approval_request';
}

/**
 * Type guard for EventCompactApprovalRequest.
 */
export function isCompactApprovalRequest(event: AgentEvent): event is EventCompactApprovalRequest {
  return event.type === 'compact_approval_request';
}

/**
 * Type guard for EventTaskComplete.
 */
export function isTaskComplete(event: AgentEvent): event is EventTaskComplete {
  return event.type === 'task_complete';
}

/**
 * Type guard for EventError.
 */
export function isError(event: AgentEvent): event is EventError {
  return event.type === 'error';
}
