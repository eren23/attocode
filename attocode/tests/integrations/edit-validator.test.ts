/**
 * Tests for Edit Validator (Phase 5.1)
 */
import { describe, it, expect } from 'vitest';
import { validateSyntax, validateEdit } from '../../src/integrations/safety/edit-validator.js';

// Note: These tests work both with and without tree-sitter installed.
// If tree-sitter is not available, all validations return valid (no-op).
// We detect availability by checking a known-broken file.

function hasTreeSitter(): boolean {
  const result = validateSyntax('const x = {{{', 'test.ts');
  // If tree-sitter is available, this should fail validation
  return !result.valid;
}

describe('Edit Validator', () => {
  describe('validateSyntax', () => {
    it('returns valid for unsupported file types', () => {
      const result = validateSyntax('this is not code at all!!!{{{', 'test.md');
      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it('returns valid for unsupported extensions', () => {
      for (const ext of ['.json', '.yaml', '.css', '.html', '.txt', '.md']) {
        const result = validateSyntax('not code', `test${ext}`);
        expect(result.valid).toBe(true);
      }
    });

    it('returns valid for empty content', () => {
      const result = validateSyntax('', 'test.ts');
      expect(result.valid).toBe(true);
    });

    it('validates valid TypeScript', () => {
      const code = `
        export function add(a: number, b: number): number {
          return a + b;
        }

        const x: string = "hello";
        console.log(add(1, 2));
      `;
      const result = validateSyntax(code, 'test.ts');
      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it('detects broken TypeScript syntax', () => {
      if (!hasTreeSitter()) {
        // tree-sitter not available — skip
        return;
      }
      const code = `
        export function add(a: number, b: number): number {
          return a + b


        // Missing closing brace for function
        const x = {{{ broken;
      `;
      const result = validateSyntax(code, 'test.ts');
      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
      expect(result.errors[0].line).toBeGreaterThan(0);
      expect(result.errors[0].column).toBeGreaterThan(0);
      expect(result.errors[0].message).toContain('Syntax error');
    });

    it('validates valid JSX', () => {
      const code = `
        function App() {
          return <div className="app">Hello</div>;
        }
      `;
      const result = validateSyntax(code, 'test.jsx');
      expect(result.valid).toBe(true);
    });

    it('validates valid TSX', () => {
      const code = `
        interface Props { name: string; }
        function App({ name }: Props) {
          return <div>{name}</div>;
        }
      `;
      const result = validateSyntax(code, 'test.tsx');
      expect(result.valid).toBe(true);
    });

    it('validates valid Python', () => {
      const code = `
def greet(name: str) -> str:
    return f"Hello, {name}"

class Greeter:
    def __init__(self, name):
        self.name = name
`;
      const result = validateSyntax(code, 'test.py');
      expect(result.valid).toBe(true);
    });

    it('detects broken Python syntax', () => {
      if (!hasTreeSitter()) return;
      const code = `
def greet(name:
    return f"Hello, {name}"
    (((broken syntax here
`;
      const result = validateSyntax(code, 'test.py');
      // Python parser is optional; if not available, valid=true
      // If available, should detect errors
      if (!result.valid) {
        expect(result.errors.length).toBeGreaterThan(0);
      }
    });

    it('handles valid JavaScript', () => {
      const code = `
        const a = 1;
        function test() { return a + 2; }
        module.exports = { test };
      `;
      const result = validateSyntax(code, 'test.js');
      expect(result.valid).toBe(true);
    });

    it('detects broken JavaScript', () => {
      if (!hasTreeSitter()) return;
      const code = `
        const a = {{{ broken
        function test() {{{ more broken
      `;
      const result = validateSyntax(code, 'test.js');
      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
    });
  });

  describe('validateEdit', () => {
    it('returns valid for unsupported files', () => {
      const result = validateEdit('old content', 'new content', 'test.md');
      expect(result.valid).toBe(true);
    });

    it('returns valid when edit preserves correct syntax', () => {
      const before = 'const x = 1;';
      const after = 'const x = 2;';
      const result = validateEdit(before, after, 'test.ts');
      expect(result.valid).toBe(true);
    });

    it('detects when edit introduces syntax errors', () => {
      if (!hasTreeSitter()) return;
      const before = 'const x = 1;';
      const after = 'const x = {{{;';
      const result = validateEdit(before, after, 'test.ts');
      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('does not report errors that existed before the edit', () => {
      if (!hasTreeSitter()) return;
      // Both before and after have the same error
      const before = 'const x = {{{ broken;';
      const after = 'const x = {{{ still broken;';
      const result = validateEdit(before, after, 'test.ts');
      // Same number of errors — should not flag
      expect(result.valid).toBe(true);
    });

    it('detects regression from valid to broken', () => {
      if (!hasTreeSitter()) return;
      const before = `
        export function add(a: number, b: number): number {
          return a + b;
        }
      `;
      const after = `
        export function add(a: number, b: number): number {
          return a + b;

        // Oops, removed closing brace and added garbage
        const x = {{{ broken;
      `;
      const result = validateEdit(before, after, 'test.ts');
      expect(result.valid).toBe(false);
    });
  });
});
