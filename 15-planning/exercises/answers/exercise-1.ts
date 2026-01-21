/**
 * Exercise 15: Task Decomposition - REFERENCE SOLUTION
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

export class TaskPlanner {
  createPlan(goal: string, taskDefs: Omit<Task, 'id' | 'status'>[]): Plan {
    const tasks: Task[] = taskDefs.map((t, i) => ({
      ...t,
      id: `task-${i}`,
      status: 'pending' as TaskStatus,
    }));

    return {
      id: generateId(),
      goal,
      tasks,
      createdAt: Date.now(),
    };
  }

  getNextTasks(plan: Plan): Task[] {
    return plan.tasks.filter(task => {
      if (task.status !== 'pending') return false;
      return task.dependencies.every(depId => {
        const dep = plan.tasks.find(t => t.id === depId);
        return dep?.status === 'completed';
      });
    });
  }

  completeTask(plan: Plan, taskId: string): boolean {
    const task = plan.tasks.find(t => t.id === taskId);
    if (!task || task.status === 'completed') return false;
    task.status = 'completed';
    return true;
  }

  isComplete(plan: Plan): boolean {
    return plan.tasks.every(t => t.status === 'completed');
  }

  getProgress(plan: Plan): { completed: number; total: number; percentage: number } {
    const completed = plan.tasks.filter(t => t.status === 'completed').length;
    const total = plan.tasks.length;
    return {
      completed,
      total,
      percentage: total > 0 ? Math.round((completed / total) * 100) : 0,
    };
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 10);
}
