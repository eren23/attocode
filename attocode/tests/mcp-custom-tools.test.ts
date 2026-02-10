/**
 * MCP Custom Tools Tests
 */

import { describe, it, expect } from 'vitest';
import {
  createSerperSearchTool,
  createCustomTool,
  createCustomTools,
  customToolToRegistryFormat,
  type GenericToolSpec,
} from '../src/integrations/mcp-custom-tools.js';

describe('createSerperSearchTool', () => {
  it('should create a tool with correct name and description', () => {
    const tool = createSerperSearchTool({ apiKey: 'test-key' });
    expect(tool.name).toBe('web_search');
    expect(tool.description.toLowerCase()).toContain('search');
    expect(tool.description).toContain('Serper');
  });

  it('should have correct input schema', () => {
    const tool = createSerperSearchTool({ apiKey: 'test-key' });
    const schema = tool.inputSchema as { properties: Record<string, unknown>; required: string[] };
    expect(schema.properties).toHaveProperty('query');
    expect(schema.required).toContain('query');
  });

  it('should be marked as safe', () => {
    const tool = createSerperSearchTool({ apiKey: 'key' });
    expect(tool.dangerLevel).toBe('safe');
    expect(tool.category).toBe('search');
  });

  it('should return error when API key is missing', async () => {
    // Remove env var temporarily
    const old = process.env.SERPER_API_KEY;
    delete process.env.SERPER_API_KEY;

    const tool = createSerperSearchTool({ apiKey: undefined });
    const result = await tool.execute({ query: 'test' });
    expect(result.success).toBe(false);
    expect(result.content).toContain('SERPER_API_KEY');

    if (old) process.env.SERPER_API_KEY = old;
  });

  it('should return error for empty query', async () => {
    const tool = createSerperSearchTool({ apiKey: 'key' });
    const result = await tool.execute({ query: '' });
    expect(result.success).toBe(false);
    expect(result.content).toContain('required');
  });
});

describe('createCustomTool', () => {
  it('should create a tool with correct metadata', () => {
    const spec: GenericToolSpec = {
      name: 'my_api',
      description: 'Calls my API endpoint for data retrieval.',
      inputSchema: { type: 'object', properties: { id: { type: 'string' } } },
      url: 'https://example.com/api',
    };
    const tool = createCustomTool(spec);
    expect(tool.name).toBe('my_api');
    expect(tool.description).toBe(spec.description);
    expect(tool.dangerLevel).toBe('moderate');
  });

  it('should respect custom danger level', () => {
    const spec: GenericToolSpec = {
      name: 'safe_tool',
      description: 'A safe read-only tool for reading data.',
      inputSchema: {},
      url: 'https://example.com',
      dangerLevel: 'safe',
    };
    const tool = createCustomTool(spec);
    expect(tool.dangerLevel).toBe('safe');
  });

  it('should have an execute function', () => {
    const spec: GenericToolSpec = {
      name: 'tool',
      description: 'A tool that does something useful and important.',
      inputSchema: {},
      url: 'https://example.com',
    };
    const tool = createCustomTool(spec);
    expect(tool.execute).toBeTypeOf('function');
  });
});

describe('createCustomTools', () => {
  it('should create multiple tools from specs', () => {
    const specs: GenericToolSpec[] = [
      { name: 'a', description: 'Tool A does something.', inputSchema: {}, url: 'https://a.com' },
      { name: 'b', description: 'Tool B does something.', inputSchema: {}, url: 'https://b.com' },
    ];
    const tools = createCustomTools(specs);
    expect(tools).toHaveLength(2);
    expect(tools[0].name).toBe('a');
    expect(tools[1].name).toBe('b');
  });
});

describe('customToolToRegistryFormat', () => {
  it('should convert to registry format', () => {
    const tool = createSerperSearchTool({ apiKey: 'key' });
    const reg = customToolToRegistryFormat(tool);
    expect(reg).toHaveProperty('name', 'web_search');
    expect(reg).toHaveProperty('description');
    expect(reg).toHaveProperty('inputSchema');
    expect(reg).toHaveProperty('dangerLevel', 'safe');
  });

  it('should default dangerLevel to moderate', () => {
    const reg = customToolToRegistryFormat({
      name: 'tool',
      description: 'A custom tool.',
      inputSchema: {},
      execute: async () => ({ success: true, content: '' }),
    });
    expect(reg.dangerLevel).toBe('moderate');
  });
});
