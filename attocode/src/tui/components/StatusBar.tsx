/**
 * StatusBar Component
 *
 * Memoized status bar with colocated state for elapsed time, context tokens,
 * and budget percentage. Extracted from TUIApp to prevent full re-renders
 * when status changes.
 *
 * Anti-flicker: Custom comparator only re-renders when values change meaningfully.
 */

import { memo, useState, useEffect, useRef } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';
import type { TransparencyState } from '../transparency-aggregator.js';
import { estimateTokenCount } from '../../integrations/utilities/token-estimate.js';

export interface StatusBarProps {
  isProcessing: boolean;
  status: { iter: number; tokens: number; cost: number; mode: string };
  colors: ThemeColors;
  model: string;
  gitBranch: string;
  transparencyState: TransparencyState | null;
  agent: {
    getState: () => { messages: Array<{ content: string | unknown }> };
    getMaxContextTokens: () => number;
    getSystemPromptTokenEstimate?: () => number;
    getBudgetUsage?: () => { percentUsed: number } | null | undefined;
    getTypeCheckerState: () => { tsconfigDir?: string | null } | null;
  };
}

// How often (ms) to recalculate context/budget (throttle expensive operations)
const CONTEXT_RECALC_INTERVAL_MS = 2000;
// Timer interval for elapsed time display
const ELAPSED_TIMER_INTERVAL_MS = 5000;
// Only show elapsed time after this many seconds
const ELAPSED_SHOW_THRESHOLD_S = 10;

export const StatusBar = memo(
  function StatusBar({
    isProcessing,
    status,
    colors,
    model,
    gitBranch,
    transparencyState,
    agent,
  }: StatusBarProps) {
    // Colocated state: these are only consumed by StatusBar
    const [elapsedTime, setElapsedTime] = useState(0);
    const [contextPct, setContextPct] = useState(0);
    const [budgetPct, setBudgetPct] = useState(0);
    const processingStartRef = useRef<number | null>(null);

    // Track elapsed time (only when processing)
    useEffect(() => {
      if (isProcessing) {
        processingStartRef.current = Date.now();
        setElapsedTime(0);
        const interval = setInterval(() => {
          if (processingStartRef.current) {
            setElapsedTime(Math.floor((Date.now() - processingStartRef.current) / 1000));
          }
        }, ELAPSED_TIMER_INTERVAL_MS);
        return () => clearInterval(interval);
      } else {
        processingStartRef.current = null;
        return undefined;
      }
    }, [isProcessing]);

    // Throttled context/budget recalculation
    useEffect(() => {
      const recalculate = () => {
        const agentState = agent.getState();
        const messageTokens = agentState.messages.reduce(
          (sum: number, m: { content: string | unknown }) =>
            sum +
            estimateTokenCount(
              typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
            ),
          0,
        );
        const systemPromptTokens = agent.getSystemPromptTokenEstimate?.() ?? 0;
        const currentContextTokens = messageTokens + systemPromptTokens;
        const contextLimit = agent.getMaxContextTokens();
        setContextPct(Math.round((currentContextTokens / contextLimit) * 100));

        const budgetUsage = agent.getBudgetUsage?.();
        if (budgetUsage) {
          setBudgetPct(Math.round(budgetUsage.percentUsed));
        }
      };

      // Recalculate immediately on mount and after token changes
      recalculate();

      // Set up throttled recalculation during processing
      if (isProcessing) {
        const interval = setInterval(recalculate, CONTEXT_RECALC_INTERVAL_MS);
        return () => clearInterval(interval);
      }
      return undefined;
    }, [agent, isProcessing, status.tokens]);

    const modelShort = (model || 'unknown').split('/').pop() || model || 'unknown';
    const costStr = status.cost > 0 ? `$${status.cost.toFixed(4)}` : '$0.00';

    return (
      <Box
        borderStyle="single"
        borderColor={isProcessing ? colors.info : colors.textMuted}
        paddingX={1}
        justifyContent="space-between"
      >
        <Box gap={1}>
          <Text color={isProcessing ? colors.info : '#98FB98'} bold={isProcessing}>
            {isProcessing ? '[~]' : '[*]'}
          </Text>
          <Text color={isProcessing ? colors.info : colors.text} bold={isProcessing}>
            {status.mode.length > 40 ? status.mode.slice(0, 37) + '...' : status.mode}
          </Text>
          {isProcessing && elapsedTime >= ELAPSED_SHOW_THRESHOLD_S && (
            <Text color={colors.textMuted} dimColor>
              | {elapsedTime}s
            </Text>
          )}
          {status.iter > 0 && (
            <Text color={colors.textMuted} dimColor>
              | iter {status.iter}
            </Text>
          )}
        </Box>
        <Box gap={2}>
          <Text color="#DDA0DD" dimColor>
            {modelShort}
          </Text>
          {/* Mini context bar: ctx:[====----] 42% */}
          <Text color={contextPct > 70 ? '#FFD700' : colors.textMuted} dimColor>
            {'ctx:[' +
              '='.repeat(Math.min(8, Math.round((contextPct / 100) * 8))) +
              '-'.repeat(Math.max(0, 8 - Math.round((contextPct / 100) * 8))) +
              '] ' +
              contextPct +
              '%'}
          </Text>
          {/* Budget health indicator */}
          {budgetPct > 0 && (
            <Text
              color={budgetPct >= 80 ? '#FF6B6B' : budgetPct >= 50 ? '#FFD700' : colors.textMuted}
              dimColor
            >
              {'bud:' + budgetPct + '%'}
            </Text>
          )}
          <Text color="#98FB98" dimColor>
            {costStr}
          </Text>
          {gitBranch && (
            <Text color="#87CEEB" dimColor>
              {gitBranch}
            </Text>
          )}
          {/* Show learnings count if any */}
          {transparencyState?.activeLearnings && transparencyState.activeLearnings.length > 0 && (
            <Text color="#87CEEB" dimColor>
              L:{transparencyState.activeLearnings.length}
            </Text>
          )}
          {/* TSC status indicator (only for TS projects) */}
          {agent.getTypeCheckerState()?.tsconfigDir &&
            (() => {
              const tscRes = transparencyState?.diagnostics?.lastTscResult;
              if (!tscRes)
                return (
                  <Text color={colors.textMuted} dimColor>
                    tsc:—
                  </Text>
                );
              if (tscRes.success)
                return (
                  <Text color="#98FB98" dimColor>
                    tsc:[ok]
                  </Text>
                );
              return (
                <Text color={colors.error} dimColor>
                  tsc:[X]{tscRes.errorCount}
                </Text>
              );
            })()}
          <Text color={colors.textMuted} dimColor>
            ^P:help
          </Text>
        </Box>
      </Box>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparator: skip re-render if nothing visually meaningful changed
    if (prevProps.isProcessing !== nextProps.isProcessing) return false;
    if (prevProps.status.mode !== nextProps.status.mode) return false;
    if (prevProps.status.iter !== nextProps.status.iter) return false;
    // Only re-render for cost changes > $0.001
    if (Math.abs(prevProps.status.cost - nextProps.status.cost) > 0.001) return false;
    // Tokens trigger context recalc internally, but skip render unless significant
    if (Math.abs(prevProps.status.tokens - nextProps.status.tokens) > 5000) return false;
    if (prevProps.gitBranch !== nextProps.gitBranch) return false;
    if (prevProps.model !== nextProps.model) return false;
    // Transparency state for learnings count and tsc
    const prevLearnings = prevProps.transparencyState?.activeLearnings?.length ?? 0;
    const nextLearnings = nextProps.transparencyState?.activeLearnings?.length ?? 0;
    if (prevLearnings !== nextLearnings) return false;
    const prevTsc = prevProps.transparencyState?.diagnostics?.lastTscResult;
    const nextTsc = nextProps.transparencyState?.diagnostics?.lastTscResult;
    if (prevTsc?.success !== nextTsc?.success || prevTsc?.errorCount !== nextTsc?.errorCount)
      return false;
    return true;
  },
);
