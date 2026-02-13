/**
 * Tests for generateLightweightRepoMap.
 */
import { describe, it, expect } from 'vitest';
import { generateLightweightRepoMap, type RepoMap, type CodeChunk } from '../src/integrations/codebase-context.js';

function createMockChunk(overrides: Partial<CodeChunk> = {}): CodeChunk {
  const filePath = overrides.filePath || 'src/index.ts';
  return {
    id: filePath,
    filePath,
    content: 'export default {}',
    tokenCount: 100,
    importance: 0.5,
    type: 'core_module',
    symbols: ['default'],
    dependencies: [],
    ...overrides,
  };
}

function createMockRepoMap(chunks: Array<Partial<CodeChunk>>): RepoMap {
  const chunkMap = new Map<string, CodeChunk>();
  for (const c of chunks) {
    const chunk = createMockChunk(c);
    chunkMap.set(chunk.id, chunk);
  }
  return {
    root: '/project',
    chunks: chunkMap,
    entryPoints: [],
    coreModules: [],
    dependencyGraph: new Map(),
    reverseDependencyGraph: new Map(),
    totalTokens: chunks.length * 100,
    analyzedAt: new Date(),
  };
}

describe('generateLightweightRepoMap', () => {
  it('generates file tree with symbols from RepoMap', () => {
    const repoMap = createMockRepoMap([
      { filePath: 'src/agent.ts', symbols: ['ProductionAgent', 'run', 'cleanup'], importance: 0.9 },
      { filePath: 'src/tools/bash.ts', symbols: ['BashTool'], importance: 0.7 },
    ]);
    const result = generateLightweightRepoMap(repoMap);
    expect(result).toContain('src/');
    expect(result).toContain('agent.ts (ProductionAgent, run, cleanup)');
    expect(result).toContain('src/tools/');
    expect(result).toContain('bash.ts (BashTool)');
  });

  it('includes Repository Map header', () => {
    const repoMap = createMockRepoMap([
      { filePath: 'src/index.ts', symbols: ['main'], importance: 0.5 },
    ]);
    const result = generateLightweightRepoMap(repoMap);
    expect(result).toContain('## Repository Map');
  });

  it('respects maxTokens budget', () => {
    const manyFiles = Array.from({ length: 100 }, (_, i) => ({
      filePath: `src/file${i}.ts`,
      symbols: [`Class${i}`],
      importance: 0.5,
    }));
    const repoMap = createMockRepoMap(manyFiles);
    const result = generateLightweightRepoMap(repoMap, 200); // Very small budget
    expect(result).toContain('... (truncated)');
    // Should not contain all 100 files
    const lineCount = result.split('\n').length;
    expect(lineCount).toBeLessThan(105);
  });

  it('sorts by importance within directories', () => {
    const repoMap = createMockRepoMap([
      { filePath: 'src/low.ts', symbols: ['Low'], importance: 0.1 },
      { filePath: 'src/high.ts', symbols: ['High'], importance: 0.9 },
    ]);
    const result = generateLightweightRepoMap(repoMap);
    const highIdx = result.indexOf('high.ts');
    const lowIdx = result.indexOf('low.ts');
    expect(highIdx).toBeLessThan(lowIdx);
  });

  it('sorts directories alphabetically', () => {
    const repoMap = createMockRepoMap([
      { filePath: 'src/z-module/index.ts', symbols: ['Z'], importance: 0.5 },
      { filePath: 'src/a-module/index.ts', symbols: ['A'], importance: 0.5 },
    ]);
    const result = generateLightweightRepoMap(repoMap);
    const aIdx = result.indexOf('src/a-module/');
    const zIdx = result.indexOf('src/z-module/');
    expect(aIdx).toBeLessThan(zIdx);
  });

  it('handles files with no symbols', () => {
    const repoMap = createMockRepoMap([
      { filePath: 'src/empty.ts', symbols: [], importance: 0.3 },
    ]);
    const result = generateLightweightRepoMap(repoMap);
    expect(result).toContain('empty.ts');
    // Should NOT have parentheses with empty symbols
    expect(result).not.toContain('empty.ts ()');
  });

  it('limits symbols to 5 per file', () => {
    const repoMap = createMockRepoMap([
      {
        filePath: 'src/big.ts',
        symbols: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'],
        importance: 0.5,
      },
    ]);
    const result = generateLightweightRepoMap(repoMap);
    // Should have at most 5 symbols
    const match = result.match(/\(([^)]+)\)/);
    expect(match).toBeTruthy();
    const symbolCount = match![1].split(',').length;
    expect(symbolCount).toBeLessThanOrEqual(5);
  });

  it('handles empty repo map', () => {
    const repoMap = createMockRepoMap([]);
    const result = generateLightweightRepoMap(repoMap);
    expect(result).toContain('## Repository Map');
    // No files means just the header
    expect(result.trim().split('\n').length).toBeLessThanOrEqual(2);
  });
});
