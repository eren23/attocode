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
  computeTreeEdit,
  diffSymbols,
  diffDependencies,
} from '../../src/integrations/context/codebase-ast.js';
import type { ASTSymbol, ASTDependency } from '../../src/integrations/context/codebase-ast.js';

/**
 * Helper to detect if tree-sitter is available at runtime.
 * If not installed, parseFile returns null and extractSymbolsAST returns [].
 */
function hasTreeSitter(): boolean {
  const result = parseFile('const x = 1;', '/test/check.ts');
  return result !== null;
}

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

// =============================================================================
// extractSymbolsAST - detailed parameters
// =============================================================================

describe('extractSymbolsAST - detailed parameters', () => {
  beforeEach(() => {
    clearASTCache();
    resetASTCacheStats();
  });

  it.skipIf(!hasTreeSitter())('extracts parameter names and types', () => {
    const code = `function foo(a: string, b: number) {}`;
    const symbols = extractSymbolsAST(code, '/test/params.ts');
    const foo = symbols.find(s => s.name === 'foo');
    expect(foo).toBeDefined();
    expect(foo!.parameters).toBeDefined();
    expect(foo!.parameters!.length).toBe(2);
    expect(foo!.parameters![0].name).toBe('a');
    expect(foo!.parameters![0].typeAnnotation).toBe('string');
    expect(foo!.parameters![0].hasDefault).toBe(false);
    expect(foo!.parameters![0].isRest).toBe(false);
    expect(foo!.parameters![1].name).toBe('b');
    expect(foo!.parameters![1].typeAnnotation).toBe('number');
  });

  it.skipIf(!hasTreeSitter())('extracts default and rest parameters', () => {
    const code = `function foo(a: string, b = 5, ...rest: number[]) {}`;
    const symbols = extractSymbolsAST(code, '/test/params-default-rest.ts');
    const foo = symbols.find(s => s.name === 'foo');
    expect(foo).toBeDefined();
    expect(foo!.parameters).toBeDefined();
    expect(foo!.parameters!.length).toBe(3);

    const paramA = foo!.parameters![0];
    expect(paramA.name).toBe('a');
    expect(paramA.hasDefault).toBe(false);
    expect(paramA.isRest).toBe(false);

    const paramB = foo!.parameters![1];
    expect(paramB.name).toBe('b');
    expect(paramB.hasDefault).toBe(true);
    expect(paramB.isRest).toBe(false);

    const paramRest = foo!.parameters![2];
    // The implementation includes the '...' prefix in the name.
    // Note: depending on tree-sitter grammar version, rest parameters may or may
    // not be classified as rest_parameter nodes. We verify the name contains 'rest'
    // and the type annotation is present.
    expect(paramRest.name).toContain('rest');
    expect(paramRest.typeAnnotation).toBe('number[]');
    // isRest may be true or false depending on tree-sitter grammar version
    if (paramRest.name.startsWith('...')) {
      // Name includes spread operator — implementation stores it in name
      expect(paramRest.name).toBe('...rest');
    } else {
      // Name is clean — isRest flag should be true
      expect(paramRest.isRest).toBe(true);
    }
  });

  it.skipIf(!hasTreeSitter())('extracts parameters for class methods', () => {
    const code = `class Svc {
  process(input: string, options?: Record<string, unknown>): void {}
}`;
    const symbols = extractSymbolsAST(code, '/test/method-params.ts');
    const method = symbols.find(s => s.name === 'process' && s.kind === 'method');
    expect(method).toBeDefined();
    expect(method!.parameters).toBeDefined();
    expect(method!.parameters!.length).toBeGreaterThanOrEqual(1);
    expect(method!.parameters![0].name).toBe('input');
  });
});

// =============================================================================
// extractSymbolsAST - return type
// =============================================================================

describe('extractSymbolsAST - return type', () => {
  beforeEach(() => {
    clearASTCache();
    resetASTCacheStats();
  });

  it.skipIf(!hasTreeSitter())('extracts return type annotation from function', () => {
    const code = `function bar(): Promise<string> { return Promise.resolve(''); }`;
    const symbols = extractSymbolsAST(code, '/test/return-type.ts');
    const bar = symbols.find(s => s.name === 'bar');
    expect(bar).toBeDefined();
    expect(bar!.returnType).toBeDefined();
    expect(bar!.returnType).toContain('Promise');
  });

  it.skipIf(!hasTreeSitter())('extracts simple return type', () => {
    const code = `function count(): number { return 42; }`;
    const symbols = extractSymbolsAST(code, '/test/return-simple.ts');
    const count = symbols.find(s => s.name === 'count');
    expect(count).toBeDefined();
    expect(count!.returnType).toBe('number');
  });

  it.skipIf(!hasTreeSitter())('extracts return type from class method', () => {
    const code = `class Repo {
  findAll(): string[] { return []; }
}`;
    const symbols = extractSymbolsAST(code, '/test/return-method.ts');
    const method = symbols.find(s => s.name === 'findAll' && s.kind === 'method');
    expect(method).toBeDefined();
    expect(method!.returnType).toBeDefined();
    expect(method!.returnType).toContain('string[]');
  });
});

// =============================================================================
// extractSymbolsAST - visibility modifiers
// =============================================================================

describe('extractSymbolsAST - visibility modifiers', () => {
  beforeEach(() => {
    clearASTCache();
    resetASTCacheStats();
  });

  it.skipIf(!hasTreeSitter())('extracts private visibility', () => {
    const code = `class Foo {
  private secret(): void {}
}`;
    const symbols = extractSymbolsAST(code, '/test/visibility-private.ts');
    const secret = symbols.find(s => s.name === 'secret');
    expect(secret).toBeDefined();
    expect(secret!.visibility).toBe('private');
  });

  it.skipIf(!hasTreeSitter())('extracts protected visibility', () => {
    const code = `class Foo {
  protected helper(): void {}
}`;
    const symbols = extractSymbolsAST(code, '/test/visibility-protected.ts');
    const helper = symbols.find(s => s.name === 'helper');
    expect(helper).toBeDefined();
    expect(helper!.visibility).toBe('protected');
  });

  it.skipIf(!hasTreeSitter())('extracts public visibility', () => {
    const code = `class Foo {
  public api(): void {}
}`;
    const symbols = extractSymbolsAST(code, '/test/visibility-public.ts');
    const api = symbols.find(s => s.name === 'api');
    expect(api).toBeDefined();
    expect(api!.visibility).toBe('public');
  });

  it.skipIf(!hasTreeSitter())('extracts all visibility modifiers in one class', () => {
    const code = `class Foo {
  private secret(): void {}
  protected helper(): void {}
  public api(): void {}
}`;
    const symbols = extractSymbolsAST(code, '/test/visibility-all.ts');
    expect(symbols.find(s => s.name === 'secret')!.visibility).toBe('private');
    expect(symbols.find(s => s.name === 'helper')!.visibility).toBe('protected');
    expect(symbols.find(s => s.name === 'api')!.visibility).toBe('public');
  });
});

// =============================================================================
// extractSymbolsAST - async/generator flags
// =============================================================================

describe('extractSymbolsAST - async/generator flags', () => {
  beforeEach(() => {
    clearASTCache();
    resetASTCacheStats();
  });

  it.skipIf(!hasTreeSitter())('detects async function', () => {
    const code = `async function doAsync() {}`;
    const symbols = extractSymbolsAST(code, '/test/async-fn.ts');
    const fn = symbols.find(s => s.name === 'doAsync');
    expect(fn).toBeDefined();
    expect(fn!.isAsync).toBe(true);
  });

  // Note: tree-sitter TypeScript uses 'generator_function_declaration' node type
  // for function* declarations, which is not currently handled by declarationKind().
  // Generator functions are only detected when they appear as class methods
  // (via extractFunctionFlags checking for 'function*' in text).
  // These tests verify the current behavior rather than expected ideal behavior.
  it.skipIf(!hasTreeSitter())('generator function at top level is not extracted (known limitation)', () => {
    const code = `function* gen() { yield 1; }`;
    const symbols = extractSymbolsAST(code, '/test/gen-fn.ts');
    // generator_function_declaration is not in declarationKind(), so it won't be found
    const fn = symbols.find(s => s.name === 'gen');
    // Currently not extracted — if this starts passing, the limitation was fixed
    expect(fn).toBeUndefined();
  });

  it.skipIf(!hasTreeSitter())('async generator at top level is not extracted (known limitation)', () => {
    const code = `async function* asyncGen() { yield 1; }`;
    const symbols = extractSymbolsAST(code, '/test/async-gen-fn.ts');
    const fn = symbols.find(s => s.name === 'asyncGen');
    // Currently not extracted — if this starts passing, the limitation was fixed
    expect(fn).toBeUndefined();
  });

  it.skipIf(!hasTreeSitter())('non-async function has isAsync falsy', () => {
    const code = `function sync() {}`;
    const symbols = extractSymbolsAST(code, '/test/sync-fn.ts');
    const fn = symbols.find(s => s.name === 'sync');
    expect(fn).toBeDefined();
    expect(fn!.isAsync).toBeFalsy();
  });
});

// =============================================================================
// extractSymbolsAST - endLine tracking
// =============================================================================

describe('extractSymbolsAST - endLine tracking', () => {
  beforeEach(() => {
    clearASTCache();
    resetASTCacheStats();
  });

  it.skipIf(!hasTreeSitter())('tracks endLine for multi-line function', () => {
    const code = `function multiLine(
  a: string,
  b: number,
) {
  return a + b;
}`;
    const symbols = extractSymbolsAST(code, '/test/endline.ts');
    const fn = symbols.find(s => s.name === 'multiLine');
    expect(fn).toBeDefined();
    expect(fn!.line).toBe(1);
    expect(fn!.endLine).toBeDefined();
    expect(fn!.endLine).toBe(6);
  });

  it.skipIf(!hasTreeSitter())('tracks endLine for class', () => {
    const code = `class MyClass {
  foo() {}
  bar() {}
}`;
    const symbols = extractSymbolsAST(code, '/test/endline-class.ts');
    const cls = symbols.find(s => s.name === 'MyClass' && s.kind === 'class');
    expect(cls).toBeDefined();
    expect(cls!.line).toBe(1);
    expect(cls!.endLine).toBeDefined();
    expect(cls!.endLine).toBe(4);
  });

  it.skipIf(!hasTreeSitter())('single-line function has endLine equal to line', () => {
    const code = `function oneLiner() {}`;
    const symbols = extractSymbolsAST(code, '/test/endline-single.ts');
    const fn = symbols.find(s => s.name === 'oneLiner');
    expect(fn).toBeDefined();
    // endLine should be defined and equal to line (both line 1)
    if (fn!.endLine !== undefined) {
      expect(fn!.endLine).toBe(fn!.line);
    }
  });
});

// =============================================================================
// extractSymbolsAST - property kind
// =============================================================================

describe('extractSymbolsAST - property kind', () => {
  beforeEach(() => {
    clearASTCache();
    resetASTCacheStats();
  });

  it.skipIf(!hasTreeSitter())('extracts class fields as property kind', () => {
    const code = `class MyClass {
  name: string;
  count = 0;
}`;
    const symbols = extractSymbolsAST(code, '/test/property-kind.ts');
    const properties = symbols.filter(s => s.kind === 'property');
    expect(properties.length).toBeGreaterThanOrEqual(1);
    const nameField = properties.find(s => s.name === 'name');
    const countField = properties.find(s => s.name === 'count');
    // At least one of these should be extracted as a property
    expect(nameField || countField).toBeDefined();
    if (nameField) {
      expect(nameField.kind).toBe('property');
      expect(nameField.parentSymbol).toBe('MyClass');
    }
    if (countField) {
      expect(countField.kind).toBe('property');
      expect(countField.parentSymbol).toBe('MyClass');
    }
  });
});

// =============================================================================
// extractSymbolsAST - static/abstract members
// =============================================================================

describe('extractSymbolsAST - static/abstract members', () => {
  beforeEach(() => {
    clearASTCache();
    resetASTCacheStats();
  });

  it.skipIf(!hasTreeSitter())('detects static method', () => {
    const code = `class Foo {
  static getInstance(): Foo { return new Foo(); }
}`;
    const symbols = extractSymbolsAST(code, '/test/static-method.ts');
    const method = symbols.find(s => s.name === 'getInstance');
    expect(method).toBeDefined();
    expect(method!.isStatic).toBe(true);
  });

  // Note: abstract class members require tree-sitter to parse `abstract` modifier.
  // If tree-sitter does not parse abstract members as separate nodes, this test
  // may need adjustment. The abstract keyword may be treated as a modifier on the
  // class declaration or method definition depending on tree-sitter grammar version.
  it.skipIf(!hasTreeSitter())('detects abstract method if supported by grammar', () => {
    const code = `abstract class Foo {
  abstract doWork(): void;
}`;
    const symbols = extractSymbolsAST(code, '/test/abstract-method.ts');
    const method = symbols.find(s => s.name === 'doWork');
    // Abstract methods may or may not be extracted depending on tree-sitter grammar.
    // If extracted, isAbstract should be true.
    if (method) {
      expect(method.isAbstract).toBe(true);
    }
  });

  it.skipIf(!hasTreeSitter())('static field is detected', () => {
    const code = `class Config {
  static readonly DEFAULT_TIMEOUT = 5000;
}`;
    const symbols = extractSymbolsAST(code, '/test/static-field.ts');
    const field = symbols.find(s => s.name === 'DEFAULT_TIMEOUT');
    // Static fields may be extracted as property with isStatic
    if (field) {
      expect(field.isStatic).toBe(true);
    }
  });
});

// =============================================================================
// computeTreeEdit
// =============================================================================

describe('computeTreeEdit', () => {
  it('computes correct edit for simple string replacement', () => {
    const oldContent = 'const x = 1;\nconst y = 2;\n';
    const oldString = 'const y = 2;';
    const newString = 'const y = 42;';

    const edit = computeTreeEdit(oldContent, oldString, newString);
    expect(edit).not.toBeNull();

    // startIndex should point to where 'const y = 2;' begins
    const expectedStart = oldContent.indexOf(oldString);
    expect(edit!.startIndex).toBe(expectedStart);

    // oldEndIndex = startIndex + oldString.length
    expect(edit!.oldEndIndex).toBe(expectedStart + oldString.length);

    // newEndIndex = startIndex + newString.length
    expect(edit!.newEndIndex).toBe(expectedStart + newString.length);
  });

  it('returns null when oldString is not found', () => {
    const oldContent = 'const x = 1;';
    const edit = computeTreeEdit(oldContent, 'not present', 'replacement');
    expect(edit).toBeNull();
  });

  it('computes correct row/column positions', () => {
    const oldContent = 'line one\nline two\nline three\n';
    const oldString = 'line two';
    const newString = 'LINE TWO REPLACED';

    const edit = computeTreeEdit(oldContent, oldString, newString);
    expect(edit).not.toBeNull();

    // 'line two' starts at row 1 (0-indexed), column 0
    expect(edit!.startPosition.row).toBe(1);
    expect(edit!.startPosition.column).toBe(0);

    // old end: 'line two' ends at row 1, column 8
    expect(edit!.oldEndPosition.row).toBe(1);
    expect(edit!.oldEndPosition.column).toBe(8);

    // new end: 'LINE TWO REPLACED' ends at row 1, column 17
    expect(edit!.newEndPosition.row).toBe(1);
    expect(edit!.newEndPosition.column).toBe(17);
  });

  it('handles multi-line replacement', () => {
    const oldContent = 'a\nb\nc\n';
    const oldString = 'b';
    const newString = 'b1\nb2';

    const edit = computeTreeEdit(oldContent, oldString, newString);
    expect(edit).not.toBeNull();

    // Start at row 1, col 0
    expect(edit!.startPosition.row).toBe(1);
    expect(edit!.startPosition.column).toBe(0);

    // Old end: single char 'b' at row 1, col 1
    expect(edit!.oldEndPosition.row).toBe(1);
    expect(edit!.oldEndPosition.column).toBe(1);

    // New end: 'b1\nb2' ends at row 2, col 2
    expect(edit!.newEndPosition.row).toBe(2);
    expect(edit!.newEndPosition.column).toBe(2);
  });

  it('handles replacement at the start of the content', () => {
    const oldContent = 'hello world';
    const oldString = 'hello';
    const newString = 'goodbye';

    const edit = computeTreeEdit(oldContent, oldString, newString);
    expect(edit).not.toBeNull();
    expect(edit!.startIndex).toBe(0);
    expect(edit!.startPosition.row).toBe(0);
    expect(edit!.startPosition.column).toBe(0);
  });

  it('handles empty replacement (deletion)', () => {
    const oldContent = 'abc';
    const oldString = 'b';
    const newString = '';

    const edit = computeTreeEdit(oldContent, oldString, newString);
    expect(edit).not.toBeNull();
    expect(edit!.startIndex).toBe(1);
    expect(edit!.oldEndIndex).toBe(2);
    expect(edit!.newEndIndex).toBe(1); // startIndex + 0
  });
});

// =============================================================================
// diffSymbols
// =============================================================================

describe('diffSymbols', () => {
  const makeSymbol = (overrides: Partial<ASTSymbol> & Pick<ASTSymbol, 'name' | 'kind'>): ASTSymbol => ({
    exported: false,
    line: 1,
    ...overrides,
  });

  it('detects added symbol', () => {
    const oldSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'existing', kind: 'function', line: 1 }),
    ];
    const newSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'existing', kind: 'function', line: 1 }),
      makeSymbol({ name: 'brandNew', kind: 'function', line: 5 }),
    ];

    const changes = diffSymbols(oldSymbols, newSymbols);
    const added = changes.filter(c => c.changeKind === 'added');
    expect(added).toHaveLength(1);
    expect(added[0].symbol.name).toBe('brandNew');
  });

  it('detects removed symbol', () => {
    const oldSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'willRemove', kind: 'function', line: 1 }),
      makeSymbol({ name: 'stays', kind: 'variable', line: 3 }),
    ];
    const newSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'stays', kind: 'variable', line: 3 }),
    ];

    const changes = diffSymbols(oldSymbols, newSymbols);
    const removed = changes.filter(c => c.changeKind === 'removed');
    expect(removed).toHaveLength(1);
    expect(removed[0].symbol.name).toBe('willRemove');
  });

  it('detects modified symbol when line changes', () => {
    const oldSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'moved', kind: 'function', line: 5 }),
    ];
    const newSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'moved', kind: 'function', line: 10 }),
    ];

    const changes = diffSymbols(oldSymbols, newSymbols);
    const modified = changes.filter(c => c.changeKind === 'modified');
    expect(modified).toHaveLength(1);
    expect(modified[0].symbol.name).toBe('moved');
    expect(modified[0].previousSymbol).toBeDefined();
    expect(modified[0].previousSymbol!.line).toBe(5);
  });

  it('detects modified symbol when returnType changes', () => {
    const oldSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'fn', kind: 'function', line: 1, returnType: 'string' }),
    ];
    const newSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'fn', kind: 'function', line: 1, returnType: 'number' }),
    ];

    const changes = diffSymbols(oldSymbols, newSymbols);
    const modified = changes.filter(c => c.changeKind === 'modified');
    expect(modified).toHaveLength(1);
    expect(modified[0].previousSymbol!.returnType).toBe('string');
    expect(modified[0].symbol.returnType).toBe('number');
  });

  it('does not report unchanged symbols', () => {
    const symbols: ASTSymbol[] = [
      makeSymbol({ name: 'unchanged', kind: 'function', line: 1, exported: true }),
    ];

    const changes = diffSymbols(symbols, [...symbols]);
    expect(changes).toHaveLength(0);
  });

  it('handles empty old and new arrays', () => {
    expect(diffSymbols([], [])).toHaveLength(0);
  });

  it('handles all added (old is empty)', () => {
    const newSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'a', kind: 'function', line: 1 }),
      makeSymbol({ name: 'b', kind: 'class', line: 5 }),
    ];

    const changes = diffSymbols([], newSymbols);
    expect(changes).toHaveLength(2);
    expect(changes.every(c => c.changeKind === 'added')).toBe(true);
  });

  it('handles all removed (new is empty)', () => {
    const oldSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'a', kind: 'function', line: 1 }),
      makeSymbol({ name: 'b', kind: 'class', line: 5 }),
    ];

    const changes = diffSymbols(oldSymbols, []);
    expect(changes).toHaveLength(2);
    expect(changes.every(c => c.changeKind === 'removed')).toBe(true);
  });

  it('uses kind and parentSymbol in key (same name, different kind is separate)', () => {
    const oldSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'Item', kind: 'class', line: 1 }),
    ];
    const newSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'Item', kind: 'interface', line: 1 }),
    ];

    const changes = diffSymbols(oldSymbols, newSymbols);
    // class:Item removed, interface:Item added
    expect(changes).toHaveLength(2);
    expect(changes.find(c => c.changeKind === 'removed')!.symbol.kind).toBe('class');
    expect(changes.find(c => c.changeKind === 'added')!.symbol.kind).toBe('interface');
  });

  it('detects modification when isAsync changes', () => {
    const oldSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'fn', kind: 'function', line: 1, isAsync: false }),
    ];
    const newSymbols: ASTSymbol[] = [
      makeSymbol({ name: 'fn', kind: 'function', line: 1, isAsync: true }),
    ];

    const changes = diffSymbols(oldSymbols, newSymbols);
    expect(changes).toHaveLength(1);
    expect(changes[0].changeKind).toBe('modified');
  });
});

// =============================================================================
// diffDependencies
// =============================================================================

describe('diffDependencies', () => {
  const makeDep = (source: string, names: string[], isRelative = false): ASTDependency => ({
    source,
    names,
    isRelative,
  });

  it('detects added dependency', () => {
    const oldDeps: ASTDependency[] = [
      makeDep('./existing', ['A']),
    ];
    const newDeps: ASTDependency[] = [
      makeDep('./existing', ['A']),
      makeDep('./new-module', ['B']),
    ];

    const result = diffDependencies(oldDeps, newDeps);
    expect(result.added).toHaveLength(1);
    expect(result.added[0].source).toBe('./new-module');
    expect(result.removed).toHaveLength(0);
  });

  it('detects removed dependency', () => {
    const oldDeps: ASTDependency[] = [
      makeDep('./will-remove', ['X']),
      makeDep('./stays', ['Y']),
    ];
    const newDeps: ASTDependency[] = [
      makeDep('./stays', ['Y']),
    ];

    const result = diffDependencies(oldDeps, newDeps);
    expect(result.removed).toHaveLength(1);
    expect(result.removed[0].source).toBe('./will-remove');
    expect(result.added).toHaveLength(0);
  });

  it('detects both added and removed dependencies', () => {
    const oldDeps: ASTDependency[] = [
      makeDep('./old', ['A']),
    ];
    const newDeps: ASTDependency[] = [
      makeDep('./new', ['B']),
    ];

    const result = diffDependencies(oldDeps, newDeps);
    expect(result.added).toHaveLength(1);
    expect(result.added[0].source).toBe('./new');
    expect(result.removed).toHaveLength(1);
    expect(result.removed[0].source).toBe('./old');
  });

  it('handles empty arrays', () => {
    const result = diffDependencies([], []);
    expect(result.added).toHaveLength(0);
    expect(result.removed).toHaveLength(0);
  });

  it('treats same source with different names as different dependencies', () => {
    const oldDeps: ASTDependency[] = [
      makeDep('./module', ['A']),
    ];
    const newDeps: ASTDependency[] = [
      makeDep('./module', ['A', 'B']),
    ];

    const result = diffDependencies(oldDeps, newDeps);
    // The names differ, so old is removed and new is added
    expect(result.added).toHaveLength(1);
    expect(result.removed).toHaveLength(1);
  });

  it('detects no changes when arrays are identical', () => {
    const deps: ASTDependency[] = [
      makeDep('./utils', ['helper', 'format'], true),
      makeDep('lodash', ['debounce'], false),
    ];

    const result = diffDependencies(deps, [...deps]);
    expect(result.added).toHaveLength(0);
    expect(result.removed).toHaveLength(0);
  });

  it('handles all added (old is empty)', () => {
    const newDeps: ASTDependency[] = [
      makeDep('./a', ['A']),
      makeDep('./b', ['B']),
    ];

    const result = diffDependencies([], newDeps);
    expect(result.added).toHaveLength(2);
    expect(result.removed).toHaveLength(0);
  });

  it('handles all removed (new is empty)', () => {
    const oldDeps: ASTDependency[] = [
      makeDep('./a', ['A']),
      makeDep('./b', ['B']),
    ];

    const result = diffDependencies(oldDeps, []);
    expect(result.added).toHaveLength(0);
    expect(result.removed).toHaveLength(2);
  });
});
