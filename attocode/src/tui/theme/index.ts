/**
 * Theme System
 *
 * Provides dark, light, and custom theme support for the TUI.
 */

import type { Theme, ThemeColors, ThemeName } from '../types.js';

// =============================================================================
// DARK THEME
// =============================================================================

export const darkColors: ThemeColors = {
  // Primary colors
  primary: '#61afef',
  secondary: '#98c379',
  accent: '#c678dd',

  // Text colors
  text: '#abb2bf',
  textMuted: '#5c6370',
  textInverse: '#282c34',

  // Background colors
  background: '#282c34',
  backgroundAlt: '#21252b',

  // Semantic colors
  success: '#98c379',
  error: '#e06c75',
  warning: '#e5c07b',
  info: '#61afef',

  // Component colors
  border: '#3e4451',
  borderFocus: '#61afef',

  // Role colors
  userMessage: '#61afef',
  assistantMessage: '#98c379',
  systemMessage: '#5c6370',
  toolMessage: '#56b6c2',  // Cyan for tools (vibrant, original style)

  // Code colors
  codeBackground: '#21252b',
  codeKeyword: '#c678dd',
  codeString: '#98c379',
  codeComment: '#5c6370',
  codeNumber: '#d19a66',
  codeFunction: '#61afef',
  codeType: '#e5c07b',
};

export const darkTheme: Theme = {
  name: 'dark',
  colors: darkColors,
  borderStyle: 'round',
  spinnerType: 'dots',
};

// =============================================================================
// LIGHT THEME
// =============================================================================

export const lightColors: ThemeColors = {
  // Primary colors
  primary: '#4078f2',
  secondary: '#50a14f',
  accent: '#a626a4',

  // Text colors
  text: '#383a42',
  textMuted: '#a0a1a7',
  textInverse: '#fafafa',

  // Background colors
  background: '#fafafa',
  backgroundAlt: '#f0f0f0',

  // Semantic colors
  success: '#50a14f',
  error: '#e45649',
  warning: '#c18401',
  info: '#4078f2',

  // Component colors
  border: '#d3d3d3',
  borderFocus: '#4078f2',

  // Role colors
  userMessage: '#4078f2',
  assistantMessage: '#50a14f',
  systemMessage: '#a0a1a7',
  toolMessage: '#0184bc',  // Cyan for tools (vibrant, readable on light bg)

  // Code colors
  codeBackground: '#f0f0f0',
  codeKeyword: '#a626a4',
  codeString: '#50a14f',
  codeComment: '#a0a1a7',
  codeNumber: '#986801',
  codeFunction: '#4078f2',
  codeType: '#c18401',
};

export const lightTheme: Theme = {
  name: 'light',
  colors: lightColors,
  borderStyle: 'round',
  spinnerType: 'dots',
};

// =============================================================================
// HIGH CONTRAST THEME
// =============================================================================

export const highContrastColors: ThemeColors = {
  primary: '#00ff00',
  secondary: '#00ffff',
  accent: '#ff00ff',
  text: '#ffffff',
  textMuted: '#cccccc',
  textInverse: '#000000',
  background: '#000000',
  backgroundAlt: '#1a1a1a',
  success: '#00ff00',
  error: '#ff0000',
  warning: '#ffff00',
  info: '#00ffff',
  border: '#ffffff',
  borderFocus: '#00ff00',
  userMessage: '#00ffff',
  assistantMessage: '#00ff00',
  systemMessage: '#cccccc',
  toolMessage: '#ffff00',
  codeBackground: '#1a1a1a',
  codeKeyword: '#ff00ff',
  codeString: '#00ff00',
  codeComment: '#808080',
  codeNumber: '#ffff00',
  codeFunction: '#00ffff',
  codeType: '#ff8800',
};

export const highContrastTheme: Theme = {
  name: 'high-contrast',
  colors: highContrastColors,
  borderStyle: 'bold',
  spinnerType: 'line',
};

// =============================================================================
// THEME REGISTRY
// =============================================================================

const themes = new Map<string, Theme>([
  ['dark', darkTheme],
  ['light', lightTheme],
  ['high-contrast', highContrastTheme],
]);

/**
 * Register a custom theme.
 */
export function registerTheme(theme: Theme): void {
  themes.set(theme.name, theme);
}

/**
 * Get a theme by name.
 */
export function getTheme(name: ThemeName): Theme {
  if (name === 'auto') {
    return detectSystemTheme();
  }
  return themes.get(name) ?? darkTheme;
}

/**
 * Get all registered theme names.
 */
export function getThemeNames(): string[] {
  return Array.from(themes.keys());
}

/**
 * Detect system preference for dark/light mode.
 */
export function detectSystemTheme(): Theme {
  // Check environment variables for theme hints
  const colorTerm = process.env.COLORFGBG;
  if (colorTerm) {
    // COLORFGBG format: "fg;bg" - high bg value usually means light theme
    const parts = colorTerm.split(';');
    const bg = parseInt(parts[parts.length - 1], 10);
    if (!isNaN(bg) && bg > 7) {
      return lightTheme;
    }
  }

  // Check for macOS dark mode
  if (process.env.TERM_PROGRAM === 'Apple_Terminal' || process.env.TERM_PROGRAM === 'iTerm.app') {
    // Could potentially check system preference, but default to dark for terminals
  }

  // Check for explicit dark mode env vars
  if (process.env.DARK_MODE === 'true' || process.env.THEME === 'dark') {
    return darkTheme;
  }

  // Default to dark theme for terminals
  return darkTheme;
}

// =============================================================================
// THEME CONTEXT (for React)
// =============================================================================

export interface ThemeContextValue {
  theme: Theme;
  setTheme: (name: ThemeName) => void;
}

// Will be used with React.createContext when Ink is loaded
export const defaultThemeContext: ThemeContextValue = {
  theme: darkTheme,
  setTheme: () => {},
};

// =============================================================================
// COLOR UTILITIES
// =============================================================================

/**
 * Convert hex color to ANSI escape code (basic 16 colors approximation).
 */
export function hexToAnsi(hex: string): string {
  // Simple mapping for common colors
  const colorMap: Record<string, string> = {
    '#61afef': '\x1b[34m',   // blue
    '#98c379': '\x1b[32m',   // green
    '#c678dd': '\x1b[35m',   // magenta
    '#e06c75': '\x1b[31m',   // red
    '#e5c07b': '\x1b[33m',   // yellow
    '#56b6c2': '\x1b[36m',   // cyan
    '#abb2bf': '\x1b[37m',   // white/gray
    '#5c6370': '\x1b[90m',   // bright black/gray
    '#282c34': '\x1b[40m',   // bg black
  };

  return colorMap[hex.toLowerCase()] ?? '\x1b[37m';
}

/**
 * Get ANSI color for a theme color name.
 */
export function getAnsiColor(theme: Theme, colorName: keyof ThemeColors): string {
  return hexToAnsi(theme.colors[colorName]);
}

// =============================================================================
// EXPORTS
// =============================================================================

export type { Theme, ThemeColors, ThemeName };
export { themes };
