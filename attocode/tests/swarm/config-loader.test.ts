/**
 * Tests for swarm YAML config loader
 */
import { describe, it, expect } from 'vitest';
import { parseSwarmYaml, yamlToSwarmConfig, mergeSwarmConfigs, normalizeCapabilities } from '../../src/integrations/swarm/swarm-config-loader.js';
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
    // 'refactor' is normalized to 'code', deduped
    expect(config.workers![0].capabilities).toEqual(['code']);
  });

  it('should normalize write capability from yaml', () => {
    const yaml = `
workers:
  - name: synthesizer
    model: test/model
    capabilities: [write, refactor]
`;
    const config = yamlToSwarmConfig(parseSwarmYaml(yaml), 'test/orch');
    expect(config.workers).toHaveLength(1);
    // 'write' passes through, 'refactor' → 'code'
    expect(config.workers![0].capabilities).toContain('write');
    expect(config.workers![0].capabilities).toContain('code');
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

  it('should let CLI orchestratorModel override YAML when explicitly set', () => {
    const yamlPartial = {
      orchestratorModel: 'yaml/model',
    };
    const result = mergeSwarmConfigs(DEFAULT_SWARM_CONFIG, yamlPartial, {
      orchestratorModel: 'cli/model',
      orchestratorModelExplicit: true,
    });
    expect(result.orchestratorModel).toBe('cli/model');
  });

  it('should keep YAML orchestrator when CLI model is not explicit', () => {
    const yamlPartial = {
      orchestratorModel: 'yaml/model',
    };
    const result = mergeSwarmConfigs(DEFAULT_SWARM_CONFIG, yamlPartial, {
      orchestratorModel: 'default/model',
      orchestratorModelExplicit: false,
    });
    expect(result.orchestratorModel).toBe('yaml/model');
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

describe('yamlToSwarmConfig snake_case features', () => {
  it('should load wave_review (snake_case) from features', () => {
    const yaml = parseSwarmYaml(`
features:
  wave_review: true
  verification: false
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.enableWaveReview).toBe(true);
    expect(config.enableVerification).toBe(false);
  });

  it('should load waveReview (camelCase) from features', () => {
    const yaml = parseSwarmYaml(`
features:
  waveReview: true
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.enableWaveReview).toBe(true);
  });

  it('should load dispatch_stagger_ms (snake_case) from budget', () => {
    const yaml = parseSwarmYaml(`
budget:
  dispatch_stagger_ms: 250
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.dispatchStaggerMs).toBe(250);
  });

  it('should load dispatchStaggerMs (camelCase) from budget', () => {
    const yaml = parseSwarmYaml(`
budget:
  dispatchStaggerMs: 500
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.dispatchStaggerMs).toBe(500);
  });

  it('should load orchestrator model from models section', () => {
    const yaml = parseSwarmYaml(`
models:
  orchestrator: anthropic/claude-sonnet-4
  quality_gate: google/gemini-2.0-flash-001
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.orchestratorModel).toBe('anthropic/claude-sonnet-4');
    expect(config.qualityGateModel).toBe('google/gemini-2.0-flash-001');
  });

  it('should load quality_gate (snake_case) from models section', () => {
    const yaml = parseSwarmYaml(`
models:
  quality_gate: test/gate-model
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.qualityGateModel).toBe('test/gate-model');
  });

  it('should load quality gates from quality.gates and quality.gate_model', () => {
    const yaml = parseSwarmYaml(`
quality:
  gates: true
  gate_model: test/quality-model
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.qualityGates).toBe(true);
    expect(config.qualityGateModel).toBe('test/quality-model');
  });

  it('should load resilience snake_case aliases', () => {
    const yaml = parseSwarmYaml(`
resilience:
  max_concurrency: 4
  worker_retries: 3
  rate_limit_retries: 5
  dispatch_stagger_ms: 250
  model_failover: false
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.maxConcurrency).toBe(4);
    expect(config.workerRetries).toBe(3);
    expect(config.rateLimitRetries).toBe(5);
    expect(config.dispatchStaggerMs).toBe(250);
    expect(config.enableModelFailover).toBe(false);
  });

  it('should load communication snake_case aliases', () => {
    const yaml = parseSwarmYaml(`
communication:
  dependency_context_max_length: 3000
  include_file_list: false
`);
    const config = yamlToSwarmConfig(yaml, 'test/orch');
    expect(config.communication?.dependencyContextMaxLength).toBe(3000);
    expect(config.communication?.includeFileList).toBe(false);
  });
});

describe('normalizeCapabilities', () => {
  it('should pass valid capabilities through', () => {
    expect(normalizeCapabilities(['code', 'research', 'write'])).toEqual(['code', 'research', 'write']);
  });

  it('should map refactor to code', () => {
    expect(normalizeCapabilities(['refactor'])).toEqual(['code']);
  });

  it('should map implement to code', () => {
    expect(normalizeCapabilities(['implement'])).toEqual(['code']);
  });

  it('should map writing/synthesis/merge to write', () => {
    expect(normalizeCapabilities(['writing'])).toEqual(['write']);
    expect(normalizeCapabilities(['synthesis'])).toEqual(['write']);
    expect(normalizeCapabilities(['merge'])).toEqual(['write']);
  });

  it('should map docs/documentation to document', () => {
    expect(normalizeCapabilities(['docs'])).toEqual(['document']);
    expect(normalizeCapabilities(['documentation'])).toEqual(['document']);
  });

  it('should drop unknown capabilities', () => {
    expect(normalizeCapabilities(['code', 'teleport', 'fly'])).toEqual(['code']);
  });

  it('should deduplicate capabilities', () => {
    expect(normalizeCapabilities(['code', 'refactor', 'implement'])).toEqual(['code']);
  });

  it('should fall back to code when empty after filtering', () => {
    expect(normalizeCapabilities(['unknown', 'invalid'])).toEqual(['code']);
    expect(normalizeCapabilities([])).toEqual(['code']);
  });

  it('should handle case insensitivity', () => {
    expect(normalizeCapabilities(['Code', 'RESEARCH'])).toEqual(['code', 'research']);
  });
});
