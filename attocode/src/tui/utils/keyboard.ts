/**
 * Cross-Platform Keyboard Utilities
 *
 * Handles keyboard shortcuts across Mac, Linux, and Windows.
 *
 * Problem: On Mac, Option+key produces Unicode characters (Option+T → †)
 * but on Linux/Windows, Alt+key may be handled differently.
 *
 * This module normalizes key detection so shortcuts work consistently.
 */

/**
 * Key event structure from Ink's useInput hook.
 */
export interface KeyEvent {
  ctrl?: boolean;
  meta?: boolean;
  shift?: boolean;
  escape?: boolean;
  return?: boolean;
  backspace?: boolean;
  delete?: boolean;
  upArrow?: boolean;
  downArrow?: boolean;
  leftArrow?: boolean;
  rightArrow?: boolean;
  pageUp?: boolean;
  pageDown?: boolean;
}

/**
 * Normalized shortcut result.
 */
export interface NormalizedShortcut {
  type: 'alt-t' | 'alt-o' | 'alt-i' | 'alt-d' | 'alt-s' | 'none';
  matched: boolean;
  raw: string;
}

/**
 * Mac Unicode mappings for Option+key combinations.
 *
 * When you press Option+T on Mac terminal, it produces Unicode character †
 * This maps those characters back to their intended shortcuts.
 */
const MAC_UNICODE_MAP: Record<string, string> = {
  '\u2020': 't', // Option+T → † (dagger)
  '\u00f8': 'o', // Option+O → ø (o with stroke)
  '\u00ee': 'i', // Option+I → î (i with circumflex) - some terminals
  '\u0131': 'i', // Option+I → ı (dotless i) - other terminals
  '\u2202': 'd', // Option+D → ∂ (partial differential)
  '\u00df': 's', // Option+S → ß (sharp s)
  '\u00a9': 'g', // Option+G → © (copyright)
  '\u00ae': 'r', // Option+R → ® (registered)
  '\u2211': 'w', // Option+W → ∑ (summation)
  '\u0153': 'q', // Option+Q → œ (oe ligature)
  '\u00e5': 'a', // Option+A → å (a with ring)
};

/**
 * Detect Alt/Option key shortcuts cross-platform.
 *
 * @param input - The input string from useInput
 * @param key - The key event object from useInput
 * @returns The normalized letter if it's an Alt shortcut, null otherwise
 *
 * @example
 * ```tsx
 * useInput((input, key) => {
 *   const altKey = detectAltShortcut(input, key);
 *   if (altKey === 't') {
 *     toggleToolExpand();
 *   }
 * });
 * ```
 */
export function detectAltShortcut(input: string, key: KeyEvent): string | null {
  // Check Mac Unicode characters first
  const macLetter = MAC_UNICODE_MAP[input];
  if (macLetter) {
    return macLetter;
  }

  // Check standard Alt+key (key.meta in Ink represents Alt on some systems)
  // Note: Ink uses 'meta' for Cmd on Mac and Alt on Linux/Windows
  if (key.meta && input.length === 1 && input.match(/[a-z]/i)) {
    return input.toLowerCase();
  }

  return null;
}

/**
 * Check if a specific Alt shortcut was pressed.
 *
 * @example
 * ```tsx
 * if (isAltShortcut(input, key, 't')) {
 *   toggleToolExpand();
 * }
 * ```
 */
export function isAltShortcut(input: string, key: KeyEvent, letter: string): boolean {
  return detectAltShortcut(input, key) === letter.toLowerCase();
}

/**
 * Normalize input to a named shortcut.
 *
 * @example
 * ```tsx
 * const shortcut = normalizeShortcut(input, key);
 * switch (shortcut.type) {
 *   case 'alt-t': toggleToolExpand(); break;
 *   case 'alt-o': toggleThinking(); break;
 *   case 'alt-i': toggleTransparency(); break;
 * }
 * ```
 */
export function normalizeShortcut(input: string, key: KeyEvent): NormalizedShortcut {
  const altKey = detectAltShortcut(input, key);

  if (!altKey) {
    return { type: 'none', matched: false, raw: input };
  }

  switch (altKey) {
    case 't':
      return { type: 'alt-t', matched: true, raw: input };
    case 'o':
      return { type: 'alt-o', matched: true, raw: input };
    case 'i':
      return { type: 'alt-i', matched: true, raw: input };
    case 'd':
      return { type: 'alt-d', matched: true, raw: input };
    case 's':
      return { type: 'alt-s', matched: true, raw: input };
    default:
      return { type: 'none', matched: false, raw: input };
  }
}

/**
 * Create a keyboard handler config for common TUI shortcuts.
 *
 * @example
 * ```tsx
 * const shortcuts = createShortcutHandler({
 *   onAltT: () => toggleToolExpand(),
 *   onAltO: () => toggleThinking(),
 *   onAltI: () => toggleTransparency(),
 *   onCtrlC: () => exit(),
 *   onCtrlL: () => clearScreen(),
 *   onCtrlP: () => toggleCommandPalette(),
 * });
 *
 * useInput((input, key) => {
 *   shortcuts.handle(input, key);
 * });
 * ```
 */
export interface ShortcutHandlers {
  onAltT?: () => void;
  onAltO?: () => void;
  onAltI?: () => void;
  onAltD?: () => void;
  onAltS?: () => void;
  onCtrlC?: () => void;
  onCtrlL?: () => void;
  onCtrlP?: () => void;
  onEscape?: () => void;
}

export function createShortcutHandler(handlers: ShortcutHandlers) {
  return {
    /**
     * Handle an input event. Returns true if a shortcut was handled.
     */
    handle(input: string, key: KeyEvent): boolean {
      // Global Ctrl shortcuts
      if (key.ctrl) {
        if (input === 'c' && handlers.onCtrlC) {
          handlers.onCtrlC();
          return true;
        }
        if (input === 'l' && handlers.onCtrlL) {
          handlers.onCtrlL();
          return true;
        }
        if (input === 'p' && handlers.onCtrlP) {
          handlers.onCtrlP();
          return true;
        }
      }

      // Escape
      if (key.escape && handlers.onEscape) {
        handlers.onEscape();
        return true;
      }

      // Alt shortcuts
      const shortcut = normalizeShortcut(input, key);
      if (shortcut.matched) {
        switch (shortcut.type) {
          case 'alt-t':
            if (handlers.onAltT) { handlers.onAltT(); return true; }
            break;
          case 'alt-o':
            if (handlers.onAltO) { handlers.onAltO(); return true; }
            break;
          case 'alt-i':
            if (handlers.onAltI) { handlers.onAltI(); return true; }
            break;
          case 'alt-d':
            if (handlers.onAltD) { handlers.onAltD(); return true; }
            break;
          case 'alt-s':
            if (handlers.onAltS) { handlers.onAltS(); return true; }
            break;
        }
      }

      return false;
    },
  };
}

/**
 * Format a shortcut for display in help text.
 *
 * @example
 * formatShortcutDisplay('alt', 't') // Returns "Alt+T" or "⌥T" on Mac
 */
export function formatShortcutDisplay(modifier: 'alt' | 'ctrl' | 'meta', key: string): string {
  const isMac = process.platform === 'darwin';

  const modifierSymbols: Record<string, string> = isMac
    ? { alt: '⌥', ctrl: '⌃', meta: '⌘' }
    : { alt: 'Alt+', ctrl: 'Ctrl+', meta: 'Meta+' };

  return `${modifierSymbols[modifier]}${key.toUpperCase()}`;
}
