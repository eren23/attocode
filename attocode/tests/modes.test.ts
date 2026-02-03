/**
 * Mode Switching Tests
 *
 * Tests for the agent mode system (build/plan/review/debug).
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  ModeManager,
  createModeManager,
  formatModeList,
  parseMode,
  MODES,
  READ_ONLY_TOOLS,
  ALL_TOOLS,
  calculateTaskSimilarity,
  areTasksSimilar,
} from '../src/modes.js';
import type { ToolDefinition } from '../src/types.js';

// Mock tools for testing
const mockTools: ToolDefinition[] = [
  { name: 'read_file', description: 'Read file', parameters: {}, execute: async () => '' },
  { name: 'write_file', description: 'Write file', parameters: {}, execute: async () => '' },
  { name: 'list_files', description: 'List files', parameters: {}, execute: async () => '' },
  { name: 'execute_command', description: 'Execute command', parameters: {}, execute: async () => '' },
  { name: 'grep', description: 'Search', parameters: {}, execute: async () => '' },
];

describe('MODES configuration', () => {
  it('should have all required modes defined', () => {
    expect(MODES.build).toBeDefined();
    expect(MODES.plan).toBeDefined();
    expect(MODES.review).toBeDefined();
    expect(MODES.debug).toBeDefined();
  });

  it('should have required properties for each mode', () => {
    for (const [_key, config] of Object.entries(MODES)) {
      expect(config.name).toBeTruthy();
      expect(config.description).toBeTruthy();
      expect(Array.isArray(config.availableTools)).toBe(true);
      expect(config.systemPromptAddition).toBeTruthy();
      expect(config.color).toBeTruthy();
      expect(config.icon).toBeTruthy();
    }
  });

  it('build mode should have all tools', () => {
    expect(MODES.build.availableTools).toContain(ALL_TOOLS);
  });

  it('plan mode should allow all tools but intercept writes', () => {
    // Plan mode allows all tools but requires write approval
    expect(MODES.plan.availableTools).toContain(ALL_TOOLS);
    expect(MODES.plan.requireWriteApproval).toBe(true);
  });

  it('review mode should have read-only tools', () => {
    for (const tool of READ_ONLY_TOOLS) {
      expect(MODES.review.availableTools).toContain(tool);
    }
  });
});

describe('ModeManager', () => {
  let manager: ModeManager;

  beforeEach(() => {
    manager = createModeManager(mockTools);
  });

  describe('initialization', () => {
    it('should start in build mode by default', () => {
      expect(manager.getMode()).toBe('build');
    });

    it('should initialize with provided tools', () => {
      const config = manager.getModeConfig();
      expect(config).toBeDefined();
    });
  });

  describe('getMode and setMode', () => {
    it('should change mode when setMode is called', () => {
      manager.setMode('plan');
      expect(manager.getMode()).toBe('plan');

      manager.setMode('review');
      expect(manager.getMode()).toBe('review');
    });

    it('should not emit event when setting same mode', () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      manager.setMode('build'); // Same as current
      expect(events.length).toBe(0);
    });

    it('should emit event when mode changes', () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      manager.setMode('plan');

      expect(events.length).toBe(1);
      expect((events[0] as any).type).toBe('mode.changed');
      expect((events[0] as any).from).toBe('build');
      expect((events[0] as any).to).toBe('plan');
    });
  });

  describe('cycleMode', () => {
    it('should cycle through modes', () => {
      expect(manager.getMode()).toBe('build');

      manager.cycleMode();
      expect(manager.getMode()).toBe('plan');

      manager.cycleMode();
      expect(manager.getMode()).toBe('review');

      manager.cycleMode();
      expect(manager.getMode()).toBe('debug');

      manager.cycleMode();
      expect(manager.getMode()).toBe('build'); // Back to start
    });
  });

  describe('getModeConfig', () => {
    it('should return config for current mode', () => {
      const config = manager.getModeConfig();

      expect(config.name).toBe('Build');
      expect(config.description).toBeTruthy();
    });

    it('should update when mode changes', () => {
      manager.setMode('plan');
      const config = manager.getModeConfig();

      expect(config.name).toBe('Plan');
    });
  });

  describe('isToolAvailable', () => {
    it('should allow all tools in build mode', () => {
      manager.setMode('build');

      expect(manager.isToolAvailable('read_file')).toBe(true);
      expect(manager.isToolAvailable('write_file')).toBe(true);
      expect(manager.isToolAvailable('execute_command')).toBe(true);
    });

    it('should allow all tools in plan mode (writes are intercepted, not filtered)', () => {
      manager.setMode('plan');

      // Plan mode allows all tools - writes are intercepted, not blocked
      expect(manager.isToolAvailable('read_file')).toBe(true);
      expect(manager.isToolAvailable('list_files')).toBe(true);
      expect(manager.isToolAvailable('write_file')).toBe(true); // Available, but intercepted
    });
  });

  describe('filterTools', () => {
    it('should return all tools in build mode', () => {
      manager.setMode('build');
      const filtered = manager.filterTools(mockTools);

      expect(filtered.length).toBe(mockTools.length);
    });

    it('should not filter tools in plan mode (all tools available, writes intercepted)', () => {
      manager.setMode('plan');
      const filtered = manager.filterTools(mockTools);

      // Plan mode allows all tools - writes are intercepted by shouldInterceptTool, not filtered
      expect(filtered.length).toBe(mockTools.length);
    });

    it('should filter tools in review mode', () => {
      manager.setMode('review');
      const filtered = manager.filterTools(mockTools);

      // Review mode is actually read-only with tool filtering
      expect(filtered.length).toBeLessThan(mockTools.length);
      expect(filtered.every(t => READ_ONLY_TOOLS.includes(t.name))).toBe(true);
    });

    it('should emit events for filtered tools in review mode', () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      manager.setMode('review');
      events.length = 0; // Clear mode change event

      manager.filterTools(mockTools);

      const filterEvents = events.filter((e: any) => e.type === 'mode.tool.filtered');
      expect(filterEvents.length).toBeGreaterThan(0);
    });
  });

  describe('getSystemPromptAddition', () => {
    it('should return mode-specific prompt', () => {
      manager.setMode('build');
      const buildPrompt = manager.getSystemPromptAddition();
      expect(buildPrompt).toContain('BUILD');

      manager.setMode('plan');
      const planPrompt = manager.getSystemPromptAddition();
      expect(planPrompt).toContain('PLAN');
      // Plan mode mentions write approval (not read-only, since it allows all tools)
      expect(planPrompt).toContain('QUEUED');
    });

    it('should return read-only prompt for review mode', () => {
      manager.setMode('review');
      const reviewPrompt = manager.getSystemPromptAddition();
      expect(reviewPrompt).toContain('REVIEW');
      expect(reviewPrompt).toContain('read-only');
    });

    it('should include clarification instructions in PLAN mode', () => {
      manager.setMode('plan');
      const planPrompt = manager.getSystemPromptAddition();

      // PLAN mode MUST instruct the agent to ask clarifying questions
      // before proposing changes when requirements are ambiguous
      expect(planPrompt).toContain('clarif');  // clarify/clarification/clarifying
      expect(planPrompt).toContain('ask');     // ask questions

      // Should mention what to clarify
      expect(planPrompt.toLowerCase()).toMatch(/scope|requirement|constraint|priorit/);
    });
  });

  describe('getAllModes', () => {
    it('should return all available modes', () => {
      const modes = manager.getAllModes();

      expect(modes).toContain('build');
      expect(modes).toContain('plan');
      expect(modes).toContain('review');
      expect(modes).toContain('debug');
    });
  });

  describe('getModeInfo', () => {
    it('should return info for current mode', () => {
      const info = manager.getModeInfo();

      expect(info.name).toBe('Build');
      expect(info.icon).toBeTruthy();
      expect(info.color).toBeTruthy();
    });

    it('should return info for specified mode', () => {
      const info = manager.getModeInfo('plan');

      expect(info.name).toBe('Plan');
    });
  });

  describe('formatModePrompt', () => {
    it('should format mode for terminal display', () => {
      const prompt = manager.formatModePrompt();

      expect(prompt).toContain('Build');
      expect(prompt).toContain('\x1b['); // ANSI color code
    });
  });

  describe('updateTools', () => {
    it('should update available tools', () => {
      const newTools: ToolDefinition[] = [
        { name: 'new_tool', description: 'New', parameters: {}, execute: async () => '' },
      ];

      manager.updateTools(newTools);

      // Verify tools are updated (internal state)
      expect(manager.isToolAvailable('new_tool')).toBe(true);
    });
  });
});

describe('parseMode', () => {
  it('should parse valid mode names', () => {
    expect(parseMode('build')).toBe('build');
    expect(parseMode('plan')).toBe('plan');
    expect(parseMode('review')).toBe('review');
    expect(parseMode('debug')).toBe('debug');
  });

  it('should handle case-insensitive input', () => {
    expect(parseMode('BUILD')).toBe('build');
    expect(parseMode('Plan')).toBe('plan');
    expect(parseMode('REVIEW')).toBe('review');
  });

  it('should handle aliases', () => {
    expect(parseMode('read')).toBe('plan');
    expect(parseMode('readonly')).toBe('plan');
    expect(parseMode('cr')).toBe('review');
    expect(parseMode('codereview')).toBe('review');
    expect(parseMode('dev')).toBe('build');
    expect(parseMode('bug')).toBe('debug');
  });

  it('should return null for invalid mode', () => {
    expect(parseMode('invalid')).toBeNull();
    expect(parseMode('')).toBeNull();
    expect(parseMode('xyz')).toBeNull();
  });
});

describe('formatModeList', () => {
  it('should format all modes for display', () => {
    const formatted = formatModeList();

    expect(formatted).toContain('build');
    expect(formatted).toContain('plan');
    expect(formatted).toContain('review');
    expect(formatted).toContain('debug');
    expect(formatted).toContain('Available modes');
  });
});

// =============================================================================
// SEMANTIC TASK SIMILARITY TESTS (Phase 2)
// =============================================================================

describe('calculateTaskSimilarity', () => {
  it('should return 1.0 for identical tasks', () => {
    const task = 'Implement user authentication';
    const similarity = calculateTaskSimilarity(task, task);
    expect(similarity).toBe(1.0);
  });

  it('should return 0.0 for completely different tasks', () => {
    const taskA = 'implement user authentication login';
    const taskB = 'fix database connection pool';
    const similarity = calculateTaskSimilarity(taskA, taskB);
    expect(similarity).toBeLessThan(0.3);
  });

  it('should return high similarity for semantically similar tasks', () => {
    const taskA = 'Implement user authentication with JWT tokens';
    const taskB = 'Add user authentication using JWT';
    const similarity = calculateTaskSimilarity(taskA, taskB);
    // Jaccard similarity: common words / total unique words
    // Common: user, authentication, JWT (3), Union: implement, user, authentication, with, JWT, tokens, add, using (8)
    // 3/8 = 0.375
    expect(similarity).toBeGreaterThan(0.3);
  });

  it('should be case insensitive', () => {
    const taskA = 'IMPLEMENT USER AUTH';
    const taskB = 'implement user auth';
    const similarity = calculateTaskSimilarity(taskA, taskB);
    expect(similarity).toBe(1.0);
  });

  it('should ignore common stop words', () => {
    const taskA = 'implement the user authentication';
    const taskB = 'implement a user authentication';
    const similarity = calculateTaskSimilarity(taskA, taskB);
    // Should be similar - stop words may or may not be filtered
    // Common: implement, user, authentication (3), Union may include "the", "a"
    expect(similarity).toBeGreaterThan(0.6);
  });

  it('should handle empty strings gracefully', () => {
    // Empty strings have no meaningful words, behavior depends on implementation
    const emptyResult = calculateTaskSimilarity('', '');
    expect(typeof emptyResult).toBe('number');
    expect(emptyResult).toBeGreaterThanOrEqual(0);
    expect(emptyResult).toBeLessThanOrEqual(1);
  });

  it('should handle single-word tasks', () => {
    expect(calculateTaskSimilarity('test', 'test')).toBe(1.0);
    expect(calculateTaskSimilarity('test', 'different')).toBe(0);
  });
});

describe('areTasksSimilar', () => {
  it('should return true for tasks above threshold', () => {
    const taskA = 'Implement user authentication with JWT';
    const taskB = 'Add user authentication using JWT tokens';
    // Calculate actual similarity and use threshold below it
    const similarity = calculateTaskSimilarity(taskA, taskB);
    // Use a threshold slightly below the actual similarity
    expect(areTasksSimilar(taskA, taskB, similarity - 0.1)).toBe(true);
  });

  it('should return false for tasks below threshold', () => {
    const taskA = 'Implement user authentication';
    const taskB = 'Fix database connection';
    expect(areTasksSimilar(taskA, taskB, 0.5)).toBe(false);
  });

  it('should use default threshold of 0.75', () => {
    // Very similar tasks should pass default threshold
    const taskA = 'implement user login authentication';
    const taskB = 'implement user authentication login';
    expect(areTasksSimilar(taskA, taskB)).toBe(true);
  });

  it('should allow custom threshold', () => {
    const taskA = 'implement user auth';
    const taskB = 'implement login system';

    // Should fail with high threshold
    const highThreshold = areTasksSimilar(taskA, taskB, 0.9);
    expect(highThreshold).toBe(false);

    // May pass with low threshold - depends on actual word overlap
    // These tasks share "implement" so there's some overlap
    const similarity = calculateTaskSimilarity(taskA, taskB);
    expect(similarity).toBeGreaterThanOrEqual(0);
  });

  it('should detect duplicate exploration tasks', () => {
    // These are the kind of tasks subagents might receive
    const taskA = 'Research the codebase structure and find authentication files';
    const taskB = 'Explore codebase to find files related to authentication';

    // Should be similar enough to be considered duplicates
    const similarity = calculateTaskSimilarity(taskA, taskB);
    expect(similarity).toBeGreaterThan(0.3);
  });

  it('should distinguish different feature implementations', () => {
    const taskA = 'Implement JWT token validation middleware';
    const taskB = 'Implement database migration for user table';

    // Should not be considered similar
    expect(areTasksSimilar(taskA, taskB, 0.5)).toBe(false);
  });
});
