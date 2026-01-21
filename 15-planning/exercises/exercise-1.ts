/**
 * Exercise 15: Task Decomposition
 * Implement task planning with dependencies.
 */

export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'blocked';

export interface Task {
  id: string;
  name: string;
  description: string;
  dependencies: string[];
  status: TaskStatus;
}

export interface Plan {
  id: string;
  goal: string;
  tasks: Task[];
  createdAt: number;
}

/**
 * TODO: Implement TaskPlanner
 */
export class TaskPlanner {
  createPlan(_goal: string, _tasks: Omit<Task, 'id' | 'status'>[]): Plan {
    throw new Error('TODO: Implement createPlan');
  }

  getNextTasks(_plan: Plan): Task[] {
    // TODO: Return tasks that have all dependencies completed
    throw new Error('TODO: Implement getNextTasks');
  }

  completeTask(_plan: Plan, _taskId: string): boolean {
    throw new Error('TODO: Implement completeTask');
  }

  isComplete(_plan: Plan): boolean {
    throw new Error('TODO: Implement isComplete');
  }

  getProgress(_plan: Plan): { completed: number; total: number; percentage: number } {
    throw new Error('TODO: Implement getProgress');
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 10);
}
