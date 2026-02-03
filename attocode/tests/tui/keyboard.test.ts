/**
 * Keyboard Utilities Tests
 *
 * Tests for cross-platform keyboard shortcut detection.
 */

import { describe, it, expect } from 'vitest';
import {
  detectAltShortcut,
  isAltShortcut,
  normalizeShortcut,
  createShortcutHandler,
  formatShortcutDisplay,
  type KeyEvent,
} from '../../src/tui/utils/keyboard.js';

describe('detectAltShortcut', () => {
  describe('Mac Unicode detection', () => {
    it('should detect Option+T (dagger †)', () => {
      const result = detectAltShortcut('\u2020', {});
      expect(result).toBe('t');
    });

    it('should detect Option+O (ø)', () => {
      const result = detectAltShortcut('\u00f8', {});
      expect(result).toBe('o');
    });

    it('should detect Option+I (î or ı)', () => {
      // î variant
      expect(detectAltShortcut('\u00ee', {})).toBe('i');
      // ı variant
      expect(detectAltShortcut('\u0131', {})).toBe('i');
    });

    it('should detect Option+D (∂)', () => {
      const result = detectAltShortcut('\u2202', {});
      expect(result).toBe('d');
    });

    it('should detect Option+S (ß)', () => {
      const result = detectAltShortcut('\u00df', {});
      expect(result).toBe('s');
    });
  });

  describe('standard Alt+key detection', () => {
    it('should detect Alt+letter with meta key', () => {
      const key: KeyEvent = { meta: true };
      expect(detectAltShortcut('t', key)).toBe('t');
      expect(detectAltShortcut('o', key)).toBe('o');
      expect(detectAltShortcut('i', key)).toBe('i');
    });

    it('should convert uppercase to lowercase', () => {
      const key: KeyEvent = { meta: true };
      expect(detectAltShortcut('T', key)).toBe('t');
    });

    it('should return null for non-letter with meta', () => {
      const key: KeyEvent = { meta: true };
      expect(detectAltShortcut('1', key)).toBeNull();
      expect(detectAltShortcut('!', key)).toBeNull();
    });
  });

  describe('non-shortcut detection', () => {
    it('should return null for regular letters', () => {
      expect(detectAltShortcut('t', {})).toBeNull();
      expect(detectAltShortcut('hello', {})).toBeNull();
    });

    it('should return null for empty input', () => {
      expect(detectAltShortcut('', {})).toBeNull();
    });

    it('should return null for unmapped Unicode', () => {
      expect(detectAltShortcut('\u2603', {})).toBeNull(); // Snowman
    });
  });
});

describe('isAltShortcut', () => {
  it('should return true for matching shortcut', () => {
    expect(isAltShortcut('\u2020', {}, 't')).toBe(true);
    expect(isAltShortcut('\u00f8', {}, 'o')).toBe(true);
  });

  it('should return false for non-matching shortcut', () => {
    expect(isAltShortcut('\u2020', {}, 'o')).toBe(false);
  });

  it('should be case-insensitive for the letter parameter', () => {
    expect(isAltShortcut('\u2020', {}, 'T')).toBe(true);
    expect(isAltShortcut('\u2020', {}, 't')).toBe(true);
  });
});

describe('normalizeShortcut', () => {
  it('should normalize alt-t shortcut', () => {
    const result = normalizeShortcut('\u2020', {});
    expect(result.type).toBe('alt-t');
    expect(result.matched).toBe(true);
    expect(result.raw).toBe('\u2020');
  });

  it('should normalize alt-o shortcut', () => {
    const result = normalizeShortcut('\u00f8', {});
    expect(result.type).toBe('alt-o');
    expect(result.matched).toBe(true);
  });

  it('should normalize alt-i shortcut', () => {
    const result = normalizeShortcut('\u0131', {});
    expect(result.type).toBe('alt-i');
    expect(result.matched).toBe(true);
  });

  it('should normalize alt-d shortcut', () => {
    const result = normalizeShortcut('\u2202', {});
    expect(result.type).toBe('alt-d');
    expect(result.matched).toBe(true);
  });

  it('should normalize alt-s shortcut', () => {
    const result = normalizeShortcut('\u00df', {});
    expect(result.type).toBe('alt-s');
    expect(result.matched).toBe(true);
  });

  it('should return none for unrecognized input', () => {
    const result = normalizeShortcut('hello', {});
    expect(result.type).toBe('none');
    expect(result.matched).toBe(false);
    expect(result.raw).toBe('hello');
  });

  it('should return none for unmapped Alt keys', () => {
    // Option+G produces © but maps to 'g' which isn't in the shortcut list
    const result = normalizeShortcut('\u00a9', {});
    expect(result.type).toBe('none');
    expect(result.matched).toBe(false);
  });
});

describe('createShortcutHandler', () => {
  it('should call onAltT handler for alt-t', () => {
    let called = false;
    const handler = createShortcutHandler({
      onAltT: () => { called = true; },
    });

    const result = handler.handle('\u2020', {});
    expect(result).toBe(true);
    expect(called).toBe(true);
  });

  it('should call onAltO handler for alt-o', () => {
    let called = false;
    const handler = createShortcutHandler({
      onAltO: () => { called = true; },
    });

    const result = handler.handle('\u00f8', {});
    expect(result).toBe(true);
    expect(called).toBe(true);
  });

  it('should call onCtrlC handler', () => {
    let called = false;
    const handler = createShortcutHandler({
      onCtrlC: () => { called = true; },
    });

    const result = handler.handle('c', { ctrl: true });
    expect(result).toBe(true);
    expect(called).toBe(true);
  });

  it('should call onCtrlL handler', () => {
    let called = false;
    const handler = createShortcutHandler({
      onCtrlL: () => { called = true; },
    });

    const result = handler.handle('l', { ctrl: true });
    expect(result).toBe(true);
    expect(called).toBe(true);
  });

  it('should call onCtrlP handler', () => {
    let called = false;
    const handler = createShortcutHandler({
      onCtrlP: () => { called = true; },
    });

    const result = handler.handle('p', { ctrl: true });
    expect(result).toBe(true);
    expect(called).toBe(true);
  });

  it('should call onEscape handler', () => {
    let called = false;
    const handler = createShortcutHandler({
      onEscape: () => { called = true; },
    });

    const result = handler.handle('', { escape: true });
    expect(result).toBe(true);
    expect(called).toBe(true);
  });

  it('should return false when no handler matches', () => {
    const handler = createShortcutHandler({
      onAltT: () => {},
    });

    const result = handler.handle('hello', {});
    expect(result).toBe(false);
  });

  it('should return false when handler not defined for shortcut', () => {
    const handler = createShortcutHandler({
      onAltT: () => {},
      // onAltO not defined
    });

    const result = handler.handle('\u00f8', {}); // alt-o
    expect(result).toBe(false);
  });

  it('should handle multiple shortcuts', () => {
    const calls: string[] = [];
    const handler = createShortcutHandler({
      onAltT: () => { calls.push('alt-t'); },
      onAltO: () => { calls.push('alt-o'); },
      onCtrlC: () => { calls.push('ctrl-c'); },
    });

    handler.handle('\u2020', {});
    handler.handle('\u00f8', {});
    handler.handle('c', { ctrl: true });

    expect(calls).toEqual(['alt-t', 'alt-o', 'ctrl-c']);
  });
});

describe('formatShortcutDisplay', () => {
  // Note: This test depends on process.platform which can't be easily mocked
  // Testing the actual output format

  it('should format alt shortcuts', () => {
    const result = formatShortcutDisplay('alt', 't');
    // Either "⌥T" (Mac) or "Alt+T" (other)
    expect(result).toMatch(/[⌥Alt\+]T/);
  });

  it('should format ctrl shortcuts', () => {
    const result = formatShortcutDisplay('ctrl', 'c');
    // Either "⌃C" (Mac) or "Ctrl+C" (other)
    expect(result).toMatch(/[⌃Ctrl\+]C/);
  });

  it('should format meta shortcuts', () => {
    const result = formatShortcutDisplay('meta', 's');
    // Either "⌘S" (Mac) or "Meta+S" (other)
    expect(result).toMatch(/[⌘Meta\+]S/);
  });

  it('should uppercase the key', () => {
    const result = formatShortcutDisplay('alt', 'a');
    expect(result).toContain('A');
    expect(result).not.toContain('a');
  });
});
