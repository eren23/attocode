/**
 * Interactive Planning Tests
 *
 * Tests for the conversational + editable planning system.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  InteractivePlanner,
  createInteractivePlanner,
  formatPlan,
  formatStep,
  type PlannerLLMCall,
  type InteractivePlannerEvent,
  type InteractivePlan,
  type PlanStep,
} from '../../src/integrations/interactive-planning.js';

// =============================================================================
// TEST HELPERS
// =============================================================================

function createMockLLM(planResponse?: string): PlannerLLMCall {
  return vi.fn(async () => ({
    content: planResponse || JSON.stringify({
      reasoning: 'Test reasoning',
      steps: [
        { description: 'Step 1: Analyze requirements', complexity: 2 },
        { description: 'Step 2: Implement feature', complexity: 4 },
        { description: 'Step 3: Write tests', complexity: 3, isDecisionPoint: true, decisionOptions: ['Unit tests', 'E2E tests', 'Both'] },
        { description: 'Step 4: Deploy', complexity: 2 },
      ],
    }),
  }));
}

function createEditLLM(response: object): PlannerLLMCall {
  return vi.fn(async () => ({
    content: JSON.stringify(response),
  }));
}

// =============================================================================
// TESTS
// =============================================================================

describe('InteractivePlanner', () => {
  let planner: InteractivePlanner;

  beforeEach(() => {
    planner = createInteractivePlanner({
      autoCheckpoint: true,
      confirmBeforeExecute: true,
      maxCheckpoints: 5,
    });
  });

  describe('initialization', () => {
    it('should create planner with default config', () => {
      const p = createInteractivePlanner();
      expect(p).toBeInstanceOf(InteractivePlanner);
      expect(p.getPlan()).toBeNull();
    });

    it('should create planner with custom config', () => {
      const p = createInteractivePlanner({
        autoCheckpoint: false,
        maxCheckpoints: 10,
      });
      expect(p).toBeInstanceOf(InteractivePlanner);
    });
  });

  describe('draft', () => {
    it('should create plan from LLM response', async () => {
      const llm = createMockLLM();
      const plan = await planner.draft('Add user authentication', llm);

      expect(plan).toBeDefined();
      expect(plan.goal).toBe('Add user authentication');
      expect(plan.steps.length).toBe(4);
      expect(plan.status).toBe('draft');
      expect(plan.reasoning).toBe('Test reasoning');
    });

    it('should parse numbered steps as fallback', async () => {
      const llm = vi.fn(async () => ({
        content: `Here's the plan:
1. First analyze the code
2. Then implement the feature
3. Finally write tests`,
      }));

      const plan = await planner.draft('Simple task', llm);

      expect(plan.steps.length).toBe(3);
      expect(plan.steps[0].description).toBe('First analyze the code');
    });

    it('should assign step numbers and IDs', async () => {
      const llm = createMockLLM();
      const plan = await planner.draft('Test task', llm);

      expect(plan.steps[0].number).toBe(1);
      expect(plan.steps[0].id).toBe('step-1');
      expect(plan.steps[3].number).toBe(4);
    });

    it('should mark decision points', async () => {
      const llm = createMockLLM();
      const plan = await planner.draft('Test task', llm);

      const decisionStep = plan.steps.find((s) => s.isDecisionPoint);
      expect(decisionStep).toBeDefined();
      expect(decisionStep?.decisionOptions).toEqual(['Unit tests', 'E2E tests', 'Both']);
    });

    it('should emit plan.created event', async () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      await planner.draft('Test', createMockLLM());

      expect(events.some((e) => e.type === 'plan.created')).toBe(true);
    });
  });

  describe('edit', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
    });

    describe('direct parsing', () => {
      it('should parse skip command', async () => {
        const result = await planner.edit('skip step 2');

        expect(result.command.type).toBe('skip');
        expect(result.command.target).toBe(2);
        expect(result.confidence).toBeGreaterThanOrEqual(0.9);

        const plan = planner.getPlan()!;
        expect(plan.steps[1].status).toBe('skipped');
      });

      it('should parse unskip command', async () => {
        await planner.edit('skip step 2');
        const result = await planner.edit('unskip step 2');

        expect(result.command.type).toBe('unskip');
        expect(planner.getPlan()!.steps[1].status).toBe('pending');
      });

      it('should parse remove command', async () => {
        const result = await planner.edit('remove step 3');

        expect(result.command.type).toBe('remove');
        expect(planner.getPlan()!.steps.length).toBe(3);
      });

      it('should parse add after command', async () => {
        const result = await planner.edit('add rate limiting after step 2');

        expect(result.command.type).toBe('add');
        expect(result.command.position).toBe('after');
        expect(result.command.target).toBe(2);

        const plan = planner.getPlan()!;
        expect(plan.steps.length).toBe(5);
        expect(plan.steps[2].description).toBe('rate limiting');
      });

      it('should parse add before command', async () => {
        const result = await planner.edit('add validation before step 1');

        expect(result.command.type).toBe('add');
        expect(result.command.position).toBe('before');

        const plan = planner.getPlan()!;
        expect(plan.steps[0].description).toBe('validation');
      });

      it('should parse move command', async () => {
        const originalStep2 = planner.getPlan()!.steps[1].description;
        const result = await planner.edit('move step 2 to position 4');

        expect(result.command.type).toBe('move');
        expect(result.command.destination).toBe(4);

        const plan = planner.getPlan()!;
        expect(plan.steps[3].description).toBe(originalStep2);
      });

      it('should parse update command', async () => {
        const result = await planner.edit('update step 1 to analyze and document requirements');

        expect(result.command.type).toBe('update');
        expect(planner.getPlan()!.steps[0].description).toBe('analyze and document requirements');
      });

      it('should return low confidence for unclear commands', async () => {
        const result = await planner.edit('do something weird');

        expect(result.confidence).toBeLessThan(0.5);
        expect(result.clarificationNeeded).toBeDefined();
      });
    });

    describe('LLM-assisted parsing', () => {
      it('should use LLM for ambiguous commands', async () => {
        const editLLM = createEditLLM({
          type: 'add',
          content: 'caching layer',
          position: 'after',
          target: 2,
          confidence: 0.9,
        });

        const result = await planner.edit('maybe add some caching somewhere', editLLM);

        expect(editLLM).toHaveBeenCalled();
        expect(result.command.type).toBe('add');
      });

      it('should return clarification needed on low confidence', async () => {
        const editLLM = createEditLLM({
          type: 'update',
          confidence: 0.5,
          clarificationNeeded: 'What exactly would you like to change?',
        });

        const result = await planner.edit('change things', editLLM);

        expect(result.clarificationNeeded).toBeDefined();
      });
    });

    it('should emit edit.applied event', async () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      await planner.edit('skip step 1');

      expect(events.some((e) => e.type === 'edit.applied')).toBe(true);
    });

    it('should renumber steps after modifications', async () => {
      await planner.edit('remove step 2');

      const plan = planner.getPlan()!;
      expect(plan.steps[0].number).toBe(1);
      expect(plan.steps[1].number).toBe(2);
      expect(plan.steps[2].number).toBe(3);
    });

    it('should throw when no plan exists', async () => {
      const emptyPlanner = createInteractivePlanner();
      await expect(emptyPlanner.edit('skip step 1')).rejects.toThrow('No plan to edit');
    });
  });

  describe('approve', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
    });

    it('should approve draft plan', () => {
      planner.approve();
      expect(planner.getPlan()!.status).toBe('approved');
    });

    it('should emit plan.approved event', () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      planner.approve();

      expect(events.some((e) => e.type === 'plan.approved')).toBe(true);
    });

    it('should throw when no plan exists', () => {
      const emptyPlanner = createInteractivePlanner();
      expect(() => emptyPlanner.approve()).toThrow('No plan to approve');
    });

    it('should throw when plan is not in draft or discussing status', async () => {
      planner.approve();
      expect(() => planner.approve()).toThrow('Cannot approve plan in status: approved');
    });
  });

  describe('execute', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
      planner.approve();
    });

    it('should yield steps in order', () => {
      const steps: PlanStep[] = [];
      for (const step of planner.execute()) {
        steps.push(step);
        planner.completeStep();
      }

      // Step 3 is a decision point, so execution pauses there
      // Steps 1, 2 are yielded before hitting the decision point
      expect(steps.length).toBe(2);
      expect(steps[0].number).toBe(1);
      expect(steps[1].number).toBe(2);
    });

    it('should skip already skipped steps', async () => {
      // Create a new planner for this test since beforeEach already approves
      const p = createInteractivePlanner({ autoCheckpoint: false });
      await p.draft('Test task', createMockLLM());
      await p.edit('skip step 1');
      p.approve();

      const steps: PlanStep[] = [];
      for (const step of p.execute()) {
        steps.push(step);
        p.completeStep();
      }

      // First step is skipped, so step 2 should be first yielded
      expect(steps[0].number).toBe(2);
    });

    it('should auto-checkpoint before each step', () => {
      const generator = planner.execute();
      generator.next();

      expect(planner.getCheckpoints().length).toBe(1);
    });

    it('should pause at decision points', () => {
      const steps: PlanStep[] = [];
      for (const step of planner.execute()) {
        steps.push(step);
        planner.completeStep();
      }

      // Should pause at step 3 (decision point)
      expect(planner.getPlan()!.status).toBe('paused');
    });

    it('should emit step events', () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      const generator = planner.execute();
      generator.next();

      expect(events.some((e) => e.type === 'step.started')).toBe(true);
    });

    it('should throw when plan is not approved', () => {
      const p = createInteractivePlanner({ confirmBeforeExecute: true });
      p.draft('Test', createMockLLM());

      // Need to wait for draft to complete
      setTimeout(() => {
        expect(() => [...p.execute()]).toThrow('Plan must be approved before execution');
      }, 0);
    });

    it('should mark plan as completed when all steps done', async () => {
      // Create a plan without decision points
      const llm = vi.fn(async () => ({
        content: JSON.stringify({
          steps: [
            { description: 'Step 1' },
            { description: 'Step 2' },
          ],
        }),
      }));

      const p = createInteractivePlanner();
      await p.draft('Simple task', llm);
      p.approve();

      for (const _step of p.execute()) {
        p.completeStep();
      }

      expect(p.getPlan()!.status).toBe('completed');
    });
  });

  describe('completeStep', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
      planner.approve();
    });

    it('should mark current step as completed', () => {
      const generator = planner.execute();
      generator.next();

      planner.completeStep('Task output');

      expect(planner.getPlan()!.steps[0].status).toBe('completed');
      expect(planner.getPlan()!.steps[0].output).toBe('Task output');
    });

    it('should advance current step index', () => {
      const generator = planner.execute();
      generator.next();

      expect(planner.getPlan()!.currentStepIndex).toBe(0);

      planner.completeStep();

      expect(planner.getPlan()!.currentStepIndex).toBe(1);
    });

    it('should emit step.completed event', () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      const generator = planner.execute();
      generator.next();
      planner.completeStep();

      expect(events.some((e) => e.type === 'step.completed')).toBe(true);
    });
  });

  describe('failStep', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
      planner.approve();
    });

    it('should mark current step as failed', () => {
      const generator = planner.execute();
      generator.next();

      planner.failStep('Something went wrong');

      expect(planner.getPlan()!.steps[0].status).toBe('failed');
      expect(planner.getPlan()!.steps[0].statusReason).toBe('Something went wrong');
    });

    it('should mark plan as failed', () => {
      const generator = planner.execute();
      generator.next();
      planner.failStep('Error');

      expect(planner.getPlan()!.status).toBe('failed');
    });

    it('should emit step.failed event', () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      const generator = planner.execute();
      generator.next();
      planner.failStep('Error');

      expect(events.some((e) => e.type === 'step.failed')).toBe(true);
    });
  });

  describe('makeDecision', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
      planner.approve();
    });

    it('should record decision choice', () => {
      // Execute until decision point
      for (const _step of planner.execute()) {
        planner.completeStep();
      }

      expect(planner.getPlan()!.status).toBe('paused');

      planner.makeDecision('Unit tests');

      const step = planner.getPlan()!.steps[2]; // Step 3 is decision point
      expect(step.decisionChoice).toBe('Unit tests');
      expect(planner.getPlan()!.status).toBe('executing');
    });

    it('should emit decision.made event', () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      for (const _step of planner.execute()) {
        planner.completeStep();
      }

      planner.makeDecision('Both');

      expect(events.some((e) => e.type === 'decision.made')).toBe(true);
    });

    it('should throw when no decision pending', () => {
      expect(() => planner.makeDecision('test')).toThrow('No decision pending');
    });
  });

  describe('checkpoints', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
      planner.approve();
    });

    it('should create checkpoint', () => {
      const cp = planner.createCheckpoint('Test checkpoint');

      expect(cp.label).toBe('Test checkpoint');
      expect(cp.planState).toBeDefined();
      expect(planner.getCheckpoints().length).toBe(1);
    });

    it('should emit checkpoint.created event', () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      planner.createCheckpoint('Test');

      expect(events.some((e) => e.type === 'checkpoint.created')).toBe(true);
    });

    it('should enforce max checkpoints', () => {
      for (let i = 0; i < 10; i++) {
        planner.createCheckpoint(`Checkpoint ${i}`);
      }

      expect(planner.getCheckpoints().length).toBe(5); // maxCheckpoints is 5
    });

    it('should throw when no plan exists', () => {
      const emptyPlanner = createInteractivePlanner();
      expect(() => emptyPlanner.createCheckpoint('test')).toThrow('No plan for checkpoint');
    });
  });

  describe('rollback', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
      planner.approve();
    });

    it('should restore plan state from checkpoint', () => {
      const cp = planner.createCheckpoint('Before changes');

      // Make some changes
      const generator = planner.execute();
      generator.next();
      planner.completeStep();
      generator.next();
      planner.completeStep();

      expect(planner.getPlan()!.currentStepIndex).toBe(2);

      planner.rollback(cp.id);

      expect(planner.getPlan()!.currentStepIndex).toBe(0);
      expect(planner.getPlan()!.steps[0].status).toBe('pending');
    });

    it('should remove checkpoints after rollback point', () => {
      planner.createCheckpoint('CP1');
      planner.createCheckpoint('CP2');
      const cp3 = planner.createCheckpoint('CP3');
      planner.createCheckpoint('CP4');

      expect(planner.getCheckpoints().length).toBe(4);

      planner.rollback(cp3.id);

      expect(planner.getCheckpoints().length).toBe(3);
    });

    it('should emit rollback events', () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      const cp = planner.createCheckpoint('Test');
      planner.rollback(cp.id);

      expect(events.some((e) => e.type === 'rollback.started')).toBe(true);
      expect(events.some((e) => e.type === 'rollback.completed')).toBe(true);
    });

    it('should throw when checkpoint not found', () => {
      expect(() => planner.rollback('nonexistent')).toThrow('Checkpoint nonexistent not found');
    });

    it('should throw when no plan exists', () => {
      const emptyPlanner = createInteractivePlanner();
      expect(() => emptyPlanner.rollback('test')).toThrow('No plan to rollback');
    });
  });

  describe('cancel', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
    });

    it('should cancel the plan', () => {
      planner.cancel('User requested');

      expect(planner.getPlan()!.status).toBe('cancelled');
    });

    it('should emit plan.cancelled event', () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      planner.cancel('Reason');

      const event = events.find((e) => e.type === 'plan.cancelled');
      expect(event).toBeDefined();
      if (event?.type === 'plan.cancelled') {
        expect(event.reason).toBe('Reason');
      }
    });
  });

  describe('discussion history', () => {
    beforeEach(async () => {
      await planner.draft('Test task', createMockLLM());
    });

    it('should add messages to discussion history', () => {
      planner.addDiscussion('user', 'Can we add caching?');
      planner.addDiscussion('assistant', 'Yes, I can add that after step 2.');

      const plan = planner.getPlan()!;
      expect(plan.discussionHistory.length).toBe(2);
      expect(plan.discussionHistory[0].role).toBe('user');
    });

    it('should change status to discussing', () => {
      expect(planner.getPlan()!.status).toBe('draft');

      planner.addDiscussion('user', 'Question');

      expect(planner.getPlan()!.status).toBe('discussing');
    });
  });

  describe('clear', () => {
    it('should clear the plan', async () => {
      await planner.draft('Test', createMockLLM());
      expect(planner.getPlan()).not.toBeNull();

      planner.clear();

      expect(planner.getPlan()).toBeNull();
    });
  });

  describe('events', () => {
    it('should allow subscribing to events', async () => {
      const events: InteractivePlannerEvent[] = [];
      planner.on((event) => events.push(event));

      await planner.draft('Test', createMockLLM());

      expect(events.length).toBeGreaterThan(0);
    });

    it('should allow unsubscribing', async () => {
      const events: InteractivePlannerEvent[] = [];
      const unsubscribe = planner.on((event) => events.push(event));

      await planner.draft('Test', createMockLLM());
      expect(events.length).toBeGreaterThan(0);

      events.length = 0;
      unsubscribe();

      planner.approve();
      expect(events.length).toBe(0);
    });

    it('should ignore listener errors', async () => {
      planner.on(() => {
        throw new Error('Listener error');
      });

      // Should not throw
      await planner.draft('Test', createMockLLM());
    });
  });
});

describe('formatPlan', () => {
  it('should format plan for display', () => {
    const plan: InteractivePlan = {
      id: 'test',
      goal: 'Test Goal',
      steps: [
        {
          id: 'step-1',
          number: 1,
          description: 'First step',
          dependencies: [],
          status: 'completed',
        },
        {
          id: 'step-2',
          number: 2,
          description: 'Second step',
          dependencies: [],
          status: 'in_progress',
        },
        {
          id: 'step-3',
          number: 3,
          description: 'Third step',
          dependencies: [],
          status: 'pending',
          isDecisionPoint: true,
        },
      ],
      status: 'executing',
      currentStepIndex: 1,
      checkpoints: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      discussionHistory: [],
      reasoning: 'Test reasoning',
    };

    const formatted = formatPlan(plan);

    expect(formatted).toContain('Test Goal');
    expect(formatted).toContain('executing');
    expect(formatted).toContain('First step');
    expect(formatted).toContain('●'); // completed icon
    expect(formatted).toContain('◐'); // in_progress icon
    expect(formatted).toContain('○'); // pending icon
    expect(formatted).toContain('[DECISION]');
    expect(formatted).toContain('Test reasoning');
  });

  it('should show failed step reason', () => {
    const plan: InteractivePlan = {
      id: 'test',
      goal: 'Test',
      steps: [
        {
          id: 'step-1',
          number: 1,
          description: 'Failed step',
          dependencies: [],
          status: 'failed',
          statusReason: 'Network error',
        },
      ],
      status: 'failed',
      currentStepIndex: 0,
      checkpoints: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      discussionHistory: [],
    };

    const formatted = formatPlan(plan);

    expect(formatted).toContain('✗'); // failed icon
    expect(formatted).toContain('Network error');
  });

  it('should show checkpoint count', () => {
    const plan: InteractivePlan = {
      id: 'test',
      goal: 'Test',
      steps: [],
      status: 'draft',
      currentStepIndex: 0,
      checkpoints: [
        { id: 'cp1', timestamp: '', label: '', beforeStepId: '', planState: { steps: [], status: 'draft', currentStepIndex: 0 } },
        { id: 'cp2', timestamp: '', label: '', beforeStepId: '', planState: { steps: [], status: 'draft', currentStepIndex: 0 } },
      ],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      discussionHistory: [],
    };

    const formatted = formatPlan(plan);

    expect(formatted).toContain('Checkpoints: 2');
  });
});

describe('formatStep', () => {
  it('should format step for display', () => {
    const step: PlanStep = {
      id: 'step-1',
      number: 1,
      description: 'Test step',
      dependencies: [],
      status: 'completed',
      output: 'Step output result',
    };

    const formatted = formatStep(step);

    expect(formatted).toContain('Step 1');
    expect(formatted).toContain('Test step');
    expect(formatted).toContain('Step output result');
  });

  it('should format decision point', () => {
    const step: PlanStep = {
      id: 'step-1',
      number: 1,
      description: 'Choose approach',
      dependencies: [],
      status: 'pending',
      isDecisionPoint: true,
      decisionOptions: ['Option A', 'Option B'],
    };

    const formatted = formatStep(step);

    expect(formatted).toContain('Decision options');
    expect(formatted).toContain('Option A');
    expect(formatted).toContain('Option B');
  });

  it('should show decision choice if made', () => {
    const step: PlanStep = {
      id: 'step-1',
      number: 1,
      description: 'Choose approach',
      dependencies: [],
      status: 'completed',
      isDecisionPoint: true,
      decisionOptions: ['Option A', 'Option B'],
      decisionChoice: 'Option A',
    };

    const formatted = formatStep(step);

    expect(formatted).toContain('Choice: Option A');
  });

  it('should truncate long output', () => {
    const step: PlanStep = {
      id: 'step-1',
      number: 1,
      description: 'Test',
      dependencies: [],
      status: 'completed',
      output: 'A'.repeat(200),
    };

    const formatted = formatStep(step);

    expect(formatted).toContain('...');
    expect(formatted.length).toBeLessThan(250);
  });
});
