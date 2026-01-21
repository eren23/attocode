/**
 * Exercise Tests: Lesson 15 - Task Decomposition
 */
import { describe, it, expect } from 'vitest';
import { TaskPlanner } from './exercises/answers/exercise-1.js';

describe('TaskPlanner', () => {
  const planner = new TaskPlanner();

  it('should create a plan with tasks', () => {
    const plan = planner.createPlan('Build feature', [
      { name: 'Design', description: 'Design the feature', dependencies: [] },
      { name: 'Implement', description: 'Write code', dependencies: ['task-0'] },
    ]);

    expect(plan.tasks).toHaveLength(2);
    expect(plan.tasks[0].status).toBe('pending');
  });

  it('should get next available tasks', () => {
    const plan = planner.createPlan('Test', [
      { name: 'A', description: '', dependencies: [] },
      { name: 'B', description: '', dependencies: ['task-0'] },
    ]);

    const next = planner.getNextTasks(plan);
    expect(next).toHaveLength(1);
    expect(next[0].name).toBe('A');
  });

  it('should unblock tasks when dependencies complete', () => {
    const plan = planner.createPlan('Test', [
      { name: 'A', description: '', dependencies: [] },
      { name: 'B', description: '', dependencies: ['task-0'] },
    ]);

    planner.completeTask(plan, 'task-0');
    const next = planner.getNextTasks(plan);

    expect(next).toHaveLength(1);
    expect(next[0].name).toBe('B');
  });

  it('should track completion', () => {
    const plan = planner.createPlan('Test', [
      { name: 'A', description: '', dependencies: [] },
    ]);

    expect(planner.isComplete(plan)).toBe(false);
    planner.completeTask(plan, 'task-0');
    expect(planner.isComplete(plan)).toBe(true);
  });

  it('should calculate progress', () => {
    const plan = planner.createPlan('Test', [
      { name: 'A', description: '', dependencies: [] },
      { name: 'B', description: '', dependencies: [] },
    ]);

    planner.completeTask(plan, 'task-0');
    const progress = planner.getProgress(plan);

    expect(progress.completed).toBe(1);
    expect(progress.percentage).toBe(50);
  });
});
