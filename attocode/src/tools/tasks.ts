/**
 * Task Tools - Claude Code-style Task Management
 *
 * Provides LLM-accessible tools for task management:
 * - task_create: Create new tasks with subject, description, activeForm
 * - task_update: Update task status, dependencies, metadata
 * - task_get: Get full task details
 * - task_list: List all tasks with summaries
 */

import type { ToolDefinition } from '../types.js';
import type { TaskManager, Task, CreateTaskOptions, UpdateTaskOptions, TaskStatus } from '../integrations/task-manager.js';

// =============================================================================
// TOOL PARAMETERS
// =============================================================================

const taskCreateParameters = {
  type: 'object',
  properties: {
    subject: {
      type: 'string',
      description: 'Brief title in imperative form (e.g., "Fix authentication bug", "Add user validation")',
    },
    description: {
      type: 'string',
      description: 'Detailed description of what needs to be done, including context and acceptance criteria',
    },
    activeForm: {
      type: 'string',
      description: 'Present continuous form shown in spinner when task is in_progress (e.g., "Fixing authentication bug")',
    },
    metadata: {
      type: 'object',
      description: 'Optional metadata to attach to the task',
    },
  },
  required: ['subject', 'description'],
};

const taskUpdateParameters = {
  type: 'object',
  properties: {
    taskId: {
      type: 'string',
      description: 'The ID of the task to update (e.g., "1" or "task-1")',
    },
    status: {
      type: 'string',
      enum: ['pending', 'in_progress', 'completed', 'deleted'],
      description: 'New status for the task',
    },
    subject: {
      type: 'string',
      description: 'New subject for the task',
    },
    description: {
      type: 'string',
      description: 'New description for the task',
    },
    activeForm: {
      type: 'string',
      description: 'New activeForm for the task',
    },
    owner: {
      type: 'string',
      description: 'Agent/owner ID to assign the task to',
    },
    addBlockedBy: {
      type: 'array',
      items: { type: 'string' },
      description: 'Task IDs that block this task (must complete first)',
    },
    addBlocks: {
      type: 'array',
      items: { type: 'string' },
      description: 'Task IDs that this task blocks',
    },
    metadata: {
      type: 'object',
      description: 'Metadata keys to merge (set key to null to delete)',
    },
  },
  required: ['taskId'],
};

const taskGetParameters = {
  type: 'object',
  properties: {
    taskId: {
      type: 'string',
      description: 'The ID of the task to retrieve (e.g., "1" or "task-1")',
    },
  },
  required: ['taskId'],
};

const taskListParameters = {
  type: 'object',
  properties: {},
  required: [],
};

// =============================================================================
// TOOL DESCRIPTIONS
// =============================================================================

const TASK_CREATE_DESCRIPTION = `Create a new task to track work that needs to be done.

Use this tool when:
- Starting a multi-step task that needs tracking
- Breaking down complex work into manageable pieces
- Coordinating work between multiple agents

Tasks are created with status "pending". Use task_update to change status.

Example:
  subject: "Implement user authentication"
  description: "Add JWT-based authentication with login/logout endpoints"
  activeForm: "Implementing user authentication"`;

const TASK_UPDATE_DESCRIPTION = `Update a task's status, dependencies, or other fields.

Status workflow: pending → in_progress → completed
Use status "deleted" to permanently remove a task.

Dependency management:
- addBlockedBy: List task IDs that must complete before this task can start
- addBlocks: List task IDs that cannot start until this task completes

Example: Mark task as in progress when starting work:
  taskId: "1", status: "in_progress"

Example: Set up dependencies:
  taskId: "2", addBlockedBy: ["1"]`;

const TASK_GET_DESCRIPTION = `Get full details of a specific task.

Returns:
- id, subject, description, activeForm
- status (pending, in_progress, completed)
- owner (if assigned)
- blockedBy (tasks that must complete first)
- blocks (tasks waiting on this one)
- metadata

Use this before starting work on a task to understand requirements.`;

const TASK_LIST_DESCRIPTION = `List all tasks with their current status.

Returns summary of each task:
- id: Task identifier
- subject: Brief title
- status: pending, in_progress, or completed
- owner: Agent ID if assigned
- blockedBy: Open (uncompleted) blocker task IDs

Tasks are sorted: in_progress first, then pending, then completed.
Use task_get for full details on a specific task.`;

// =============================================================================
// TOOL FACTORIES
// =============================================================================

/**
 * Create task_create tool bound to a TaskManager.
 */
export function createTaskCreateTool(taskManager: TaskManager): ToolDefinition {
  return {
    name: 'task_create',
    description: TASK_CREATE_DESCRIPTION,
    parameters: taskCreateParameters,
    dangerLevel: 'safe',
    execute: async (args: Record<string, unknown>) => {
      const options: CreateTaskOptions = {
        subject: args.subject as string,
        description: args.description as string,
        activeForm: args.activeForm as string | undefined,
        metadata: args.metadata as Record<string, unknown> | undefined,
      };

      if (!options.subject || !options.description) {
        return {
          success: false,
          error: 'subject and description are required',
        };
      }

      const task = taskManager.create(options);

      return {
        success: true,
        task: formatTaskForOutput(task),
        message: `Task #${task.id.replace('task-', '')} created: ${task.subject}`,
      };
    },
  };
}

/**
 * Create task_update tool bound to a TaskManager.
 */
export function createTaskUpdateTool(taskManager: TaskManager): ToolDefinition {
  return {
    name: 'task_update',
    description: TASK_UPDATE_DESCRIPTION,
    parameters: taskUpdateParameters,
    dangerLevel: 'safe',
    execute: async (args: Record<string, unknown>) => {
      const taskId = args.taskId as string;

      if (!taskId) {
        return {
          success: false,
          error: 'taskId is required',
        };
      }

      const updates: UpdateTaskOptions = {};

      if (args.status !== undefined) updates.status = args.status as TaskStatus;
      if (args.subject !== undefined) updates.subject = args.subject as string;
      if (args.description !== undefined) updates.description = args.description as string;
      if (args.activeForm !== undefined) updates.activeForm = args.activeForm as string;
      if (args.owner !== undefined) updates.owner = args.owner as string;
      if (args.addBlockedBy !== undefined) updates.addBlockedBy = args.addBlockedBy as string[];
      if (args.addBlocks !== undefined) updates.addBlocks = args.addBlocks as string[];
      if (args.metadata !== undefined) updates.metadata = args.metadata as Record<string, unknown>;

      const task = taskManager.update(taskId, updates);

      if (!task) {
        return {
          success: false,
          error: `Task not found: ${taskId}`,
        };
      }

      if (task.status === 'deleted') {
        return {
          success: true,
          message: `Task #${taskId.replace('task-', '')} deleted`,
        };
      }

      return {
        success: true,
        task: formatTaskForOutput(task),
        message: `Task #${task.id.replace('task-', '')} updated`,
      };
    },
  };
}

/**
 * Create task_get tool bound to a TaskManager.
 */
export function createTaskGetTool(taskManager: TaskManager): ToolDefinition {
  return {
    name: 'task_get',
    description: TASK_GET_DESCRIPTION,
    parameters: taskGetParameters,
    dangerLevel: 'safe',
    execute: async (args: Record<string, unknown>) => {
      const taskId = args.taskId as string;

      if (!taskId) {
        return {
          success: false,
          error: 'taskId is required',
        };
      }

      const task = taskManager.get(taskId);

      if (!task) {
        return {
          success: false,
          error: `Task not found: ${taskId}`,
        };
      }

      const openBlockers = taskManager.getOpenBlockers(task.id);

      return {
        success: true,
        task: formatTaskForOutput(task),
        isBlocked: openBlockers.length > 0,
        openBlockers,
      };
    },
  };
}

/**
 * Create task_list tool bound to a TaskManager.
 */
export function createTaskListTool(taskManager: TaskManager): ToolDefinition {
  return {
    name: 'task_list',
    description: TASK_LIST_DESCRIPTION,
    parameters: taskListParameters,
    dangerLevel: 'safe',
    execute: async () => {
      const summaries = taskManager.listSummaries();
      const counts = taskManager.getCounts();

      return {
        success: true,
        tasks: summaries.map(s => ({
          id: s.id.replace('task-', ''),
          subject: s.subject,
          status: s.status,
          owner: s.owner || null,
          blockedBy: s.blockedBy.map(b => b.replace('task-', '')),
        })),
        counts,
        message: summaries.length === 0
          ? 'No tasks'
          : `${counts.total} task(s): ${counts.inProgress} in progress, ${counts.pending} pending, ${counts.completed} completed`,
      };
    },
  };
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Format a task for output (strip internal prefixes).
 */
function formatTaskForOutput(task: Task): Record<string, unknown> {
  return {
    id: task.id.replace('task-', ''),
    subject: task.subject,
    description: task.description,
    activeForm: task.activeForm,
    status: task.status,
    owner: task.owner || null,
    blockedBy: task.blockedBy.map(b => b.replace('task-', '')),
    blocks: task.blocks.map(b => b.replace('task-', '')),
    metadata: task.metadata,
    createdAt: new Date(task.createdAt).toISOString(),
    updatedAt: new Date(task.updatedAt).toISOString(),
  };
}

// =============================================================================
// REGISTRATION HELPER
// =============================================================================

/**
 * Create all task tools bound to a TaskManager.
 */
export function createTaskTools(taskManager: TaskManager): ToolDefinition[] {
  return [
    createTaskCreateTool(taskManager),
    createTaskUpdateTool(taskManager),
    createTaskGetTool(taskManager),
    createTaskListTool(taskManager),
  ];
}
