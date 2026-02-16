/**
 * Tests for Codebase AST Module (Phase 3.3)
 *
 * Tests tree-sitter based symbol and dependency extraction for
 * TypeScript/TSX and Python.
 */

import { describe, it, expect } from 'vitest';
import {
  extractSymbolsAST,
  extractDependenciesAST,
  isASTSupported,
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
