/**
 * Mode Switching Tests
 *
 * Tests for the agent mode system (build/plan/review/debug).
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  ModeManager,
  createModeManager,
  formatModeList,
  parseMode,
  MODES,
  READ_ONLY_TOOLS,
  ALL_TOOLS,
  type AgentMode,
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
    for (const [key, config] of Object.entries(MODES)) {
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

  it('plan mode should have read-only tools', () => {
    for (const tool of READ_ONLY_TOOLS) {
      expect(MODES.plan.availableTools).toContain(tool);
    }
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

    it('should restrict tools in plan mode', () => {
      manager.setMode('plan');

      expect(manager.isToolAvailable('read_file')).toBe(true);
      expect(manager.isToolAvailable('list_files')).toBe(true);
      // write_file is not in READ_ONLY_TOOLS
      expect(manager.isToolAvailable('write_file')).toBe(false);
    });
  });

  describe('filterTools', () => {
    it('should return all tools in build mode', () => {
      manager.setMode('build');
      const filtered = manager.filterTools(mockTools);

      expect(filtered.length).toBe(mockTools.length);
    });

    it('should filter tools in plan mode', () => {
      manager.setMode('plan');
      const filtered = manager.filterTools(mockTools);

      // Only read-only tools should remain
      expect(filtered.length).toBeLessThan(mockTools.length);
      expect(filtered.every(t => READ_ONLY_TOOLS.includes(t.name))).toBe(true);
    });

    it('should emit events for filtered tools', () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      manager.setMode('plan');
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
      expect(planPrompt).toContain('read-only');
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
