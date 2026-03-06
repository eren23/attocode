/**
 * Dependency Graph Visualization
 *
 * Generates visual representations of codebase dependency graphs.
 * Supports multiple output formats:
 * - Mermaid: Markdown-compatible diagrams (renders in GitHub, VS Code, etc.)
 * - DOT: GraphViz format for advanced visualization
 * - ASCII: Terminal-friendly text diagrams
 *
 * @example
 * ```typescript
 * const repoMap = await codebaseContext.analyze();
 * const diagram = generateDependencyDiagram(repoMap.dependencyGraph, {
 *   format: 'mermaid',
 *   maxNodes: 20,
 *   direction: 'LR',
 * });
 * console.log(diagram);
 * ```
 */

import * as path from 'path';

// =============================================================================
// TYPES
// =============================================================================

export type FileDependencyGraph = Map<string, Set<string>>;

export type DiagramFormat = 'mermaid' | 'dot' | 'ascii';
export type DiagramDirection = 'TD' | 'LR' | 'BT' | 'RL';

export interface GraphVisualizationOptions {
  /** Output format */
  format: DiagramFormat;
  /** Maximum number of nodes to include (prevents huge diagrams) */
  maxNodes?: number;
  /** Graph direction: TD (top-down), LR (left-right), BT (bottom-top), RL (right-left) */
  direction?: DiagramDirection;
  /** Include external dependencies (node_modules, etc.) */
  includeExternal?: boolean;
  /** Group files by directory */
  groupByDirectory?: boolean;
  /** Only show files matching these patterns */
  filterPatterns?: string[];
  /** Highlight these files (shown with different style) */
  highlightFiles?: string[];
  /** Title for the diagram */
  title?: string;
}

export interface DiagramResult {
  /** The generated diagram content */
  content: string;
  /** Number of nodes in the diagram */
  nodeCount: number;
  /** Number of edges in the diagram */
  edgeCount: number;
  /** Files that were excluded due to limits */
  excludedFiles: string[];
}

// =============================================================================
// MAIN API
// =============================================================================

/**
 * Generate a visual diagram of a dependency graph.
 */
export function generateDependencyDiagram(
  graph: FileDependencyGraph,
  options: Partial<GraphVisualizationOptions> = {},
): DiagramResult {
  const opts: GraphVisualizationOptions = {
    format: options.format ?? 'mermaid',
    maxNodes: options.maxNodes ?? 50,
    direction: options.direction ?? 'TD',
    includeExternal: options.includeExternal ?? false,
    groupByDirectory: options.groupByDirectory ?? false,
    filterPatterns: options.filterPatterns,
    highlightFiles: options.highlightFiles ?? [],
    title: options.title,
  };

  switch (opts.format) {
    case 'mermaid':
      return generateMermaidDiagram(graph, opts);
    case 'dot':
      return generateDotDiagram(graph, opts);
    case 'ascii':
      return generateAsciiDiagram(graph, opts);
    default:
      throw new Error(`Unsupported diagram format: ${opts.format}`);
  }
}

/**
 * Generate a focused diagram showing a file and its immediate dependencies.
 */
export function generateFocusedDiagram(
  graph: FileDependencyGraph,
  centerFile: string,
  options: Partial<GraphVisualizationOptions> = {},
): DiagramResult {
  // Extract subgraph centered on the specified file
  const subgraph = extractSubgraph(graph, centerFile, 2); // 2 levels of depth

  return generateDependencyDiagram(subgraph, {
    ...options,
    highlightFiles: [centerFile, ...(options.highlightFiles ?? [])],
    title: options.title ?? `Dependencies of ${path.basename(centerFile)}`,
  });
}

/**
 * Generate a diagram showing the reverse dependencies (what depends on this file).
 */
export function generateReverseDiagram(
  reverseFileDependencyGraph: FileDependencyGraph,
  targetFile: string,
  options: Partial<GraphVisualizationOptions> = {},
): DiagramResult {
  const subgraph = extractSubgraph(reverseFileDependencyGraph, targetFile, 2);

  return generateDependencyDiagram(subgraph, {
    ...options,
    highlightFiles: [targetFile, ...(options.highlightFiles ?? [])],
    title: options.title ?? `Files that depend on ${path.basename(targetFile)}`,
  });
}

// =============================================================================
// MERMAID DIAGRAM GENERATION
// =============================================================================

function generateMermaidDiagram(
  graph: FileDependencyGraph,
  options: GraphVisualizationOptions,
): DiagramResult {
  const lines: string[] = [];
  const nodes = new Set<string>();
  const excludedFiles: string[] = [];
  let edgeCount = 0;

  // Header
  lines.push('```mermaid');
  lines.push(`graph ${options.direction}`);

  if (options.title) {
    lines.push('');
    lines.push(`  %% ${options.title}`);
  }

  // Filter and limit files
  const filteredEntries = filterGraphEntries(graph, options);

  // Add subgraph groupings if requested
  if (options.groupByDirectory) {
    const grouped = groupByDirectory(filteredEntries);

    for (const [dir, files] of grouped.entries()) {
      if (files.length === 0) continue;

      const dirId = sanitizeMermaidId(dir);
      lines.push('');
      lines.push(`  subgraph ${dirId}["${dir}"]`);

      for (const file of files) {
        const nodeId = sanitizeMermaidId(file);
        const label = path.basename(file);
        const isHighlighted = options.highlightFiles?.includes(file);

        if (nodes.size < (options.maxNodes ?? 50)) {
          nodes.add(nodeId);
          if (isHighlighted) {
            lines.push(`    ${nodeId}["${label}"]:::highlighted`);
          } else {
            lines.push(`    ${nodeId}["${label}"]`);
          }
        } else {
          excludedFiles.push(file);
        }
      }

      lines.push('  end');
    }
  } else {
    // Flat list of nodes
    for (const [file] of filteredEntries) {
      if (nodes.size >= (options.maxNodes ?? 50)) {
        excludedFiles.push(file);
        continue;
      }

      const nodeId = sanitizeMermaidId(file);
      const label = path.basename(file);
      const isHighlighted = options.highlightFiles?.includes(file);

      nodes.add(nodeId);
      if (isHighlighted) {
        lines.push(`  ${nodeId}["${label}"]:::highlighted`);
      } else {
        lines.push(`  ${nodeId}["${label}"]`);
      }
    }
  }

  // Add edges
  lines.push('');
  for (const [file, deps] of filteredEntries) {
    const fromId = sanitizeMermaidId(file);
    if (!nodes.has(fromId)) continue;

    for (const dep of deps) {
      const toId = sanitizeMermaidId(dep);

      // Skip if target node wasn't included
      if (!nodes.has(toId)) continue;

      lines.push(`  ${fromId} --> ${toId}`);
      edgeCount++;
    }
  }

  // Style definitions
  if (options.highlightFiles && options.highlightFiles.length > 0) {
    lines.push('');
    lines.push('  classDef highlighted fill:#f9f,stroke:#333,stroke-width:2px');
  }

  lines.push('```');

  return {
    content: lines.join('\n'),
    nodeCount: nodes.size,
    edgeCount,
    excludedFiles,
  };
}

// =============================================================================
// DOT (GRAPHVIZ) DIAGRAM GENERATION
// =============================================================================

function generateDotDiagram(
  graph: FileDependencyGraph,
  options: GraphVisualizationOptions,
): DiagramResult {
  const lines: string[] = [];
  const nodes = new Set<string>();
  const excludedFiles: string[] = [];
  let edgeCount = 0;

  // Header
  lines.push('digraph dependencies {');
  lines.push('  // Graph settings');
  lines.push(
    `  rankdir=${options.direction === 'LR' ? 'LR' : options.direction === 'RL' ? 'RL' : options.direction === 'BT' ? 'BT' : 'TB'};`,
  );
  lines.push('  node [shape=box, fontname="Arial", fontsize=10];');
  lines.push('  edge [fontname="Arial", fontsize=8];');

  if (options.title) {
    lines.push(`  labelloc="t";`);
    lines.push(`  label="${options.title}";`);
  }

  lines.push('');
  lines.push('  // Nodes');

  const filteredEntries = filterGraphEntries(graph, options);

  for (const [file] of filteredEntries) {
    if (nodes.size >= (options.maxNodes ?? 50)) {
      excludedFiles.push(file);
      continue;
    }

    const nodeId = sanitizeDotId(file);
    const label = path.basename(file);
    const isHighlighted = options.highlightFiles?.includes(file);

    nodes.add(nodeId);
    if (isHighlighted) {
      lines.push(`  ${nodeId} [label="${label}", style="filled", fillcolor="pink"];`);
    } else {
      lines.push(`  ${nodeId} [label="${label}"];`);
    }
  }

  // Add edges
  lines.push('');
  lines.push('  // Edges');
  for (const [file, deps] of filteredEntries) {
    const fromId = sanitizeDotId(file);
    if (!nodes.has(fromId)) continue;

    for (const dep of deps) {
      const toId = sanitizeDotId(dep);
      if (!nodes.has(toId)) continue;

      lines.push(`  ${fromId} -> ${toId};`);
      edgeCount++;
    }
  }

  lines.push('}');

  return {
    content: lines.join('\n'),
    nodeCount: nodes.size,
    edgeCount,
    excludedFiles,
  };
}

// =============================================================================
// ASCII DIAGRAM GENERATION
// =============================================================================

function generateAsciiDiagram(
  graph: FileDependencyGraph,
  options: GraphVisualizationOptions,
): DiagramResult {
  const lines: string[] = [];
  const nodes = new Set<string>();
  const excludedFiles: string[] = [];
  let edgeCount = 0;

  if (options.title) {
    lines.push(`=== ${options.title} ===`);
    lines.push('');
  }

  const filteredEntries = filterGraphEntries(graph, options);

  for (const [file, deps] of filteredEntries) {
    if (nodes.size >= (options.maxNodes ?? 50)) {
      excludedFiles.push(file);
      continue;
    }

    const label = path.basename(file);
    const isHighlighted = options.highlightFiles?.includes(file);
    nodes.add(file);

    const prefix = isHighlighted ? '>>> ' : '    ';
    const depList = Array.from(deps)
      .filter((dep) => (!options.includeExternal ? !dep.includes('node_modules') : true))
      .map((dep) => path.basename(dep));

    if (depList.length === 0) {
      lines.push(`${prefix}${label} (no dependencies)`);
    } else {
      lines.push(`${prefix}${label}`);
      for (let i = 0; i < depList.length; i++) {
        const isLast = i === depList.length - 1;
        const connector = isLast ? '└── ' : '├── ';
        lines.push(`${prefix}    ${connector}${depList[i]}`);
        edgeCount++;
      }
    }
    lines.push('');
  }

  if (excludedFiles.length > 0) {
    lines.push(`... and ${excludedFiles.length} more files (increase maxNodes to see)`);
  }

  return {
    content: lines.join('\n'),
    nodeCount: nodes.size,
    edgeCount,
    excludedFiles,
  };
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Sanitize a file path into a valid Mermaid node ID.
 */
function sanitizeMermaidId(filePath: string): string {
  return filePath
    .replace(/[^a-zA-Z0-9_]/g, '_')
    .replace(/^_+/, '')
    .replace(/_+/g, '_');
}

/**
 * Sanitize a file path into a valid DOT node ID.
 */
function sanitizeDotId(filePath: string): string {
  return '"' + filePath.replace(/"/g, '\\"') + '"';
}

/**
 * Filter graph entries based on options.
 */
function filterGraphEntries(
  graph: FileDependencyGraph,
  options: GraphVisualizationOptions,
): Array<[string, Set<string>]> {
  const entries = Array.from(graph.entries());

  return entries
    .filter(([file, deps]) => {
      // Filter external dependencies
      if (!options.includeExternal) {
        if (file.includes('node_modules') || file.includes('vendor')) {
          return false;
        }
      }

      // Filter by patterns
      if (options.filterPatterns && options.filterPatterns.length > 0) {
        const matchesPattern = options.filterPatterns.some((pattern) => {
          if (pattern.startsWith('*')) {
            return file.endsWith(pattern.slice(1));
          }
          return file.includes(pattern);
        });
        if (!matchesPattern) return false;
      }

      return true;
    })
    .map(([file, deps]) => {
      // Also filter dependencies
      const filteredDeps = new Set(
        Array.from(deps).filter((dep) => {
          if (!options.includeExternal) {
            if (dep.includes('node_modules') || dep.includes('vendor')) {
              return false;
            }
          }
          return true;
        }),
      );
      return [file, filteredDeps] as [string, Set<string>];
    });
}

/**
 * Group files by their parent directory.
 */
function groupByDirectory(entries: Array<[string, Set<string>]>): Map<string, string[]> {
  const groups = new Map<string, string[]>();

  for (const [file, _deps] of entries) {
    const dir = path.dirname(file);
    if (!groups.has(dir)) {
      groups.set(dir, []);
    }
    groups.get(dir)!.push(file);
  }

  return groups;
}

/**
 * Extract a subgraph centered on a specific file.
 */
function extractSubgraph(
  graph: FileDependencyGraph,
  centerFile: string,
  depth: number,
): FileDependencyGraph {
  const subgraph = new Map<string, Set<string>>();
  const visited = new Set<string>();
  const queue: Array<{ file: string; level: number }> = [{ file: centerFile, level: 0 }];

  while (queue.length > 0) {
    const { file, level } = queue.shift()!;

    if (visited.has(file) || level > depth) continue;
    visited.add(file);

    const deps = graph.get(file);
    if (deps) {
      subgraph.set(file, deps);

      if (level < depth) {
        for (const dep of deps) {
          if (!visited.has(dep)) {
            queue.push({ file: dep, level: level + 1 });
          }
        }
      }
    }
  }

  return subgraph;
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a configured diagram generator.
 */
export function createGraphVisualizer(defaultOptions: Partial<GraphVisualizationOptions> = {}) {
  return {
    generate: (graph: FileDependencyGraph, options?: Partial<GraphVisualizationOptions>) =>
      generateDependencyDiagram(graph, { ...defaultOptions, ...options }),

    focused: (
      graph: FileDependencyGraph,
      centerFile: string,
      options?: Partial<GraphVisualizationOptions>,
    ) => generateFocusedDiagram(graph, centerFile, { ...defaultOptions, ...options }),

    reverse: (
      graph: FileDependencyGraph,
      targetFile: string,
      options?: Partial<GraphVisualizationOptions>,
    ) => generateReverseDiagram(graph, targetFile, { ...defaultOptions, ...options }),
  };
}
