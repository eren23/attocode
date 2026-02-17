/**
 * CommandPalette Component (Controlled)
 *
 * Fuzzy-search command palette for quick access to commands.
 *
 * IMPORTANT: This is a CONTROLLED component with NO useInput hook.
 * All keyboard handling must be done by the parent component
 * (MemoizedInputArea) to prevent input conflicts.
 */

import { useMemo } from 'react';
import { Box, Text } from 'ink';
import type { CommandPaletteItem } from '../types.js';
import type { Theme } from '../theme/index.js';

/**
 * Original props (uncontrolled version - kept for backwards compatibility)
 */
export interface CommandPaletteProps {
  theme: Theme;
  items: CommandPaletteItem[];
  visible: boolean;
  onSelect: (item: CommandPaletteItem) => void;
  onClose: () => void;
  placeholder?: string;
  maxVisible?: number;
}

/**
 * Controlled version props - parent manages query and selection state
 */
export interface ControlledCommandPaletteProps {
  theme: Theme;
  items: CommandPaletteItem[];
  visible: boolean;
  /** Current search query (controlled by parent) */
  query: string;
  /** Currently selected index (controlled by parent) */
  selectedIndex: number;
  /** Callback when user changes query */
  onQueryChange: (query: string) => void;
  /** Callback when user selects an item */
  onSelectItem: (item: CommandPaletteItem) => void;
  /** Callback to close the palette */
  onClose: () => void;
  placeholder?: string;
  maxVisible?: number;
}

/**
 * Simple fuzzy match scoring.
 * Returns a score where higher is better, or -1 for no match.
 */
function fuzzyMatch(query: string, text: string): number {
  if (!query) return 0;

  const q = query.toLowerCase();
  const t = text.toLowerCase();

  // Exact match gets highest score
  if (t === q) return 1000;

  // Starts with gets high score
  if (t.startsWith(q)) return 500 + (q.length / t.length) * 100;

  // Contains gets medium score
  if (t.includes(q)) return 200 + (q.length / t.length) * 100;

  // Fuzzy character matching
  let queryIndex = 0;
  let score = 0;
  let consecutiveBonus = 0;

  for (let i = 0; i < t.length && queryIndex < q.length; i++) {
    if (t[i] === q[queryIndex]) {
      queryIndex++;
      score += 10 + consecutiveBonus;
      consecutiveBonus += 5; // Bonus for consecutive matches
    } else {
      consecutiveBonus = 0;
    }
  }

  // All characters must match
  if (queryIndex !== q.length) return -1;

  return score;
}

/**
 * Highlight matching characters in text.
 */
function HighlightedText({
  theme,
  text,
  query,
  baseColor,
}: {
  theme: Theme;
  text: string;
  query: string;
  baseColor: string;
}) {
  if (!query) {
    return <Text color={baseColor}>{text}</Text>;
  }

  const q = query.toLowerCase();
  const t = text.toLowerCase();
  const parts: Array<{ text: string; highlight: boolean }> = [];

  let queryIndex = 0;
  let currentPart = '';
  let isHighlighted = false;

  for (let i = 0; i < text.length; i++) {
    const matches = queryIndex < q.length && t[i] === q[queryIndex];

    if (matches !== isHighlighted) {
      if (currentPart) {
        parts.push({ text: currentPart, highlight: isHighlighted });
      }
      currentPart = text[i];
      isHighlighted = matches;
    } else {
      currentPart += text[i];
    }

    if (matches) {
      queryIndex++;
    }
  }

  if (currentPart) {
    parts.push({ text: currentPart, highlight: isHighlighted });
  }

  return (
    <Text>
      {parts.map((part, i) => (
        <Text
          key={i}
          color={part.highlight ? theme.colors.accent : baseColor}
          bold={part.highlight}
        >
          {part.text}
        </Text>
      ))}
    </Text>
  );
}

/**
 * Controlled command palette component.
 * NO useInput hook - parent handles all keyboard input.
 */
export function ControlledCommandPalette({
  theme,
  items,
  visible,
  query,
  selectedIndex,
  // These props are passed by parent but used via callbacks, not rendered directly
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  onQueryChange: _onQueryChange,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  onSelectItem: _onSelectItem,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  onClose: _onClose,
  placeholder = 'Type to search commands...',
  maxVisible = 10,
}: ControlledCommandPaletteProps) {
  // Filter and sort items by fuzzy match score
  const filteredItems = useMemo(() => {
    if (!query) return items.slice(0, maxVisible);

    return items
      .map((item) => ({
        item,
        score: Math.max(
          fuzzyMatch(query, item.label),
          fuzzyMatch(query, item.description || ''),
          fuzzyMatch(query, item.id),
        ),
      }))
      .filter(({ score }) => score >= 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, maxVisible)
      .map(({ item }) => item);
  }, [items, query, maxVisible]);

  if (!visible) return null;

  // Group items by category
  const categories = useMemo(() => {
    const cats = new Map<string, CommandPaletteItem[]>();
    for (const item of filteredItems) {
      const cat = item.category || 'Commands';
      if (!cats.has(cat)) cats.set(cat, []);
      cats.get(cat)!.push(item);
    }
    return cats;
  }, [filteredItems]);

  return (
    <Box
      flexDirection="column"
      position="absolute"
      marginTop={2}
      marginLeft={2}
      borderStyle={theme.borderStyle}
      borderColor={theme.colors.borderFocus}
      paddingX={1}
      paddingY={1}
      width={60}
    >
      {/* Search input */}
      <Box marginBottom={1}>
        <Text color={theme.colors.primary}>{'>'} </Text>
        {query ? <Text>{query}</Text> : <Text color={theme.colors.textMuted}>{placeholder}</Text>}
        <Text backgroundColor={theme.colors.primary} color={theme.colors.textInverse}>
          {' '}
        </Text>
      </Box>

      {/* Divider */}
      <Box marginBottom={1}>
        <Text color={theme.colors.border}>{'─'.repeat(56)}</Text>
      </Box>

      {/* Results */}
      {filteredItems.length === 0 ? (
        <Box>
          <Text color={theme.colors.textMuted}>No matching commands</Text>
        </Box>
      ) : (
        Array.from(categories.entries()).map(([category, categoryItems]) => (
          <Box key={category} flexDirection="column" marginBottom={1}>
            {/* Category header */}
            <Box marginBottom={1}>
              <Text color={theme.colors.textMuted} dimColor>
                {category}
              </Text>
            </Box>

            {/* Items */}
            {categoryItems.map((item) => {
              const itemIndex = filteredItems.indexOf(item);
              const isSelected = itemIndex === selectedIndex;

              return (
                <Box key={item.id} paddingX={1}>
                  {/* Selection indicator */}
                  <Text color={isSelected ? theme.colors.primary : theme.colors.textMuted}>
                    {isSelected ? '>' : ' '}{' '}
                  </Text>

                  <Box width={38}>
                    <HighlightedText
                      theme={theme}
                      text={item.label}
                      query={query}
                      baseColor={isSelected ? theme.colors.primary : theme.colors.text}
                    />
                  </Box>

                  {/* Shortcut */}
                  {item.shortcut && (
                    <Box width={12}>
                      <Text color={theme.colors.accent}>{item.shortcut}</Text>
                    </Box>
                  )}
                </Box>
              );
            })}
          </Box>
        ))
      )}

      {/* Footer hints */}
      <Box marginTop={1} justifyContent="space-between">
        <Text color={theme.colors.textMuted}>
          <Text color={theme.colors.accent}>Enter</Text> select{' '}
          <Text color={theme.colors.accent}>Esc</Text> close{' '}
          <Text color={theme.colors.accent}>↑↓</Text> navigate
        </Text>
      </Box>
    </Box>
  );
}

/**
 * Alias for backwards compatibility.
 * Use ControlledCommandPalette directly when integrating with the TUI.
 */
export const CommandPalette = ControlledCommandPalette;

export default ControlledCommandPalette;
