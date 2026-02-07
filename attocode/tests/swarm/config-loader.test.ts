/**
 * Tests for swarm YAML config loader
 */
import { describe, it, expect } from 'vitest';
import { parseSwarmYaml, yamlToSwarmConfig, mergeSwarmConfigs } from '../../src/integrations/swarm/swarm-config-loader.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';

// Helper to access nested yaml result properties
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyObj = Record<string, any>;

describe('parseSwarmYaml', () => {
  it('should parse basic key-value pairs', () => {
    const yaml = `
philosophy: Write clean code.
models:
  orchestrator: google/gemini-2.0-flash-001
  paid_only: true
`;
    const result = parseSwarmYaml(yaml) as AnyObj;
    expect(result.philosophy).toBe('Write clean code.');
    expect(result.models?.orchestrator).toBe('google/gemini-2.0-flash-001');
    expect(result.models?.paid_only).toBe(true);
  });

  it('should parse worker array with capabilities', () => {
    const yaml = `
workers:
  - name: coder
    model: test/model
    capabilities: [code, refactor]
    persona: You are a TypeScript expert.
  - name: researcher
    model: test/model2
    capabilities: [research]
`;
    const result = parseSwarmYaml(yaml) as AnyObj;
    expect(result.workers).toHaveLength(2);
    expect(result.workers![0].name).toBe('coder');
    // Raw YAML parser returns inline arrays as strings; yamlToSwarmConfig handles the split
    expect(result.workers![0].capabilities).toBe('[code, refactor]');
    expect(result.workers![0].persona).toBe('You are a TypeScript expert.');
    expect(result.workers![1].name).toBe('researcher');
  });

  it('should convert inline capabilities to array in yamlToSwarmConfig', () => {
    const yaml = `
workers:
  - name: coder
    model: test/model
    capabilities: [code, refactor]
`;
    const config = yamlToSwarmConfig(parseSwarmYaml(yaml), 'test/orch');
    expect(config.workers).toHaveLength(1);
    expect(config.workers![0].capabilities).toEqual(['code', 'refactor']);
  });

  it('should parse hierarchy section', () => {
    const yaml = `
hierarchy:
  manager:
    model: anthropic/claude-sonnet-4
    persona: You are a strict reviewer.
  judge:
    model: google/gemini-flash
`;
    const result = parseSwarmYaml(yaml) as AnyObj;
    expect(result.hierarchy?.manager?.model).toBe('anthropic/claude-sonnet-4');
    expect(result.hierarchy?.manager?.persona).toBe('You are a strict reviewer.');
    expect(result.hierarchy?.judge?.model).toBe('google/gemini-flash');
  });

  it('should parse budget section', () => {
    const yaml = `
budget:
  total_tokens: 5000000
  max_cost: 2.50
  max_tokens_per_worker: 30000
`;
    const result = parseSwarmYaml(yaml) as AnyObj;
    expect(result.budget?.total_tokens).toBe(5000000);
    expect(result.budget?.max_cost).toBe(2.5);
    expect(result.budget?.max_tokens_per_worker).toBe(30000);
  });

  it('should handle multiline strings', () => {
    const yaml = `
philosophy: |
  Write clean code.
  Always test.
  Keep it simple.
`;
    const result = parseSwarmYaml(yaml) as AnyObj;
    expect(result.philosophy).toContain('Write clean code.');
    expect(result.philosophy).toContain('Always test.');
  });

  it('should skip comments and empty lines', () => {
    const yaml = `
# This is a comment
models:
  # Another comment
  orchestrator: test/model
`;
    const result = parseSwarmYaml(yaml) as AnyObj;
    expect(result.models?.orchestrator).toBe('test/model');
  });

  it('should handle boolean values', () => {
    const yaml = `
quality:
  gates: true
communication:
  blackboard: false
`;
    const result = parseSwarmYaml(yaml) as AnyObj;
    expect(result.quality?.gates).toBe(true);
    expect(result.communication?.blackboard).toBe(false);
  });
});

describe('yamlToSwarmConfig', () => {
  it('should map yaml to SwarmConfig', () => {
    const yaml = parseSwarmYaml(`
philosophy: Test-driven development
models:
  orchestrator: test/orch
  paid_only: true
budget:
  total_tokens: 3000000
  max_cost: 1.50
hierarchy:
  manager:
    model: premium/model
  judge:
    model: flash/model
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.philosophy).toBe('Test-driven development');
    expect(config.paidOnly).toBe(true);
    expect(config.totalBudget).toBe(3000000);
    expect(config.maxCost).toBe(1.5);
    expect(config.hierarchy?.manager?.model).toBe('premium/model');
    expect(config.hierarchy?.judge?.model).toBe('flash/model');
  });

  it('should map workers with personas', () => {
    const yaml = parseSwarmYaml(`
workers:
  - name: coder
    model: test/model
    capabilities: [code]
    persona: Expert coder
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.workers).toHaveLength(1);
    expect(config.workers![0].persona).toBe('Expert coder');
  });
});

describe('mergeSwarmConfigs', () => {
  it('should use defaults when no yaml config', () => {
    const result = mergeSwarmConfigs(DEFAULT_SWARM_CONFIG, null, {
      orchestratorModel: 'test/model',
    });
    expect(result.enabled).toBe(true);
    expect(result.orchestratorModel).toBe('test/model');
    expect(result.maxConcurrency).toBe(DEFAULT_SWARM_CONFIG.maxConcurrency);
  });

  it('should override defaults with yaml values', () => {
    const yamlPartial = {
      maxConcurrency: 10,
      philosophy: 'Be fast',
      paidOnly: true,
    };
    const result = mergeSwarmConfigs(DEFAULT_SWARM_CONFIG, yamlPartial, {
      orchestratorModel: 'test/model',
    });
    expect(result.maxConcurrency).toBe(10);
    expect(result.philosophy).toBe('Be fast');
    expect(result.paidOnly).toBe(true);
  });

  it('should apply CLI paidOnly override', () => {
    const result = mergeSwarmConfigs(DEFAULT_SWARM_CONFIG, null, {
      orchestratorModel: 'test/model',
      paidOnly: true,
    });
    expect(result.paidOnly).toBe(true);
  });

  it('should merge hierarchy from yaml', () => {
    const yamlPartial = {
      hierarchy: {
        manager: { model: 'premium/model', persona: 'strict' },
        judge: { model: 'flash/model' },
      },
    };
    const result = mergeSwarmConfigs(DEFAULT_SWARM_CONFIG, yamlPartial, {
      orchestratorModel: 'test/model',
    });
    expect(result.hierarchy?.manager?.model).toBe('premium/model');
    expect(result.hierarchy?.manager?.persona).toBe('strict');
    expect(result.hierarchy?.judge?.model).toBe('flash/model');
  });
});
