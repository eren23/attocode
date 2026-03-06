/**
 * Tests for TypeScript Compilation Checker
 */
import { describe, it, expect } from 'vitest';
import * as path from 'node:path';
import {
  detectTypeScriptProject,
  parseTypeCheckOutput,
  formatTypeCheckNudge,
  createTypeCheckerState,
  type TypeCheckResult,
} from '../../src/integrations/safety/type-checker.js';

describe('TypeChecker', () => {
  describe('detectTypeScriptProject', () => {
    it('should detect tsconfig.json in cwd', () => {
      // The attocode project root has a tsconfig.json
      const projectRoot = path.resolve(__dirname, '../..');
      const result = detectTypeScriptProject(projectRoot);
      expect(result).toBe(projectRoot);
    });

    it('should walk up directories to find tsconfig.json', () => {
      // Start from a subdirectory
      const subDir = path.resolve(__dirname, '../../src/integrations/safety');
      const result = detectTypeScriptProject(subDir);
      // Should find the project root's tsconfig.json
      expect(result).toBeTruthy();
      expect(result!.endsWith('attocode')).toBe(true);
    });

    it('should return null when no tsconfig.json exists', () => {
      const result = detectTypeScriptProject('/tmp');
      expect(result).toBeNull();
    });
  });

  describe('parseTypeCheckOutput', () => {
    it('should parse single error', () => {
      const output = `src/index.ts(10,5): error TS2554: Expected 2 arguments, but got 1.`;
      const errors = parseTypeCheckOutput(output);
      expect(errors).toHaveLength(1);
      expect(errors[0]).toEqual({
        file: 'src/index.ts',
        line: 10,
        column: 5,
        code: 'TS2554',
        message: 'Expected 2 arguments, but got 1.',
      });
    });

    it('should parse multiple errors', () => {
      const output = [
        `src/foo.ts(1,1): error TS2304: Cannot find name 'foo'.`,
        `src/bar.ts(20,10): error TS2345: Argument of type 'string' is not assignable to parameter of type 'number'.`,
        `src/baz.tsx(5,3): error TS7006: Parameter 'x' implicitly has an 'any' type.`,
      ].join('\n');
      const errors = parseTypeCheckOutput(output);
      expect(errors).toHaveLength(3);
      expect(errors[0].file).toBe('src/foo.ts');
      expect(errors[0].code).toBe('TS2304');
      expect(errors[1].file).toBe('src/bar.ts');
      expect(errors[1].line).toBe(20);
      expect(errors[2].file).toBe('src/baz.tsx');
      expect(errors[2].code).toBe('TS7006');
    });

    it('should return empty array for clean output', () => {
      const errors = parseTypeCheckOutput('');
      expect(errors).toHaveLength(0);
    });

    it('should ignore non-error lines', () => {
      const output = [
        'Some random log line',
        `src/foo.ts(1,1): error TS2304: Cannot find name 'foo'.`,
        'Another log line',
      ].join('\n');
      const errors = parseTypeCheckOutput(output);
      expect(errors).toHaveLength(1);
    });

    it('should handle Windows-style paths', () => {
      const output = `src\\utils\\helper.ts(15,8): error TS2322: Type 'string' is not assignable to type 'number'.`;
      const errors = parseTypeCheckOutput(output);
      expect(errors).toHaveLength(1);
      expect(errors[0].file).toBe('src\\utils\\helper.ts');
    });
  });

  describe('formatTypeCheckNudge', () => {
    it('should format errors as nudge message', () => {
      const result: TypeCheckResult = {
        success: false,
        errorCount: 2,
        errors: [
          { file: 'src/a.ts', line: 1, column: 1, code: 'TS2304', message: "Cannot find name 'x'." },
          { file: 'src/b.ts', line: 5, column: 3, code: 'TS2345', message: 'Type mismatch.' },
        ],
        duration: 1000,
      };

      const nudge = formatTypeCheckNudge(result);
      expect(nudge).toContain('2 error(s)');
      expect(nudge).toContain('src/a.ts(1,1): TS2304');
      expect(nudge).toContain('src/b.ts(5,3): TS2345');
      expect(nudge).toContain('Fix these TypeScript compilation errors');
    });

    it('should truncate when maxErrors exceeded', () => {
      const errors = Array.from({ length: 20 }, (_, i) => ({
        file: `src/file${i}.ts`,
        line: i + 1,
        column: 1,
        code: 'TS2304',
        message: `Error ${i}`,
      }));

      const result: TypeCheckResult = {
        success: false,
        errorCount: 20,
        errors,
        duration: 500,
      };

      const nudge = formatTypeCheckNudge(result, 5);
      expect(nudge).toContain('20 error(s)');
      expect(nudge).toContain('file0');
      expect(nudge).toContain('file4');
      expect(nudge).not.toContain('file5');
      expect(nudge).toContain('15 more error(s)');
    });

    it('should not show overflow message when within limit', () => {
      const result: TypeCheckResult = {
        success: false,
        errorCount: 2,
        errors: [
          { file: 'a.ts', line: 1, column: 1, code: 'TS2304', message: 'err' },
          { file: 'b.ts', line: 2, column: 1, code: 'TS2304', message: 'err' },
        ],
        duration: 100,
      };

      const nudge = formatTypeCheckNudge(result);
      expect(nudge).not.toContain('more error');
    });
  });

  describe('createTypeCheckerState', () => {
    it('should detect TS project from project root', () => {
      const projectRoot = path.resolve(__dirname, '../..');
      const state = createTypeCheckerState(projectRoot);
      expect(state.tsconfigDir).toBe(projectRoot);
      expect(state.tsEditsSinceLastCheck).toBe(0);
      expect(state.lastResult).toBeNull();
      expect(state.hasRunOnce).toBe(false);
    });

    it('should return null tsconfigDir for non-TS directory', () => {
      const state = createTypeCheckerState('/tmp');
      expect(state.tsconfigDir).toBeNull();
      expect(state.tsEditsSinceLastCheck).toBe(0);
    });
  });
});
