/**
 * ScrollableBox Component
 *
 * A virtualized scrollable container that supports keyboard navigation
 * and renders only visible items for performance.
 */

import { useState, useCallback, useEffect, memo, type ReactNode } from 'react';
import { Box, Text, useInput } from 'ink';
import type { Theme } from '../theme/index.js';

export interface ScrollableBoxProps {
  theme: Theme;
  /** Total number of items in the list */
  itemCount: number;
  /** Height of each item in lines (default: 1) */
  itemHeight?: number;
  /** Maximum visible height in lines */
  maxHeight: number;
  /** Render function for each item */
  renderItem: (index: number) => ReactNode;
  /** Whether this component has focus */
  focused?: boolean;
  /** Callback when scroll position changes */
  onScroll?: (scrollTop: number) => void;
  /** Auto-scroll to bottom when content changes */
  autoScrollToBottom?: boolean;
  /** Show scroll indicators */
  showScrollIndicators?: boolean;
  /** Buffer of extra items to render above/below viewport */
  overscan?: number;
}

/**
 * ScrollableBox provides virtualized scrolling for large lists.
 *
 * Features:
 * - Renders only visible items plus overscan buffer
 * - Keyboard navigation: Page Up/Down, Arrow Up/Down, Home/End
 * - Auto-scroll to bottom for chat-like interfaces
 * - Visual scroll indicators showing position
 */
export const ScrollableBox = memo(function ScrollableBox({
  theme,
  itemCount,
  itemHeight = 1,
  maxHeight,
  renderItem,
  focused = false,
  onScroll,
  autoScrollToBottom = true,
  showScrollIndicators = true,
  overscan = 2,
}: ScrollableBoxProps) {
  const [scrollTop, setScrollTop] = useState(0);
  const [userScrolled, setUserScrolled] = useState(false);

  // Calculate visible range
  const visibleItems = Math.floor(maxHeight / itemHeight);
  const maxScrollTop = Math.max(0, itemCount - visibleItems);

  // Calculate which items to render (with overscan)
  const startIndex = Math.max(0, scrollTop - overscan);
  const endIndex = Math.min(itemCount, scrollTop + visibleItems + overscan);

  // Auto-scroll to bottom when new items are added (if user hasn't manually scrolled)
  useEffect(() => {
    if (autoScrollToBottom && !userScrolled) {
      const newScrollTop = Math.max(0, itemCount - visibleItems);
      setScrollTop(newScrollTop);
      onScroll?.(newScrollTop);
    }
  }, [itemCount, autoScrollToBottom, userScrolled, visibleItems, onScroll]);

  // Reset user scroll flag when scrolled to bottom
  useEffect(() => {
    if (scrollTop >= maxScrollTop) {
      setUserScrolled(false);
    }
  }, [scrollTop, maxScrollTop]);

  // Handle keyboard navigation
  const handleScroll = useCallback(
    (delta: number) => {
      setUserScrolled(true);
      setScrollTop((prev) => {
        const newValue = Math.max(0, Math.min(maxScrollTop, prev + delta));
        onScroll?.(newValue);
        return newValue;
      });
    },
    [maxScrollTop, onScroll],
  );

  useInput(
    (input, key) => {
      if (!focused) return;

      // Page Up/Down
      if (key.pageUp) {
        handleScroll(-visibleItems);
        return;
      }
      if (key.pageDown) {
        handleScroll(visibleItems);
        return;
      }

      // Arrow Up/Down
      if (key.upArrow) {
        handleScroll(-1);
        return;
      }
      if (key.downArrow) {
        handleScroll(1);
        return;
      }

      // Home (Ctrl+Home or 'g' for go-to-top like vim)
      if ((key.ctrl && input === 'g') || input === 'g') {
        setUserScrolled(true);
        setScrollTop(0);
        onScroll?.(0);
        return;
      }
      // End (Ctrl+G or 'G' for go-to-bottom like vim)
      if ((key.ctrl && input === 'G') || (key.shift && input === 'G')) {
        setUserScrolled(false);
        setScrollTop(maxScrollTop);
        onScroll?.(maxScrollTop);
        return;
      }
    },
    { isActive: focused },
  );

  // Calculate scroll indicator position
  const scrollPercentage = maxScrollTop > 0 ? scrollTop / maxScrollTop : 1;
  const indicatorPosition = Math.round(scrollPercentage * (visibleItems - 1));

  // Items hidden above/below
  const hiddenAbove = scrollTop;
  const hiddenBelow = Math.max(0, itemCount - scrollTop - visibleItems);

  // Render items
  const items: ReactNode[] = [];
  for (let i = startIndex; i < endIndex; i++) {
    items.push(
      <Box key={i} flexDirection="column">
        {renderItem(i)}
      </Box>,
    );
  }

  return (
    <Box flexDirection="column">
      {/* Scroll indicator - items above */}
      {showScrollIndicators && hiddenAbove > 0 && (
        <Box justifyContent="center" marginBottom={0}>
          <Text color={theme.colors.textMuted}>
            --- {hiddenAbove} more above (Page Up to scroll) ---
          </Text>
        </Box>
      )}

      {/* Main content area */}
      <Box flexDirection="row">
        {/* Items */}
        <Box flexDirection="column" flexGrow={1}>
          {items.length === 0 ? <Text color={theme.colors.textMuted}>No items</Text> : items}
        </Box>

        {/* Scrollbar track */}
        {showScrollIndicators && itemCount > visibleItems && (
          <Box flexDirection="column" marginLeft={1} width={1}>
            {Array.from({ length: visibleItems }).map((_, i) => (
              <Text
                key={i}
                color={i === indicatorPosition ? theme.colors.primary : theme.colors.border}
              >
                {i === indicatorPosition ? '█' : '│'}
              </Text>
            ))}
          </Box>
        )}
      </Box>

      {/* Scroll indicator - items below */}
      {showScrollIndicators && hiddenBelow > 0 && (
        <Box justifyContent="center" marginTop={0}>
          <Text color={theme.colors.textMuted}>
            --- {hiddenBelow} more below (Page Down to scroll) ---
          </Text>
        </Box>
      )}
    </Box>
  );
});

export default ScrollableBox;
