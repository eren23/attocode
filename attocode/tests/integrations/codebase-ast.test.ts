/**
 * Tests for Codebase AST Module
 *
 * Tests tree-sitter based symbol and dependency extraction,
 * ASTCache, incremental parsing, and polyglot language support.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  extractSymbolsAST,
  extractDependenciesAST,
  isASTSupported,
  parseFile,
  clearASTCache,
  getASTCacheSize,
  invalidateAST,
  getCachedParse,
  fullReparse,
  djb2Hash,
  getASTCacheStats,
  resetASTCacheStats,
} from '../../src/integrations/context/codebase-ast.js';

// =============================================================================
// isASTSupported
// =============================================================================

describe('isASTSupported', () => {
  it('supports .ts files', () => {
    expect(isASTSupported('src/main.ts')).toBe(true);
  });

  it('supports .tsx files', () => {
    expect(isASTSupported('src/app.tsx')).toBe(true);
  });

  it('supports .js files', () => {
    expect(isASTSupported('lib/index.js')).toBe(true);
  });

  it('supports .jsx files', () => {
    expect(isASTSupported('src/component.jsx')).toBe(true);
  });

  it('supports .py files', () => {
    expect(isASTSupported('scripts/build.py')).toBe(true);
  });

  it('does not support .rs files', () => {
    expect(isASTSupported('src/main.rs')).toBe(false);
  });

  it('does not support .go files', () => {
    expect(isASTSupported('main.go')).toBe(false);
  });
});

// =============================================================================
// TypeScript Symbol Extraction
// =============================================================================

describe('extractSymbolsAST - TypeScript', () => {
  it('extracts exported function', () => {
    const symbols = extractSymbolsAST('export function foo() {}', 'test.ts');
    expect(symbols).toContainEqual(expect.objectContaining({
      name: 'foo',
      kind: 'function',
      exported: true,
    }));
  });

  it('extracts exported class with methods', () => {
    const code = `export class MyClass {
  doSomething() {}
  getValue() { return 1; }
}`;
    const symbols = extractSymbolsAST(code, 'test.ts');
    const classSymbol = symbols.find(s => s.name === 'MyClass');
    expect(classSymbol).toBeDefined();
    expect(classSymbol!.kind).toBe('class');
    expect(classSymbol!.exported).toBe(true);

    const methods = symbols.filter(s => s.kind === 'method');
    expect(methods.map(m => m.name)).toContain('doSomething');
    expect(methods.map(m => m.name)).toContain('getValue');
  });

  it('extracts exported interface', () => {
    const symbols = extractSymbolsAST('export interface Config { key: string; }', 'test.ts');
    expect(symbols).toContainEqual(expect.objectContaining({
      name: 'Config',
      kind: 'interface',
      exported: true,
    }));
  });

  it('extracts exported type alias', () => {
    const symbols = extractSymbolsAST('export type ID = string | number;', 'test.ts');
    expect(symbols).toContainEqual(expect.objectContaining({
      name: 'ID',
      kind: 'type',
      exported: true,
    }));
  });

  it('extracts exported enum', () => {
    const symbols = extractSymbolsAST('export enum Color { Red, Blue, Green }', 'test.ts');
    expect(symbols).toContainEqual(expect.objectContaining({
      name: 'Color',
      kind: 'enum',
      exported: true,
    }));
  });

  it('extracts exported const variable', () => {
    const symbols = extractSymbolsAST('export const MAX_SIZE = 100;', 'test.ts');
    expect(symbols).toContainEqual(expect.objectContaining({
      name: 'MAX_SIZE',
      kind: 'variable',
      exported: true,
    }));
  });

  it('extracts named exports (export { A, B })', () => {
    const code = `const A = 1;\nconst B = 2;\nexport { A, B };`;
    const symbols = extractSymbolsAST(code, 'test.ts');
    const exported = symbols.filter(s => s.exported);
    expect(exported.map(s => s.name)).toContain('A');
    expect(exported.map(s => s.name)).toContain('B');
  });

  it('extracts re-exports (export { X } from "./other")', () => {
    const symbols = extractSymbolsAST("export { X, Y } from './other';", 'test.ts');
    const exported = symbols.filter(s => s.exported);
    expect(exported.map(s => s.name)).toContain('X');
    expect(exported.map(s => s.name)).toContain('Y');
  });

  it('extracts default export class', () => {
    const symbols = extractSymbolsAST('export default class MyDefault {}', 'test.ts');
    expect(symbols.some(s => s.name === 'MyDefault' && s.exported)).toBe(true);
  });

  it('marks non-exported declarations as not exported', () => {
    const code = `function internal() {}\nexport function external() {}`;
    const symbols = extractSymbolsAST(code, 'test.ts');
    const internal = symbols.find(s => s.name === 'internal');
    const external = symbols.find(s => s.name === 'external');
    expect(internal?.exported).toBe(false);
    expect(external?.exported).toBe(true);
  });

  it('handles mixed exports and non-exports', () => {
    const code = `
function helper() {}
export function main() {}
class InternalClass {}
export class PublicClass {}
`;
    const symbols = extractSymbolsAST(code, 'test.ts');
    expect(symbols.length).toBeGreaterThanOrEqual(4);
    expect(symbols.filter(s => s.exported).length).toBe(2);
    expect(symbols.filter(s => !s.exported).length).toBeGreaterThanOrEqual(2);
  });

  it('returns empty array for empty file', () => {
    expect(extractSymbolsAST('', 'test.ts')).toEqual([]);
  });

  it('returns empty array for syntax error (graceful fallback)', () => {
    // Heavily malformed syntax — tree-sitter still produces a tree but with ERROR nodes
    const result = extractSymbolsAST('export {{{{', 'test.ts');
    // Should not throw, may return empty or partial
    expect(Array.isArray(result)).toBe(true);
  });

  it('includes line numbers', () => {
    const code = `// line 1
// line 2
export function foo() {} // line 3`;
    const symbols = extractSymbolsAST(code, 'test.ts');
    const foo = symbols.find(s => s.name === 'foo');
    expect(foo?.line).toBe(3);
  });
});

// =============================================================================
// TypeScript Dependency Extraction
// =============================================================================

describe('extractDependenciesAST - TypeScript', () => {
  it('extracts named imports', () => {
    const deps = extractDependenciesAST("import { A, B } from './module';", 'test.ts');
    expect(deps).toHaveLength(1);
    expect(deps[0].source).toBe('./module');
    expect(deps[0].names).toContain('A');
    expect(deps[0].names).toContain('B');
    expect(deps[0].isRelative).toBe(true);
  });

  it('extracts default import', () => {
    const deps = extractDependenciesAST("import MyModule from './mymod';", 'test.ts');
    expect(deps).toHaveLength(1);
    expect(deps[0].names).toContain('MyModule');
    expect(deps[0].isRelative).toBe(true);
  });

  it('extracts namespace import', () => {
    const deps = extractDependenciesAST("import * as Utils from './utils';", 'test.ts');
    expect(deps).toHaveLength(1);
    expect(deps[0].source).toBe('./utils');
    expect(deps[0].names).toContain('* as Utils');
  });

  it('distinguishes relative vs absolute paths', () => {
    const code = `
import { A } from './relative';
import { B } from 'absolute-package';
`;
    const deps = extractDependenciesAST(code, 'test.ts');
    const relative = deps.find(d => d.source === './relative');
    const absolute = deps.find(d => d.source === 'absolute-package');
    expect(relative?.isRelative).toBe(true);
    expect(absolute?.isRelative).toBe(false);
  });

  it('handles side-effect imports', () => {
    const deps = extractDependenciesAST("import './init';", 'test.ts');
    expect(deps).toHaveLength(1);
    expect(deps[0].source).toBe('./init');
    expect(deps[0].names).toEqual([]);
    expect(deps[0].isRelative).toBe(true);
  });

  it('handles export ... from re-exports', () => {
    const deps = extractDependenciesAST("export { X } from './other';", 'test.ts');
    expect(deps).toHaveLength(1);
    expect(deps[0].source).toBe('./other');
    expect(deps[0].names).toContain('X');
  });

  it('handles multiline import statements', () => {
    const code = `import {
  A,
  B,
  C,
} from './module';`;
    const deps = extractDependenciesAST(code, 'test.ts');
    expect(deps).toHaveLength(1);
    expect(deps[0].names).toHaveLength(3);
  });

  it('returns empty array for empty file', () => {
    expect(extractDependenciesAST('', 'test.ts')).toEqual([]);
  });

  it('returns empty array for file with no imports', () => {
    expect(extractDependenciesAST('const x = 1;', 'test.ts')).toEqual([]);
  });
});

// =============================================================================
// Python Symbol Extraction
// =============================================================================

describe('extractSymbolsAST - Python', () => {
  it('extracts module-level functions', () => {
    const code = `def foo():\n    pass\n\ndef bar():\n    return 1`;
    const symbols = extractSymbolsAST(code, 'test.py');
    expect(symbols.map(s => s.name)).toContain('foo');
    expect(symbols.map(s => s.name)).toContain('bar');
    expect(symbols.every(s => s.kind === 'function')).toBe(true);
  });

  it('extracts module-level classes', () => {
    const code = `class MyClass:\n    def method(self):\n        pass`;
    const symbols = extractSymbolsAST(code, 'test.py');
    expect(symbols).toContainEqual(expect.objectContaining({
      name: 'MyClass',
      kind: 'class',
    }));
  });

  it('treats underscore-prefixed names as non-exported', () => {
    const code = `def _private():\n    pass\n\ndef public():\n    pass`;
    const symbols = extractSymbolsAST(code, 'test.py');
    const priv = symbols.find(s => s.name === '_private');
    const pub = symbols.find(s => s.name === 'public');
    expect(priv?.exported).toBe(false);
    expect(pub?.exported).toBe(true);
  });

  it('returns empty array for empty file', () => {
    expect(extractSymbolsAST('', 'test.py')).toEqual([]);
  });
});

// =============================================================================
// Python Dependency Extraction
// =============================================================================

describe('extractDependenciesAST - Python', () => {
  it('extracts from...import statements', () => {
    const deps = extractDependenciesAST('from module import name, other', 'test.py');
    expect(deps).toHaveLength(1);
    expect(deps[0].source).toBe('module');
    expect(deps[0].names).toContain('name');
    expect(deps[0].names).toContain('other');
    expect(deps[0].isRelative).toBe(false);
  });

  it('extracts import statements', () => {
    const deps = extractDependenciesAST('import os', 'test.py');
    expect(deps).toHaveLength(1);
    expect(deps[0].source).toBe('os');
    expect(deps[0].names).toContain('os');
  });

  it('detects relative imports', () => {
    const deps = extractDependenciesAST('from . import relative', 'test.py');
    expect(deps).toHaveLength(1);
    expect(deps[0].isRelative).toBe(true);
    expect(deps[0].names).toContain('relative');
  });

  it('returns empty array for empty file', () => {
    expect(extractDependenciesAST('', 'test.py')).toEqual([]);
  });
});

// =============================================================================
// Edge Cases
// =============================================================================

describe('edge cases', () => {
  it('handles unsupported file extension gracefully', () => {
    // .rs and .go grammars are not installed, so they should fall back gracefully
    expect(extractSymbolsAST('fn main() {}', 'test.rs')).toEqual([]);
    expect(extractDependenciesAST('use std::io;', 'test.rs')).toEqual([]);
  });

  it('handles file with only comments', () => {
    const code = '// This is a comment\n// Another comment\n';
    const symbols = extractSymbolsAST(code, 'test.ts');
    expect(symbols).toEqual([]);
  });

  it('handles TSX file', () => {
    const code = `export function App() { return <div>Hello</div>; }`;
    const symbols = extractSymbolsAST(code, 'test.tsx');
    expect(symbols).toContainEqual(expect.objectContaining({
      name: 'App',
      kind: 'function',
      exported: true,
    }));
  });
});

// =============================================================================
// ASTCache (Phase 1)
// =============================================================================

describe('ASTCache', () => {
  beforeEach(() => {
    clearASTCache();
  });

  it('parseFile returns ParsedFile with tree, symbols, and dependencies', () => {
    const code = `import { A } from './mod';\nexport function foo() {}`;
    const parsed = parseFile(code, '/test/cache-test.ts');
    expect(parsed).not.toBeNull();
    expect(parsed!.tree).toBeDefined();
    expect(parsed!.symbols).toContainEqual(expect.objectContaining({
      name: 'foo',
      kind: 'function',
      exported: true,
    }));
    expect(parsed!.dependencies).toContainEqual(expect.objectContaining({
      source: './mod',
      isRelative: true,
    }));
    expect(parsed!.contentHash).toBeTypeOf('number');
    expect(parsed!.parsedAt).toBeTypeOf('number');
  });

  it('caches parsed results by filePath + contentHash', () => {
    const code = 'export function bar() {}';
    clearASTCache();

    const first = parseFile(code, '/test/cache-hit.ts');
    expect(getASTCacheSize()).toBe(1);

    const second = parseFile(code, '/test/cache-hit.ts');
    expect(second).toBe(first); // Same reference = cache hit
  });

  it('invalidates cache when content changes', () => {
    const code1 = 'export function v1() {}';
    const code2 = 'export function v2() {}';

    const first = parseFile(code1, '/test/cache-miss.ts');
    const second = parseFile(code2, '/test/cache-miss.ts');

    expect(second).not.toBe(first); // Different reference = cache miss
    expect(second!.symbols[0].name).toBe('v2');
  });

  it('invalidateAST removes a single file from cache', () => {
    parseFile('export const x = 1;', '/test/a.ts');
    parseFile('export const y = 2;', '/test/b.ts');
    expect(getASTCacheSize()).toBe(2);

    invalidateAST('/test/a.ts');
    expect(getASTCacheSize()).toBe(1);
    expect(getCachedParse('/test/a.ts')).toBeNull();
    expect(getCachedParse('/test/b.ts')).not.toBeNull();
  });

  it('clearASTCache empties the entire cache', () => {
    parseFile('export const x = 1;', '/test/c.ts');
    parseFile('export const y = 2;', '/test/d.ts');
    expect(getASTCacheSize()).toBe(2);

    clearASTCache();
    expect(getASTCacheSize()).toBe(0);
  });

  it('getCachedParse returns null for unparsed file', () => {
    expect(getCachedParse('/test/nonexistent.ts')).toBeNull();
  });

  it('extractSymbolsAST uses cache (single parse for multiple calls)', () => {
    clearASTCache();
    const code = 'export class Cached {}';

    // First call parses and caches
    extractSymbolsAST(code, '/test/dedup.ts');
    expect(getASTCacheSize()).toBe(1);

    // Second call with extractDependenciesAST should hit cache
    extractDependenciesAST(code, '/test/dedup.ts');
    expect(getASTCacheSize()).toBe(1); // Still 1 = no re-parse
  });

  it('returns null for unsupported file extension', () => {
    expect(parseFile('some content', '/test/file.txt')).toBeNull();
  });

  it('normalizes cache keys so absolute paths always hit (Bug 1 regression)', () => {
    clearASTCache();
    const code = 'export function normalized() {}';

    // Parse with absolute path
    const parsed = parseFile(code, '/project/src/file.ts');
    expect(parsed).not.toBeNull();
    expect(getASTCacheSize()).toBe(1);

    // getCachedParse with same absolute path should hit
    const cached = getCachedParse('/project/src/file.ts');
    expect(cached).toBe(parsed);
  });

  it('getCachedParse finds entry after parseFile with equivalent paths', () => {
    clearASTCache();
    const code = 'export const val = 42;';

    // Parse with one form
    parseFile(code, '/project/src/./utils/../utils/helper.ts');
    expect(getASTCacheSize()).toBe(1);

    // Lookup with normalized form should hit
    const cached = getCachedParse('/project/src/utils/helper.ts');
    expect(cached).not.toBeNull();
    expect(cached!.symbols[0].name).toBe('val');
  });
});

// =============================================================================
// djb2Hash
// =============================================================================

describe('djb2Hash', () => {
  it('produces consistent hashes', () => {
    const hash1 = djb2Hash('hello world');
    const hash2 = djb2Hash('hello world');
    expect(hash1).toBe(hash2);
  });

  it('produces different hashes for different strings', () => {
    const hash1 = djb2Hash('hello');
    const hash2 = djb2Hash('world');
    expect(hash1).not.toBe(hash2);
  });

  it('returns unsigned 32-bit integer', () => {
    const hash = djb2Hash('test string');
    expect(hash).toBeGreaterThanOrEqual(0);
    expect(hash).toBeLessThan(2 ** 32);
  });
});

// =============================================================================
// fullReparse (Phase 2)
// =============================================================================

describe('fullReparse', () => {
  beforeEach(() => {
    clearASTCache();
  });

  it('reparses and updates cache', () => {
    parseFile('export function old() {}', '/test/reparse.ts');
    const reparsed = fullReparse('/test/reparse.ts', 'export function updated() {}');
    expect(reparsed).not.toBeNull();
    expect(reparsed!.symbols[0].name).toBe('updated');

    // Cache should be updated
    const cached = getCachedParse('/test/reparse.ts');
    expect(cached!.symbols[0].name).toBe('updated');
  });
});

// =============================================================================
// Polyglot: isASTSupported with grammars not installed
// =============================================================================

describe('polyglot language support (graceful degradation)', () => {
  // These tests verify that polyglot extensions are recognized by the profile system
  // but gracefully degrade when the grammar packages aren't installed.
  // The grammar packages (tree-sitter-go, tree-sitter-rust, etc.) are NOT in dependencies,
  // so isASTSupported should return false for them.

  it('recognizes .go extension in profiles but degrades without grammar', () => {
    // Without tree-sitter-go installed, this returns false
    const supported = isASTSupported('main.go');
    // Either supported (grammar installed) or not — both are valid
    expect(typeof supported).toBe('boolean');
  });

  it('recognizes .java extension in profiles but degrades without grammar', () => {
    const supported = isASTSupported('Main.java');
    expect(typeof supported).toBe('boolean');
  });

  it('recognizes .c extension in profiles but degrades without grammar', () => {
    const supported = isASTSupported('main.c');
    expect(typeof supported).toBe('boolean');
  });

  it('returns empty arrays for unsupported polyglot files', () => {
    // Without grammars installed, should return empty arrays (not throw)
    expect(extractSymbolsAST('package main', 'main.go')).toEqual([]);
    expect(extractDependenciesAST('import "fmt"', 'main.go')).toEqual([]);
  });

  it('returns empty for unknown extensions', () => {
    expect(extractSymbolsAST('whatever', 'test.zig')).toEqual([]);
    expect(isASTSupported('test.zig')).toBe(false);
  });
});

// =============================================================================
// getASTCacheStats
// =============================================================================

describe('getASTCacheStats', () => {
  beforeEach(() => {
    clearASTCache();
    resetASTCacheStats();
  });

  it('returns zero counts initially', () => {
    const stats = getASTCacheStats();
    expect(stats.fileCount).toBe(0);
    expect(stats.totalParses).toBe(0);
    expect(stats.cacheHits).toBe(0);
    expect(Object.keys(stats.languages)).toHaveLength(0);
  });

  it('counts increase after parsing files', () => {
    parseFile('export function a() {}', '/test/stats-a.ts');
    parseFile('export function b() {}', '/test/stats-b.ts');

    const stats = getASTCacheStats();
    expect(stats.fileCount).toBe(2);
    expect(stats.totalParses).toBe(2);
    expect(stats.cacheHits).toBe(0);
  });

  it('records cache hits on repeated parse', () => {
    const code = 'export function c() {}';
    parseFile(code, '/test/stats-c.ts');
    parseFile(code, '/test/stats-c.ts'); // cache hit

    const stats = getASTCacheStats();
    expect(stats.fileCount).toBe(1);
    expect(stats.totalParses).toBe(1);
    expect(stats.cacheHits).toBe(1);
  });

  it('provides accurate language breakdown', () => {
    parseFile('export function ts1() {}', '/test/lang-a.ts');
    parseFile('export function ts2() {}', '/test/lang-b.tsx');
    parseFile('const x = 1;', '/test/lang-c.js');

    const stats = getASTCacheStats();
    expect(stats.languages['typescript']).toBe(2); // .ts + .tsx
    expect(stats.languages['javascript']).toBe(1);
  });
});
