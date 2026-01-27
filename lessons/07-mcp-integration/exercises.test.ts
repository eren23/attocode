/**
 * Exercise Tests: Lesson 7 - MCP Tool Discovery
 *
 * Run with: npm run test:lesson:7:exercise
 */

import { describe, it, expect, beforeEach } from 'vitest';

// Import from answers for testing
import {
  ToolDiscovery,
  formatToolForSummary,
  type ToolInfo,
} from './exercises/answers/exercise-1.js';

// =============================================================================
// TEST DATA
// =============================================================================

const sampleTools: ToolInfo[] = [
  {
    name: 'read_file',
    description: 'Read contents of a file from the filesystem',
    category: 'filesystem',
    parameters: [
      { name: 'path', type: 'string', required: true },
    ],
  },
  {
    name: 'write_file',
    description: 'Write content to a file',
    category: 'filesystem',
    parameters: [
      { name: 'path', type: 'string', required: true },
      { name: 'content', type: 'string', required: true },
    ],
  },
  {
    name: 'list_directory',
    description: 'List files in a directory',
    category: 'filesystem',
    parameters: [
      { name: 'path', type: 'string', required: true },
    ],
  },
  {
    name: 'search_code',
    description: 'Search for patterns in code files',
    category: 'search',
    parameters: [
      { name: 'pattern', type: 'string', required: true },
      { name: 'directory', type: 'string' },
    ],
  },
  {
    name: 'execute_command',
    description: 'Execute a shell command',
    category: 'system',
    parameters: [
      { name: 'command', type: 'string', required: true },
    ],
  },
];

// =============================================================================
// TESTS
// =============================================================================

describe('ToolDiscovery', () => {
  let discovery: ToolDiscovery;

  beforeEach(() => {
    discovery = new ToolDiscovery();
    discovery.registerTools(sampleTools);
  });

  describe('registerTool', () => {
    it('should register a tool', () => {
      const newDiscovery = new ToolDiscovery();
      newDiscovery.registerTool(sampleTools[0]);

      expect(newDiscovery.getToolCount()).toBe(1);
    });

    it('should update existing tool with same name', () => {
      const updated: ToolInfo = {
        ...sampleTools[0],
        description: 'Updated description',
      };

      discovery.registerTool(updated);

      expect(discovery.getToolCount()).toBe(5);
      const results = discovery.search('read_file');
      expect(results[0].description).toBe('Updated description');
    });
  });

  describe('search', () => {
    it('should find tools by exact name', () => {
      const results = discovery.search('read_file');

      expect(results.length).toBeGreaterThan(0);
      expect(results[0].name).toBe('read_file');
    });

    it('should find tools by partial name', () => {
      const results = discovery.search('file');

      // Should find tools with "file" in name (highest ranked) and description
      expect(results.length).toBeGreaterThanOrEqual(2);
      expect(results.some(t => t.name === 'read_file')).toBe(true);
      expect(results.some(t => t.name === 'write_file')).toBe(true);
      // Tools with "file" in name should be ranked higher
      expect(results[0].name).toContain('file');
      expect(results[1].name).toContain('file');
    });

    it('should find tools by description keywords', () => {
      const results = discovery.search('filesystem');

      expect(results.length).toBeGreaterThan(0);
    });

    it('should be case-insensitive', () => {
      const results1 = discovery.search('READ_FILE');
      const results2 = discovery.search('read_file');

      expect(results1.length).toBe(results2.length);
    });

    it('should return empty array for no matches', () => {
      const results = discovery.search('nonexistent_xyz');

      expect(results).toEqual([]);
    });

    it('should rank exact matches higher', () => {
      const results = discovery.search('read_file');

      expect(results[0].name).toBe('read_file');
    });
  });

  describe('getByCategory', () => {
    it('should return tools in category', () => {
      const results = discovery.getByCategory('filesystem');

      expect(results.length).toBe(3);
      expect(results.every(t => t.category === 'filesystem')).toBe(true);
    });

    it('should be case-insensitive', () => {
      const results = discovery.getByCategory('FILESYSTEM');

      expect(results.length).toBe(3);
    });

    it('should return empty for unknown category', () => {
      const results = discovery.getByCategory('unknown');

      expect(results).toEqual([]);
    });
  });

  describe('getAllTools', () => {
    it('should return all registered tools', () => {
      const all = discovery.getAllTools();

      expect(all.length).toBe(5);
    });

    it('should return empty array when no tools registered', () => {
      const empty = new ToolDiscovery();

      expect(empty.getAllTools()).toEqual([]);
    });
  });

  describe('getSummary', () => {
    it('should generate summary of all tools', () => {
      const summary = discovery.getSummary();

      expect(summary).toContain('Available tools:');
      expect(summary).toContain('read_file');
      expect(summary).toContain('write_file');
    });

    it('should generate summary of specific tools', () => {
      const fileTools = discovery.getByCategory('filesystem');
      const summary = discovery.getSummary(fileTools);

      expect(summary).toContain('read_file');
      expect(summary).not.toContain('search_code');
    });

    it('should include parameter information', () => {
      const summary = discovery.getSummary();

      expect(summary).toContain('Parameters:');
      expect(summary).toContain('path');
    });

    it('should handle empty tools gracefully', () => {
      const summary = discovery.getSummary([]);

      expect(summary).toContain('No tools');
    });
  });
});

describe('formatToolForSummary', () => {
  it('should format tool with parameters', () => {
    const tool: ToolInfo = {
      name: 'test_tool',
      description: 'A test tool',
      parameters: [
        { name: 'input', type: 'string', required: true },
      ],
    };

    const formatted = formatToolForSummary(tool);

    expect(formatted).toContain('test_tool');
    expect(formatted).toContain('A test tool');
    expect(formatted).toContain('input');
    expect(formatted).toContain('required');
  });

  it('should handle tool without parameters', () => {
    const tool: ToolInfo = {
      name: 'simple_tool',
      description: 'No params needed',
    };

    const formatted = formatToolForSummary(tool);

    expect(formatted).toContain('simple_tool');
    expect(formatted).not.toContain('Parameters:');
  });
});
