/**
 * Tests for Dependency Graph Visualization
 *
 * Tests the generation of visual diagrams from dependency graphs
 * in multiple formats (Mermaid, DOT, ASCII).
 */

import { describe, it, expect } from 'vitest';
import {
  generateDependencyDiagram,
  generateFocusedDiagram,
  generateReverseDiagram,
  createGraphVisualizer,
  type FileDependencyGraph,
} from '../../src/integrations/utilities/graph-visualization.js';

// =============================================================================
// TEST FIXTURES
// =============================================================================

function createTestGraph(): FileDependencyGraph {
  const graph = new Map<string, Set<string>>();

  graph.set('src/main.ts', new Set(['src/app.ts', 'src/utils.ts']));
  graph.set('src/app.ts', new Set(['src/services/auth.ts', 'src/services/api.ts']));
  graph.set('src/utils.ts', new Set());
  graph.set('src/services/auth.ts', new Set(['src/utils.ts']));
  graph.set('src/services/api.ts', new Set(['src/utils.ts', 'src/services/auth.ts']));

  return graph;
}

function createLargeGraph(nodeCount: number): FileDependencyGraph {
  const graph = new Map<string, Set<string>>();

  for (let i = 0; i < nodeCount; i++) {
    const deps = new Set<string>();
    // Each node depends on a few previous nodes
    for (let j = Math.max(0, i - 3); j < i; j++) {
      deps.add(`src/file${j}.ts`);
    }
    graph.set(`src/file${i}.ts`, deps);
  }

  return graph;
}

// =============================================================================
// TESTS: MERMAID FORMAT
// =============================================================================

describe('generateDependencyDiagram - Mermaid Format', () => {
  it('should generate valid Mermaid diagram', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'mermaid' });

    expect(result.content).toContain('```mermaid');
    expect(result.content).toContain('graph TD');
    expect(result.content).toContain('```');
    expect(result.nodeCount).toBeGreaterThan(0);
  });

  it('should include all nodes in small graphs', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'mermaid' });

    expect(result.nodeCount).toBe(5);
    expect(result.content).toContain('main.ts');
    expect(result.content).toContain('app.ts');
    expect(result.content).toContain('utils.ts');
  });

  it('should show edges between nodes', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'mermaid' });

    expect(result.content).toContain('-->');
    expect(result.edgeCount).toBeGreaterThan(0);
  });

  it('should respect direction option', () => {
    const graph = createTestGraph();

    const tdResult = generateDependencyDiagram(graph, { format: 'mermaid', direction: 'TD' });
    expect(tdResult.content).toContain('graph TD');

    const lrResult = generateDependencyDiagram(graph, { format: 'mermaid', direction: 'LR' });
    expect(lrResult.content).toContain('graph LR');
  });

  it('should highlight specified files', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, {
      format: 'mermaid',
      highlightFiles: ['src/main.ts'],
    });

    expect(result.content).toContain(':::highlighted');
    expect(result.content).toContain('classDef highlighted');
  });

  it('should include title when provided', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, {
      format: 'mermaid',
      title: 'My Project Dependencies',
    });

    expect(result.content).toContain('My Project Dependencies');
  });

  it('should limit nodes with maxNodes option', () => {
    const graph = createLargeGraph(100);
    const result = generateDependencyDiagram(graph, {
      format: 'mermaid',
      maxNodes: 10,
    });

    expect(result.nodeCount).toBeLessThanOrEqual(10);
    expect(result.excludedFiles.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// TESTS: DOT FORMAT
// =============================================================================

describe('generateDependencyDiagram - DOT Format', () => {
  it('should generate valid DOT diagram', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'dot' });

    expect(result.content).toContain('digraph dependencies');
    expect(result.content).toContain('rankdir=');
    expect(result.content).toContain('}');
  });

  it('should include node definitions', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'dot' });

    expect(result.content).toContain('[label=');
    expect(result.nodeCount).toBe(5);
  });

  it('should include edge definitions', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'dot' });

    expect(result.content).toContain('->');
    expect(result.edgeCount).toBeGreaterThan(0);
  });

  it('should highlight specified files with fill color', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, {
      format: 'dot',
      highlightFiles: ['src/main.ts'],
    });

    expect(result.content).toContain('fillcolor=');
  });

  it('should respect direction option', () => {
    const graph = createTestGraph();

    const lrResult = generateDependencyDiagram(graph, { format: 'dot', direction: 'LR' });
    expect(lrResult.content).toContain('rankdir=LR');
  });

  it('should include title as label', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, {
      format: 'dot',
      title: 'Project Graph',
    });

    expect(result.content).toContain('label="Project Graph"');
  });
});

// =============================================================================
// TESTS: ASCII FORMAT
// =============================================================================

describe('generateDependencyDiagram - ASCII Format', () => {
  it('should generate ASCII tree diagram', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'ascii' });

    expect(result.content).toContain('├──');
    expect(result.content).toContain('└──');
  });

  it('should show file names with their dependencies', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'ascii' });

    expect(result.content).toContain('main.ts');
    expect(result.content).toContain('app.ts');
    expect(result.content).toContain('utils.ts');
  });

  it('should indicate files with no dependencies', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, { format: 'ascii' });

    expect(result.content).toContain('(no dependencies)');
  });

  it('should highlight specified files with prefix', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, {
      format: 'ascii',
      highlightFiles: ['src/main.ts'],
    });

    expect(result.content).toContain('>>> ');
  });

  it('should include title when provided', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, {
      format: 'ascii',
      title: 'My Dependencies',
    });

    expect(result.content).toContain('=== My Dependencies ===');
  });

  it('should indicate excluded files when limit reached', () => {
    const graph = createLargeGraph(100);
    const result = generateDependencyDiagram(graph, {
      format: 'ascii',
      maxNodes: 5,
    });

    expect(result.content).toContain('more files');
  });
});

// =============================================================================
// TESTS: FILTERING
// =============================================================================

describe('generateDependencyDiagram - Filtering', () => {
  it('should exclude external dependencies by default', () => {
    const graph = new Map<string, Set<string>>();
    graph.set('src/main.ts', new Set(['node_modules/lodash/index.js', 'src/utils.ts']));
    graph.set('src/utils.ts', new Set());

    const result = generateDependencyDiagram(graph, { format: 'mermaid' });

    expect(result.content).not.toContain('lodash');
    expect(result.content).toContain('utils.ts');
  });

  it('should include external dependencies when requested', () => {
    const graph = new Map<string, Set<string>>();
    graph.set('src/main.ts', new Set(['node_modules/lodash/index.js', 'src/utils.ts']));
    // Note: lodash needs to be a key in the graph to be included as a node
    graph.set('node_modules/lodash/index.js', new Set());

    const result = generateDependencyDiagram(graph, {
      format: 'mermaid',
      includeExternal: true,
    });

    expect(result.content).toContain('lodash');
  });

  it('should filter by patterns', () => {
    // Only include files that match the pattern as keys
    const graph = new Map<string, Set<string>>();
    graph.set('src/services/auth.ts', new Set(['src/utils.ts']));
    graph.set('src/services/api.ts', new Set(['src/utils.ts']));
    graph.set('src/main.ts', new Set()); // This should be filtered out

    const result = generateDependencyDiagram(graph, {
      format: 'mermaid',
      filterPatterns: ['services'], // Simple includes pattern
    });

    expect(result.content).toContain('auth.ts');
    expect(result.content).toContain('api.ts');
    expect(result.content).not.toContain('main.ts');
  });
});

// =============================================================================
// TESTS: FOCUSED DIAGRAM
// =============================================================================

describe('generateFocusedDiagram', () => {
  it('should generate diagram centered on specific file', () => {
    const graph = createTestGraph();
    const result = generateFocusedDiagram(graph, 'src/app.ts', { format: 'mermaid' });

    expect(result.content).toContain('app.ts');
    expect(result.nodeCount).toBeGreaterThan(0);
  });

  it('should include file dependencies', () => {
    const graph = createTestGraph();
    const result = generateFocusedDiagram(graph, 'src/app.ts', { format: 'mermaid' });

    // app.ts depends on auth.ts and api.ts
    expect(result.content).toContain('auth.ts');
    expect(result.content).toContain('api.ts');
  });

  it('should highlight the center file', () => {
    const graph = createTestGraph();
    const result = generateFocusedDiagram(graph, 'src/app.ts', { format: 'mermaid' });

    expect(result.content).toContain(':::highlighted');
  });

  it('should include default title with file name', () => {
    const graph = createTestGraph();
    const result = generateFocusedDiagram(graph, 'src/app.ts', { format: 'mermaid' });

    expect(result.content).toContain('Dependencies of app.ts');
  });
});

// =============================================================================
// TESTS: REVERSE DIAGRAM
// =============================================================================

describe('generateReverseDiagram', () => {
  it('should generate diagram showing what depends on a file', () => {
    // Create reverse dependency graph where the center file is a key
    // The files in the Set are what the center file "points to" in reverse deps
    const reverseGraph = new Map<string, Set<string>>();
    reverseGraph.set('src/utils.ts', new Set(['src/services/auth.ts']));
    reverseGraph.set('src/services/auth.ts', new Set()); // This ensures auth.ts is also a node

    const result = generateReverseDiagram(reverseGraph, 'src/utils.ts', { format: 'mermaid' });

    expect(result.content).toContain('utils.ts');
    expect(result.content).toContain('auth.ts');
  });

  it('should include default title for reverse dependencies', () => {
    const reverseGraph = new Map<string, Set<string>>();
    reverseGraph.set('src/utils.ts', new Set());

    const result = generateReverseDiagram(reverseGraph, 'src/utils.ts', { format: 'mermaid' });

    expect(result.content).toContain('Files that depend on utils.ts');
  });
});

// =============================================================================
// TESTS: FACTORY FUNCTION
// =============================================================================

describe('createGraphVisualizer', () => {
  it('should create visualizer with default options', () => {
    const visualizer = createGraphVisualizer({ format: 'mermaid' });
    const graph = createTestGraph();

    const result = visualizer.generate(graph);

    expect(result.content).toContain('```mermaid');
  });

  it('should allow overriding defaults per call', () => {
    const visualizer = createGraphVisualizer({ format: 'mermaid', direction: 'TD' });
    const graph = createTestGraph();

    const result = visualizer.generate(graph, { direction: 'LR' });

    expect(result.content).toContain('graph LR');
  });

  it('should have focused method', () => {
    const visualizer = createGraphVisualizer({ format: 'mermaid' });
    const graph = createTestGraph();

    const result = visualizer.focused(graph, 'src/main.ts');

    expect(result.content).toContain('main.ts');
    expect(result.content).toContain(':::highlighted');
  });

  it('should have reverse method', () => {
    const reverseGraph = new Map<string, Set<string>>();
    reverseGraph.set('src/utils.ts', new Set(['src/main.ts']));

    const visualizer = createGraphVisualizer({ format: 'ascii' });
    const result = visualizer.reverse(reverseGraph, 'src/utils.ts');

    expect(result.content).toContain('utils.ts');
  });
});

// =============================================================================
// TESTS: EDGE CASES
// =============================================================================

describe('generateDependencyDiagram - Edge Cases', () => {
  it('should handle empty graph', () => {
    const graph = new Map<string, Set<string>>();
    const result = generateDependencyDiagram(graph, { format: 'mermaid' });

    expect(result.nodeCount).toBe(0);
    expect(result.edgeCount).toBe(0);
    expect(result.content).toContain('```mermaid');
    expect(result.content).toContain('```');
  });

  it('should handle graph with no edges', () => {
    const graph = new Map<string, Set<string>>();
    graph.set('src/file1.ts', new Set());
    graph.set('src/file2.ts', new Set());

    const result = generateDependencyDiagram(graph, { format: 'mermaid' });

    expect(result.nodeCount).toBe(2);
    expect(result.edgeCount).toBe(0);
  });

  it('should handle circular dependencies', () => {
    const graph = new Map<string, Set<string>>();
    graph.set('src/a.ts', new Set(['src/b.ts']));
    graph.set('src/b.ts', new Set(['src/a.ts']));

    const result = generateDependencyDiagram(graph, { format: 'mermaid' });

    expect(result.nodeCount).toBe(2);
    expect(result.edgeCount).toBe(2);
  });

  it('should sanitize special characters in file paths', () => {
    const graph = new Map<string, Set<string>>();
    graph.set('src/file-with-dashes.ts', new Set(['src/file.with.dots.ts']));
    graph.set('src/file.with.dots.ts', new Set());

    // Should not throw
    const mermaidResult = generateDependencyDiagram(graph, { format: 'mermaid' });
    expect(mermaidResult.nodeCount).toBe(2);

    const dotResult = generateDependencyDiagram(graph, { format: 'dot' });
    expect(dotResult.nodeCount).toBe(2);
  });

  it('should handle deeply nested paths', () => {
    const graph = new Map<string, Set<string>>();
    graph.set('src/a/b/c/d/e/deeply-nested.ts', new Set(['src/utils.ts']));
    graph.set('src/utils.ts', new Set());

    const result = generateDependencyDiagram(graph, { format: 'mermaid' });

    // Should show just the file name in the label
    expect(result.content).toContain('deeply-nested.ts');
  });
});

// =============================================================================
// TESTS: GROUP BY DIRECTORY
// =============================================================================

describe('generateDependencyDiagram - Group by Directory', () => {
  it('should group nodes by directory in Mermaid', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, {
      format: 'mermaid',
      groupByDirectory: true,
    });

    expect(result.content).toContain('subgraph');
    expect(result.content).toContain('end');
  });

  it('should create separate subgraphs for each directory', () => {
    const graph = createTestGraph();
    const result = generateDependencyDiagram(graph, {
      format: 'mermaid',
      groupByDirectory: true,
    });

    // Should have subgraphs for 'src' and 'src/services'
    expect(result.content).toContain('subgraph');
  });
});
