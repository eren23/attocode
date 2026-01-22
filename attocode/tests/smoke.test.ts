/**
 * Smoke tests - verify all modules can be imported and basic initialization works
 */
import { describe, it, expect } from 'vitest';

describe('Smoke Tests', () => {
  describe('Core modules import correctly', () => {
    it('imports types', async () => {
      const types = await import('../src/types.js');
      expect(types).toBeDefined();
    });

    it('imports defaults', async () => {
      const defaults = await import('../src/defaults.js');
      expect(defaults).toBeDefined();
    });

    it('imports modes', async () => {
      const modes = await import('../src/modes.js');
      expect(modes).toBeDefined();
    });

    it('imports adapters', async () => {
      const adapters = await import('../src/adapters.js');
      expect(adapters).toBeDefined();
    });
  });

  describe('Provider modules import correctly', () => {
    it('imports provider types', async () => {
      const types = await import('../src/providers/types.js');
      expect(types).toBeDefined();
    });

    it('imports provider factory', async () => {
      const provider = await import('../src/providers/provider.js');
      expect(provider.getProvider).toBeDefined();
    });

    it('imports mock adapter', async () => {
      const mock = await import('../src/providers/adapters/mock.js');
      expect(mock.MockProvider).toBeDefined();
    });
  });

  describe('Tool modules import correctly', () => {
    it('imports tool types', async () => {
      const types = await import('../src/tools/types.js');
      expect(types).toBeDefined();
    });

    it('imports tool registry', async () => {
      const registry = await import('../src/tools/registry.js');
      expect(registry.ToolRegistry).toBeDefined();
    });

    it('imports standard tools', async () => {
      const standard = await import('../src/tools/standard.js');
      expect(standard.createStandardRegistry).toBeDefined();
    });
  });

  describe('Integration modules import correctly', () => {
    it('imports integrations index', async () => {
      const integrations = await import('../src/integrations/index.js');
      expect(integrations).toBeDefined();
    });

    it('imports cancellation', async () => {
      const { CancellationManager } = await import('../src/integrations/cancellation.js');
      expect(CancellationManager).toBeDefined();
    });

    it('imports memory', async () => {
      const { MemoryManager } = await import('../src/integrations/memory.js');
      expect(MemoryManager).toBeDefined();
    });

    it('imports planning', async () => {
      const { PlanningManager } = await import('../src/integrations/planning.js');
      expect(PlanningManager).toBeDefined();
    });

    it('imports hooks', async () => {
      const { HookManager } = await import('../src/integrations/hooks.js');
      expect(HookManager).toBeDefined();
    });

    it('imports sandbox', async () => {
      const sandbox = await import('../src/integrations/sandbox/index.js');
      expect(sandbox).toBeDefined();
    });
  });

  describe('Observability modules import correctly', () => {
    it('imports tracer', async () => {
      const { Tracer } = await import('../src/observability/tracer.js');
      expect(Tracer).toBeDefined();
    });
  });

  describe('Tracing modules import correctly', () => {
    it('imports trace collector', async () => {
      const { TraceCollector } = await import('../src/tracing/trace-collector.js');
      expect(TraceCollector).toBeDefined();
    });
  });

  describe('Tricks modules import correctly', () => {
    it('imports json-utils', async () => {
      const { safeParseJson } = await import('../src/tricks/json-utils.js');
      expect(safeParseJson).toBeDefined();
    });

    it('imports kv-cache-context', async () => {
      const kvCache = await import('../src/tricks/kv-cache-context.js');
      expect(kvCache).toBeDefined();
    });
  });

  describe('Agent can be initialized', () => {
    it('imports ProductionAgent', async () => {
      const { ProductionAgent } = await import('../src/agent.js');
      expect(ProductionAgent).toBeDefined();
    });
  });
});
