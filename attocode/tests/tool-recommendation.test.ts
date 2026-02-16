/**
 * Tool Recommendation Engine Tests
 */

import { describe, it, expect } from 'vitest';
import {
  ToolRecommendationEngine,
  createToolRecommendationEngine,
} from '../src/integrations/quality/tool-recommendation.js';

const ALL_TOOLS = [
  'read_file', 'write_file', 'edit_file', 'bash',
  'glob', 'grep', 'list_files', 'search_files', 'search_code',
  'get_file_info', 'spawn_agent', 'web_search',
  'task_create', 'task_update', 'task_get', 'task_list',
  'mcp_playwright_navigate', 'mcp_playwright_click',
  'mcp_serper_search',
  'mcp_context7_query',
];

describe('ToolRecommendationEngine', () => {
  it('should recommend read and write tools for research tasks', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('analyze code patterns', 'research', ALL_TOOLS);
    const names = recs.map(r => r.toolName);
    expect(names).toContain('read_file');
    expect(names).toContain('glob');
    expect(names).toContain('grep');
    // Research tasks now include write tools so workers can produce report files
    expect(names).toContain('write_file');
    expect(names).toContain('edit_file');
  });

  it('should recommend web_search for research tasks', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('research market trends', 'research', ALL_TOOLS);
    const names = recs.map(r => r.toolName);
    expect(names).toContain('web_search');
  });

  it('should recommend task coordination tools for implement tasks', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('implement feature', 'implement', ALL_TOOLS);
    const names = recs.map(r => r.toolName);
    expect(names).toContain('task_create');
    expect(names).toContain('task_update');
  });

  it('should recommend write tools for implement tasks', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('implement auth feature', 'implement', ALL_TOOLS);
    const names = recs.map(r => r.toolName);
    expect(names).toContain('write_file');
    expect(names).toContain('edit_file');
    expect(names).toContain('bash');
  });

  it('should recommend bash for test tasks', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('run unit tests', 'test', ALL_TOOLS);
    const names = recs.map(r => r.toolName);
    expect(names).toContain('bash');
  });

  it('should include MCP tools for browser-related tasks', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('navigate to the page and click the button', 'test', ALL_TOOLS);
    const mcpTools = recs.filter(r => r.source === 'mcp');
    expect(mcpTools.length).toBeGreaterThan(0);
    expect(mcpTools.some(r => r.toolName.startsWith('mcp_playwright'))).toBe(true);
  });

  it('should include MCP tools for web search tasks', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('web search for latest docs', 'research', ALL_TOOLS);
    const mcpTools = recs.filter(r => r.source === 'mcp');
    expect(mcpTools.some(r => r.toolName.startsWith('mcp_serper'))).toBe(true);
  });

  it('should always include spawn_agent if available', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('do something', 'research', ALL_TOOLS);
    expect(recs.map(r => r.toolName)).toContain('spawn_agent');
  });

  it('should respect maxToolsPerAgent config', () => {
    const engine = new ToolRecommendationEngine({ maxToolsPerAgent: 3 });
    const recs = engine.recommendTools('implement feature', 'implement', ALL_TOOLS);
    expect(recs.length).toBeLessThanOrEqual(3);
  });

  it('should sort by relevance score descending', () => {
    const engine = new ToolRecommendationEngine();
    const recs = engine.recommendTools('implement feature', 'implement', ALL_TOOLS);
    for (let i = 1; i < recs.length; i++) {
      expect(recs[i - 1].relevanceScore).toBeGreaterThanOrEqual(recs[i].relevanceScore);
    }
  });

  it('should only recommend available tools', () => {
    const engine = new ToolRecommendationEngine();
    const limited = ['read_file', 'glob'];
    const recs = engine.recommendTools('search code', 'research', limited);
    for (const r of recs) {
      expect(limited).toContain(r.toolName);
    }
  });

  it('should use task-type overrides when provided', () => {
    const engine = new ToolRecommendationEngine({
      taskToolOverrides: { research: ['custom_tool'] },
    });
    const recs = engine.recommendTools('analyze', 'research', ['custom_tool', 'read_file']);
    expect(recs.map(r => r.toolName)).toContain('custom_tool');
  });
});

describe('getMCPPreloadPrefixes', () => {
  it('should return playwright prefix for browser tasks', () => {
    const engine = new ToolRecommendationEngine();
    const prefixes = engine.getMCPPreloadPrefixes('click the browser button');
    expect(prefixes).toContain('mcp_playwright');
  });

  it('should return empty when preloading is disabled', () => {
    const engine = new ToolRecommendationEngine({ enablePreloading: false });
    expect(engine.getMCPPreloadPrefixes('click browser')).toHaveLength(0);
  });

  it('should return empty for non-MCP tasks', () => {
    const engine = new ToolRecommendationEngine();
    expect(engine.getMCPPreloadPrefixes('fix a typo')).toHaveLength(0);
  });
});

describe('inferTaskType', () => {
  it('should map agent names to task types', () => {
    expect(ToolRecommendationEngine.inferTaskType('researcher')).toBe('research');
    expect(ToolRecommendationEngine.inferTaskType('coder')).toBe('implement');
    expect(ToolRecommendationEngine.inferTaskType('reviewer')).toBe('review');
    expect(ToolRecommendationEngine.inferTaskType('architect')).toBe('design');
    expect(ToolRecommendationEngine.inferTaskType('debugger')).toBe('analysis');
    expect(ToolRecommendationEngine.inferTaskType('tester')).toBe('test');
    expect(ToolRecommendationEngine.inferTaskType('documenter')).toBe('document');
    expect(ToolRecommendationEngine.inferTaskType('synthesizer')).toBe('merge');
    expect(ToolRecommendationEngine.inferTaskType('writer')).toBe('document');
    expect(ToolRecommendationEngine.inferTaskType('merger')).toBe('merge');
  });

  it('should default to research for unknown agent', () => {
    expect(ToolRecommendationEngine.inferTaskType('unknown')).toBe('research');
  });

  it('should map dynamic swarm worker names by role token', () => {
    expect(ToolRecommendationEngine.inferTaskType('swarm-coder-task-1')).toBe('implement');
    expect(ToolRecommendationEngine.inferTaskType('swarm-tester-task-2')).toBe('test');
    expect(ToolRecommendationEngine.inferTaskType('swarm-reviewer-task-3')).toBe('review');
    expect(ToolRecommendationEngine.inferTaskType('swarm-researcher-task-4')).toBe('research');
    expect(ToolRecommendationEngine.inferTaskType('swarm-synthesizer-task-5')).toBe('merge');
    expect(ToolRecommendationEngine.inferTaskType('swarm-writer-task-6')).toBe('document');
  });

  it('should default unknown swarm workers to implement', () => {
    expect(ToolRecommendationEngine.inferTaskType('swarm-foo-task-9')).toBe('implement');
  });
});

describe('createToolRecommendationEngine', () => {
  it('should create an engine with default config', () => {
    const engine = createToolRecommendationEngine();
    expect(engine).toBeInstanceOf(ToolRecommendationEngine);
  });
});
