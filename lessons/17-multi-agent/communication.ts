/**
 * Lesson 17: Communication Channel
 *
 * Implements inter-agent communication.
 * Provides message passing, broadcasting, and history.
 */

import type {
  CommunicationChannel,
  Message,
  MessageType,
  MessageListener,
} from './types.js';

// =============================================================================
// MESSAGE ID GENERATOR
// =============================================================================

let messageCounter = 0;

function generateMessageId(): string {
  messageCounter++;
  return `msg-${Date.now()}-${messageCounter}`;
}

// =============================================================================
// SIMPLE COMMUNICATION CHANNEL
// =============================================================================

/**
 * A simple synchronous communication channel.
 */
export class SimpleChannel implements CommunicationChannel {
  id: string;
  messages: Message[] = [];
  private listeners: Set<MessageListener> = new Set();
  private maxHistory: number;

  constructor(id?: string, maxHistory = 1000) {
    this.id = id || `channel-${Date.now()}`;
    this.maxHistory = maxHistory;
  }

  /**
   * Subscribe to messages.
   */
  subscribe(listener: MessageListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Send a message to a specific agent.
   */
  async send(message: Message): Promise<void> {
    // Add to history
    this.messages.push(message);

    // Trim history if needed
    if (this.messages.length > this.maxHistory) {
      this.messages = this.messages.slice(-this.maxHistory);
    }

    // Notify listeners
    for (const listener of this.listeners) {
      try {
        listener(message);
      } catch (err) {
        console.error('Error in message listener:', err);
      }
    }
  }

  /**
   * Broadcast a message to all agents.
   */
  async broadcast(content: string, from: string): Promise<void> {
    const message: Message = {
      id: generateMessageId(),
      from,
      to: 'all',
      type: 'system',
      content,
      timestamp: new Date(),
      acknowledged: false,
    };

    await this.send(message);
  }

  /**
   * Get messages for a specific agent.
   */
  getMessagesFor(agentId: string): Message[] {
    return this.messages.filter(
      (m) => m.to === agentId || m.to === 'all'
    );
  }

  /**
   * Get messages from a specific agent.
   */
  getMessagesFrom(agentId: string): Message[] {
    return this.messages.filter((m) => m.from === agentId);
  }

  /**
   * Get messages of a specific type.
   */
  getMessagesByType(type: MessageType): Message[] {
    return this.messages.filter((m) => m.type === type);
  }

  /**
   * Get recent messages.
   */
  getRecentMessages(count = 10): Message[] {
    return this.messages.slice(-count);
  }

  /**
   * Clear message history.
   */
  clear(): void {
    this.messages = [];
  }

  /**
   * Acknowledge a message.
   */
  acknowledge(messageId: string): void {
    const message = this.messages.find((m) => m.id === messageId);
    if (message) {
      message.acknowledged = true;
    }
  }

  /**
   * Get unacknowledged messages for an agent.
   */
  getUnacknowledged(agentId: string): Message[] {
    return this.messages.filter(
      (m) => (m.to === agentId || m.to === 'all') && !m.acknowledged
    );
  }
}

// =============================================================================
// MESSAGE BUILDERS
// =============================================================================

/**
 * Build a task assignment message.
 */
export function createTaskAssignment(
  from: string,
  to: string,
  taskId: string,
  description: string
): Message {
  return {
    id: generateMessageId(),
    from,
    to,
    type: 'task_assignment',
    content: description,
    data: { taskId },
    timestamp: new Date(),
    acknowledged: false,
  };
}

/**
 * Build a task update message.
 */
export function createTaskUpdate(
  from: string,
  to: string,
  taskId: string,
  status: string,
  progress?: number
): Message {
  return {
    id: generateMessageId(),
    from,
    to,
    type: 'task_update',
    content: `Task ${taskId}: ${status}`,
    data: { taskId, status, progress },
    timestamp: new Date(),
    acknowledged: false,
  };
}

/**
 * Build a task completion message.
 */
export function createTaskComplete(
  from: string,
  taskId: string,
  result: string
): Message {
  return {
    id: generateMessageId(),
    from,
    to: 'all',
    type: 'task_complete',
    content: result,
    data: { taskId },
    timestamp: new Date(),
    acknowledged: false,
  };
}

/**
 * Build a question message.
 */
export function createQuestion(
  from: string,
  to: string,
  question: string
): Message {
  return {
    id: generateMessageId(),
    from,
    to,
    type: 'question',
    content: question,
    timestamp: new Date(),
    acknowledged: false,
  };
}

/**
 * Build an answer message.
 */
export function createAnswer(
  from: string,
  to: string,
  answer: string,
  questionId: string
): Message {
  return {
    id: generateMessageId(),
    from,
    to,
    type: 'answer',
    content: answer,
    data: { questionId },
    timestamp: new Date(),
    acknowledged: false,
  };
}

/**
 * Build an opinion message.
 */
export function createOpinion(
  from: string,
  position: string,
  reasoning: string,
  confidence: number
): Message {
  return {
    id: generateMessageId(),
    from,
    to: 'all',
    type: 'opinion',
    content: position,
    data: { reasoning, confidence },
    timestamp: new Date(),
    acknowledged: false,
  };
}

/**
 * Build a vote message.
 */
export function createVote(
  from: string,
  option: string,
  topicId: string
): Message {
  return {
    id: generateMessageId(),
    from,
    to: 'all',
    type: 'vote',
    content: option,
    data: { topicId },
    timestamp: new Date(),
    acknowledged: false,
  };
}

/**
 * Build a review request message.
 */
export function createReviewRequest(
  from: string,
  to: string,
  content: string,
  artifactId: string
): Message {
  return {
    id: generateMessageId(),
    from,
    to,
    type: 'review_request',
    content,
    data: { artifactId },
    timestamp: new Date(),
    acknowledged: false,
  };
}

/**
 * Build a review feedback message.
 */
export function createReviewFeedback(
  from: string,
  to: string,
  feedback: string,
  approved: boolean,
  requestId: string
): Message {
  return {
    id: generateMessageId(),
    from,
    to,
    type: 'review_feedback',
    content: feedback,
    data: { approved, requestId },
    timestamp: new Date(),
    acknowledged: false,
  };
}

// =============================================================================
// MESSAGE FORMATTING
// =============================================================================

/**
 * Format a message for display.
 */
export function formatMessage(message: Message): string {
  const direction = message.to === 'all' ? '→ all' : `→ ${message.to}`;
  const ack = message.acknowledged ? '✓' : '';

  return `[${message.timestamp.toISOString().slice(11, 19)}] ${message.from} ${direction} (${message.type}): ${message.content.slice(0, 50)}${message.content.length > 50 ? '...' : ''} ${ack}`;
}

/**
 * Format message history for display.
 */
export function formatHistory(messages: Message[], limit = 10): string {
  return messages
    .slice(-limit)
    .map(formatMessage)
    .join('\n');
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createChannel(id?: string): SimpleChannel {
  return new SimpleChannel(id);
}
