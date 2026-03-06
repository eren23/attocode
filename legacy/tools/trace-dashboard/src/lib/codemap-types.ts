/**
 * Code map visualization types.
 * Represents the repository's file structure, dependencies, and symbols.
 */

export interface CodeMapData {
  root: string;
  totalFiles: number;
  totalTokens: number;
  files: CodeMapFile[];
  dependencyEdges: { source: string; target: string; importedNames: string[] }[];
  entryPoints: string[];
  coreModules: string[];
  selectionMeta?: {
    selected: number;
    original: number;
    excludedDirs: string[];
    limit: number;
  };
}

export interface CodeMapFile {
  filePath: string;
  directory: string;
  fileName: string;
  tokenCount: number;
  importance: number;
  type: 'entry_point' | 'core_module' | 'types' | 'test' | 'utility' | 'config' | 'other';
  symbols: { name: string; kind: string; exported: boolean; line: number }[];
  inDegree: number;
  outDegree: number;
}

/** Raw codemap.json snapshot from swarm-live/ */
export interface CodeMapSnapshot {
  totalFiles: number;
  totalTokens: number;
  entryPoints: string[];
  coreModules: string[];
  dependencyEdges: { file: string; imports: string[] }[];
  files?: CodeMapFile[];
  topChunks: {
    filePath: string;
    tokenCount: number;
    importance: number;
    type: string;
    symbols?: { name: string; kind: string; exported: boolean; line: number }[];
  }[];
}
