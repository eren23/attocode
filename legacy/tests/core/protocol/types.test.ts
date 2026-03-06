/**
 * Protocol Types Tests
 *
 * Comprehensive tests for Operation validation with Zod schemas
 * and type guard functions for both Operations and Events.
 */

import { describe, it, expect } from 'vitest';
import {
  OperationSchema,
  isUserTurn,
  isInterrupt,
  isExecApproval,
  isCompactApproval,
  isAgentMessage,
  isExecApprovalRequest,
  isCompactApprovalRequest,
  isTaskComplete,
  isError,
  type Operation,
  type OpUserTurn,
  type OpInterrupt,
  type OpExecApproval,
  type OpCompactApproval,
  type AgentEvent,
  type EventAgentMessage,
  type EventExecApprovalRequest,
  type EventCompactApprovalRequest,
  type EventTaskComplete,
  type EventError,
  type EventToolResult,
} from '../../../src/core/protocol/types.js';

// =============================================================================
// OPERATION VALIDATION WITH ZOD
// =============================================================================

describe('Operation Validation with Zod', () => {
  describe('OpUserTurn', () => {
    it('should accept valid user_turn operation', () => {
      const validOp = {
        type: 'user_turn',
        content: 'Hello, please help me with a task',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe('user_turn');
        expect((result.data as OpUserTurn).content).toBe('Hello, please help me with a task');
      }
    });

    it('should accept user_turn with attachments', () => {
      const validOp = {
        type: 'user_turn',
        content: 'Check this image',
        attachments: [
          { type: 'image', path: '/path/to/image.png', mimeType: 'image/png' },
          { type: 'file', data: 'YmFzZTY0IGNvbnRlbnQ=' },
        ],
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        const data = result.data as OpUserTurn;
        expect(data.attachments).toHaveLength(2);
        expect(data.attachments![0].type).toBe('image');
        expect(data.attachments![1].type).toBe('file');
      }
    });

    it('should reject user_turn with empty content', () => {
      const invalidOp = {
        type: 'user_turn',
        content: '',
      };

      const result = OperationSchema.safeParse(invalidOp);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.issues[0].message).toContain('empty');
      }
    });

    it('should reject user_turn with missing content', () => {
      const invalidOp = {
        type: 'user_turn',
      };

      const result = OperationSchema.safeParse(invalidOp);
      expect(result.success).toBe(false);
    });
  });

  describe('OpInterrupt', () => {
    it('should accept valid interrupt operation', () => {
      const validOp = {
        type: 'interrupt',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe('interrupt');
      }
    });

    it('should accept interrupt with optional reason', () => {
      const validOp = {
        type: 'interrupt',
        reason: 'User requested stop',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect((result.data as OpInterrupt).reason).toBe('User requested stop');
      }
    });
  });

  describe('OpExecApproval', () => {
    it('should accept valid exec_approval operation (approved)', () => {
      const validOp = {
        type: 'exec_approval',
        toolCallId: 'tool_123',
        approved: true,
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe('exec_approval');
        expect((result.data as OpExecApproval).approved).toBe(true);
      }
    });

    it('should accept exec_approval with persistent flag', () => {
      const validOp = {
        type: 'exec_approval',
        toolCallId: 'tool_456',
        approved: true,
        persistent: true,
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect((result.data as OpExecApproval).persistent).toBe(true);
      }
    });

    it('should accept exec_approval when rejected', () => {
      const validOp = {
        type: 'exec_approval',
        toolCallId: 'tool_789',
        approved: false,
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect((result.data as OpExecApproval).approved).toBe(false);
      }
    });

    it('should reject exec_approval without toolCallId', () => {
      const invalidOp = {
        type: 'exec_approval',
        approved: true,
      };

      const result = OperationSchema.safeParse(invalidOp);
      expect(result.success).toBe(false);
    });
  });

  describe('OpCompactApproval', () => {
    it('should accept valid compact_approval operation', () => {
      const validOp = {
        type: 'compact_approval',
        approved: true,
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe('compact_approval');
      }
    });

    it('should accept compact_approval with summarize strategy', () => {
      const validOp = {
        type: 'compact_approval',
        approved: true,
        strategy: 'summarize',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect((result.data as OpCompactApproval).strategy).toBe('summarize');
      }
    });

    it('should accept compact_approval with truncate strategy', () => {
      const validOp = {
        type: 'compact_approval',
        approved: true,
        strategy: 'truncate',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect((result.data as OpCompactApproval).strategy).toBe('truncate');
      }
    });

    it('should accept compact_approval with hybrid strategy', () => {
      const validOp = {
        type: 'compact_approval',
        approved: true,
        strategy: 'hybrid',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
      if (result.success) {
        expect((result.data as OpCompactApproval).strategy).toBe('hybrid');
      }
    });

    it('should reject compact_approval with invalid strategy', () => {
      const invalidOp = {
        type: 'compact_approval',
        approved: true,
        strategy: 'invalid_strategy',
      };

      const result = OperationSchema.safeParse(invalidOp);
      expect(result.success).toBe(false);
    });
  });

  describe('OpConfigureSession', () => {
    it('should accept valid configure_session operation', () => {
      const validOp = {
        type: 'configure_session',
        config: {
          model: 'claude-3-opus',
          maxIterations: 50,
          autoCompact: true,
          approvalPolicy: 'on_request',
        },
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
    });

    it('should accept configure_session with empty config', () => {
      const validOp = {
        type: 'configure_session',
        config: {},
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
    });

    it('should reject configure_session with invalid approvalPolicy', () => {
      const invalidOp = {
        type: 'configure_session',
        config: {
          approvalPolicy: 'sometimes',
        },
      };

      const result = OperationSchema.safeParse(invalidOp);
      expect(result.success).toBe(false);
    });
  });

  describe('OpSwitchSession', () => {
    it('should accept valid switch_session operation', () => {
      const validOp = {
        type: 'switch_session',
        sessionId: 'session_abc123',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
    });
  });

  describe('OpForkSession', () => {
    it('should accept valid fork_session operation', () => {
      const validOp = {
        type: 'fork_session',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
    });

    it('should accept fork_session with optional name', () => {
      const validOp = {
        type: 'fork_session',
        name: 'experimental-branch',
      };

      const result = OperationSchema.safeParse(validOp);
      expect(result.success).toBe(true);
    });
  });

  describe('Unknown Operation Types', () => {
    it('should reject unknown operation type', () => {
      const invalidOp = {
        type: 'unknown_operation',
        data: 'some data',
      };

      const result = OperationSchema.safeParse(invalidOp);
      expect(result.success).toBe(false);
    });

    it('should reject operation with missing type', () => {
      const invalidOp = {
        content: 'hello',
      };

      const result = OperationSchema.safeParse(invalidOp);
      expect(result.success).toBe(false);
    });

    it('should reject null operation', () => {
      const result = OperationSchema.safeParse(null);
      expect(result.success).toBe(false);
    });

    it('should reject undefined operation', () => {
      const result = OperationSchema.safeParse(undefined);
      expect(result.success).toBe(false);
    });
  });
});

// =============================================================================
// OPERATION TYPE GUARDS
// =============================================================================

describe('Operation Type Guards', () => {
  // Sample operations for testing
  const userTurnOp: OpUserTurn = {
    type: 'user_turn',
    content: 'Hello world',
  };

  const interruptOp: OpInterrupt = {
    type: 'interrupt',
    reason: 'User cancelled',
  };

  const execApprovalOp: OpExecApproval = {
    type: 'exec_approval',
    toolCallId: 'tool_123',
    approved: true,
  };

  const compactApprovalOp: OpCompactApproval = {
    type: 'compact_approval',
    approved: true,
    strategy: 'summarize',
  };

  describe('isUserTurn', () => {
    it('should return true for user_turn operation', () => {
      expect(isUserTurn(userTurnOp)).toBe(true);
    });

    it('should return false for interrupt operation', () => {
      expect(isUserTurn(interruptOp)).toBe(false);
    });

    it('should return false for exec_approval operation', () => {
      expect(isUserTurn(execApprovalOp)).toBe(false);
    });

    it('should return false for compact_approval operation', () => {
      expect(isUserTurn(compactApprovalOp)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const op: Operation = userTurnOp;
      if (isUserTurn(op)) {
        // TypeScript should know op.content exists here
        expect(op.content).toBe('Hello world');
      }
    });
  });

  describe('isInterrupt', () => {
    it('should return true for interrupt operation', () => {
      expect(isInterrupt(interruptOp)).toBe(true);
    });

    it('should return false for user_turn operation', () => {
      expect(isInterrupt(userTurnOp)).toBe(false);
    });

    it('should return false for exec_approval operation', () => {
      expect(isInterrupt(execApprovalOp)).toBe(false);
    });

    it('should return false for compact_approval operation', () => {
      expect(isInterrupt(compactApprovalOp)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const op: Operation = interruptOp;
      if (isInterrupt(op)) {
        // TypeScript should know op.reason exists here
        expect(op.reason).toBe('User cancelled');
      }
    });
  });

  describe('isExecApproval', () => {
    it('should return true for exec_approval operation', () => {
      expect(isExecApproval(execApprovalOp)).toBe(true);
    });

    it('should return false for user_turn operation', () => {
      expect(isExecApproval(userTurnOp)).toBe(false);
    });

    it('should return false for interrupt operation', () => {
      expect(isExecApproval(interruptOp)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const op: Operation = execApprovalOp;
      if (isExecApproval(op)) {
        expect(op.toolCallId).toBe('tool_123');
        expect(op.approved).toBe(true);
      }
    });
  });

  describe('isCompactApproval', () => {
    it('should return true for compact_approval operation', () => {
      expect(isCompactApproval(compactApprovalOp)).toBe(true);
    });

    it('should return false for user_turn operation', () => {
      expect(isCompactApproval(userTurnOp)).toBe(false);
    });

    it('should return false for interrupt operation', () => {
      expect(isCompactApproval(interruptOp)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const op: Operation = compactApprovalOp;
      if (isCompactApproval(op)) {
        expect(op.approved).toBe(true);
        expect(op.strategy).toBe('summarize');
      }
    });
  });
});

// =============================================================================
// EVENT TYPE GUARDS
// =============================================================================

describe('Event Type Guards', () => {
  // Sample events for testing
  const agentMessageEvent: EventAgentMessage = {
    type: 'agent_message',
    content: 'I will help you with that task.',
    done: false,
    model: 'claude-3-opus',
  };

  const execApprovalRequestEvent: EventExecApprovalRequest = {
    type: 'exec_approval_request',
    toolCallId: 'tool_456',
    toolName: 'bash',
    toolArgs: { command: 'ls -la' },
    risk: 'moderate',
    description: 'List directory contents',
  };

  const compactApprovalRequestEvent: EventCompactApprovalRequest = {
    type: 'compact_approval_request',
    currentTokens: 180000,
    maxTokens: 200000,
    proposedStrategy: 'hybrid',
    estimatedTokensAfter: 80000,
    summaryPreview: 'Summary of previous conversation...',
  };

  const taskCompleteEvent: EventTaskComplete = {
    type: 'task_complete',
    usage: {
      inputTokens: 1000,
      outputTokens: 500,
      totalTokens: 1500,
    },
    status: 'success',
    durationMs: 5000,
  };

  const errorEvent: EventError = {
    type: 'error',
    code: 'RATE_LIMIT',
    message: 'Rate limit exceeded',
    recoverable: true,
    stack: 'Error: Rate limit exceeded\n    at ...',
  };

  const toolResultEvent: EventToolResult = {
    type: 'tool_result',
    toolCallId: 'tool_789',
    toolName: 'read_file',
    result: 'file contents here',
    durationMs: 100,
  };

  describe('isAgentMessage', () => {
    it('should return true for agent_message event', () => {
      expect(isAgentMessage(agentMessageEvent)).toBe(true);
    });

    it('should return false for error event', () => {
      expect(isAgentMessage(errorEvent)).toBe(false);
    });

    it('should return false for task_complete event', () => {
      expect(isAgentMessage(taskCompleteEvent)).toBe(false);
    });

    it('should return false for tool_result event', () => {
      expect(isAgentMessage(toolResultEvent)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const event: AgentEvent = agentMessageEvent;
      if (isAgentMessage(event)) {
        expect(event.content).toBe('I will help you with that task.');
        expect(event.done).toBe(false);
        expect(event.model).toBe('claude-3-opus');
      }
    });
  });

  describe('isExecApprovalRequest', () => {
    it('should return true for exec_approval_request event', () => {
      expect(isExecApprovalRequest(execApprovalRequestEvent)).toBe(true);
    });

    it('should return false for agent_message event', () => {
      expect(isExecApprovalRequest(agentMessageEvent)).toBe(false);
    });

    it('should return false for error event', () => {
      expect(isExecApprovalRequest(errorEvent)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const event: AgentEvent = execApprovalRequestEvent;
      if (isExecApprovalRequest(event)) {
        expect(event.toolName).toBe('bash');
        expect(event.risk).toBe('moderate');
      }
    });
  });

  describe('isCompactApprovalRequest', () => {
    it('should return true for compact_approval_request event', () => {
      expect(isCompactApprovalRequest(compactApprovalRequestEvent)).toBe(true);
    });

    it('should return false for agent_message event', () => {
      expect(isCompactApprovalRequest(agentMessageEvent)).toBe(false);
    });

    it('should return false for error event', () => {
      expect(isCompactApprovalRequest(errorEvent)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const event: AgentEvent = compactApprovalRequestEvent;
      if (isCompactApprovalRequest(event)) {
        expect(event.currentTokens).toBe(180000);
        expect(event.proposedStrategy).toBe('hybrid');
      }
    });
  });

  describe('isTaskComplete', () => {
    it('should return true for task_complete event', () => {
      expect(isTaskComplete(taskCompleteEvent)).toBe(true);
    });

    it('should return false for agent_message event', () => {
      expect(isTaskComplete(agentMessageEvent)).toBe(false);
    });

    it('should return false for error event', () => {
      expect(isTaskComplete(errorEvent)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const event: AgentEvent = taskCompleteEvent;
      if (isTaskComplete(event)) {
        expect(event.status).toBe('success');
        expect(event.durationMs).toBe(5000);
        expect(event.usage.totalTokens).toBe(1500);
      }
    });
  });

  describe('isError', () => {
    it('should return true for error event', () => {
      expect(isError(errorEvent)).toBe(true);
    });

    it('should return false for agent_message event', () => {
      expect(isError(agentMessageEvent)).toBe(false);
    });

    it('should return false for task_complete event', () => {
      expect(isError(taskCompleteEvent)).toBe(false);
    });

    it('should return false for tool_result event', () => {
      expect(isError(toolResultEvent)).toBe(false);
    });

    it('should narrow type correctly', () => {
      const event: AgentEvent = errorEvent;
      if (isError(event)) {
        expect(event.code).toBe('RATE_LIMIT');
        expect(event.message).toBe('Rate limit exceeded');
        expect(event.recoverable).toBe(true);
      }
    });

    it('should handle non-recoverable errors', () => {
      const fatalError: EventError = {
        type: 'error',
        code: 'FATAL',
        message: 'Unrecoverable error',
        recoverable: false,
      };

      expect(isError(fatalError)).toBe(true);
      if (isError(fatalError)) {
        expect(fatalError.recoverable).toBe(false);
      }
    });
  });
});
