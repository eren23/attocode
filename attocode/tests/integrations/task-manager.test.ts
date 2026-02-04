/**
 * Task Manager Tests
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  TaskManager,
  createTaskManager,
  type Task,
} from '../../src/integrations/task-manager.js';

describe('TaskManager', () => {
  let taskManager: TaskManager;

  beforeEach(() => {
    taskManager = createTaskManager();
  });

  describe('task creation', () => {
    it('should create a task with required fields', () => {
      const task = taskManager.create({
        subject: 'Implement feature',
        description: 'Add user authentication',
      });

      expect(task.id).toMatch(/^task-\d+$/);
      expect(task.subject).toBe('Implement feature');
      expect(task.description).toBe('Add user authentication');
      expect(task.status).toBe('pending');
      expect(task.blockedBy).toEqual([]);
      expect(task.blocks).toEqual([]);
    });

    it('should create a task with optional activeForm', () => {
      const task = taskManager.create({
        subject: 'Fix bug',
        description: 'Fix login issue',
        activeForm: 'Fixing the login bug',
      });

      expect(task.activeForm).toBe('Fixing the login bug');
    });

    it('should auto-generate activeForm if not provided', () => {
      const task = taskManager.create({
        subject: 'Update tests',
        description: 'Add new test cases',
      });

      expect(task.activeForm).toBe('Working on update tests');
    });

    it('should emit task.created event', () => {
      const listener = vi.fn();
      taskManager.on('task.created', listener);

      taskManager.create({
        subject: 'Test task',
        description: 'Test description',
      });

      expect(listener).toHaveBeenCalledOnce();
      expect(listener.mock.calls[0][0].task.subject).toBe('Test task');
    });
  });

  describe('task update', () => {
    it('should update task status', () => {
      const task = taskManager.create({
        subject: 'Task 1',
        description: 'Description 1',
      });

      const updated = taskManager.update(task.id, { status: 'in_progress' });

      expect(updated?.status).toBe('in_progress');
    });

    it('should support shorthand task IDs', () => {
      const task = taskManager.create({
        subject: 'Task 1',
        description: 'Description 1',
      });

      // Use "1" instead of "task-1"
      const updated = taskManager.update('1', { status: 'completed' });

      expect(updated?.status).toBe('completed');
    });

    it('should delete task when status is deleted', () => {
      const task = taskManager.create({
        subject: 'Task to delete',
        description: 'Will be deleted',
      });

      taskManager.update(task.id, { status: 'deleted' });

      expect(taskManager.get(task.id)).toBeUndefined();
    });

    it('should emit task.updated event', () => {
      const task = taskManager.create({
        subject: 'Task',
        description: 'Desc',
      });

      const listener = vi.fn();
      taskManager.on('task.updated', listener);

      taskManager.update(task.id, { status: 'in_progress' });

      expect(listener).toHaveBeenCalledOnce();
    });
  });

  describe('dependencies', () => {
    it('should add blockedBy dependency', () => {
      const task1 = taskManager.create({
        subject: 'Task 1',
        description: 'First task',
      });
      const task2 = taskManager.create({
        subject: 'Task 2',
        description: 'Second task',
      });

      taskManager.update(task2.id, { addBlockedBy: [task1.id] });

      const updated = taskManager.get(task2.id);
      expect(updated?.blockedBy).toContain(task1.id);

      // Should also update the blocker's blocks array
      const blocker = taskManager.get(task1.id);
      expect(blocker?.blocks).toContain(task2.id);
    });

    it('should identify blocked tasks', () => {
      const task1 = taskManager.create({
        subject: 'Task 1',
        description: 'First',
      });
      const task2 = taskManager.create({
        subject: 'Task 2',
        description: 'Second',
      });

      taskManager.update(task2.id, { addBlockedBy: [task1.id] });

      expect(taskManager.isBlocked(task1.id)).toBe(false);
      expect(taskManager.isBlocked(task2.id)).toBe(true);

      // Complete task1 - task2 should no longer be blocked
      taskManager.update(task1.id, { status: 'completed' });
      expect(taskManager.isBlocked(task2.id)).toBe(false);
    });

    it('should find available tasks', () => {
      const task1 = taskManager.create({
        subject: 'Task 1',
        description: 'First',
      });
      const task2 = taskManager.create({
        subject: 'Task 2',
        description: 'Second',
      });
      taskManager.update(task2.id, { addBlockedBy: [task1.id] });

      const available = taskManager.getAvailableTasks();

      expect(available.length).toBe(1);
      expect(available[0].id).toBe(task1.id);
    });
  });

  describe('listing', () => {
    it('should list all tasks', () => {
      taskManager.create({ subject: 'Task 1', description: 'D1' });
      taskManager.create({ subject: 'Task 2', description: 'D2' });
      taskManager.create({ subject: 'Task 3', description: 'D3' });

      const tasks = taskManager.list();

      expect(tasks.length).toBe(3);
    });

    it('should sort tasks by status', () => {
      taskManager.create({ subject: 'Pending', description: 'D' });
      const inProgress = taskManager.create({ subject: 'In Progress', description: 'D' });
      const completed = taskManager.create({ subject: 'Completed', description: 'D' });

      taskManager.update(inProgress.id, { status: 'in_progress' });
      taskManager.update(completed.id, { status: 'completed' });

      const tasks = taskManager.list();

      expect(tasks[0].status).toBe('in_progress');
      expect(tasks[1].status).toBe('pending');
      expect(tasks[2].status).toBe('completed');
    });
  });

  describe('hydration', () => {
    it('should export tasks to markdown', () => {
      taskManager.create({
        subject: 'First task',
        description: 'Do something',
      });

      const markdown = taskManager.toMarkdown();

      expect(markdown).toContain('# Tasks');
      expect(markdown).toContain('First task');
      expect(markdown).toContain('Do something');
    });

    it('should import tasks from markdown', () => {
      const markdown = `# Tasks

## [ ] task-1: First task

**Status:** pending

**Description:**
Do something

## [x] task-2: Second task

**Status:** completed

**Description:**
Did something`;

      taskManager.fromMarkdown(markdown);

      const tasks = taskManager.list();
      expect(tasks.length).toBe(2);
      expect(tasks.find(t => t.id === 'task-1')?.status).toBe('pending');
      expect(tasks.find(t => t.id === 'task-2')?.status).toBe('completed');
    });
  });

  describe('counts', () => {
    it('should count tasks by status', () => {
      taskManager.create({ subject: 'T1', description: 'D' });
      const t2 = taskManager.create({ subject: 'T2', description: 'D' });
      const t3 = taskManager.create({ subject: 'T3', description: 'D' });

      taskManager.update(t2.id, { status: 'in_progress' });
      taskManager.update(t3.id, { status: 'completed' });

      const counts = taskManager.getCounts();

      expect(counts.pending).toBe(1);
      expect(counts.inProgress).toBe(1);
      expect(counts.completed).toBe(1);
      expect(counts.total).toBe(3);
    });
  });
});
