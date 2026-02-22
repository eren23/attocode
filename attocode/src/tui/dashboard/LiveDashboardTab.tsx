import { Box, Text } from 'ink';
import React from 'react';
import { SparkLine, BarChart, PercentBar } from './viz/index.js';
import type { LiveDashboardData } from '../hooks/use-live-trace.js';
import { SeverityBadge } from './viz/index.js';

interface LiveDashboardTabProps {
  data: LiveDashboardData;
}

export function LiveDashboardTab({ data }: LiveDashboardTabProps): React.ReactElement {
  const tokenData = data.iterations.map(it => it.inputTokens + it.outputTokens);
  const cacheData = data.cacheHitRates.map(r => r * 100);

  // Top-10 tool frequency
  const toolItems = Array.from(data.toolFrequency.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name, count]) => ({ label: name, value: count, color: 'cyan' as const }));

  const elapsed = data.startTime
    ? `${((Date.now() - data.startTime.getTime()) / 1000).toFixed(0)}s`
    : '--';

  return (
    <Box flexDirection="column" paddingX={1}>
      {/* Header metrics */}
      <Box marginBottom={1}>
        <Box marginRight={3}>
          <Text bold>Iterations: </Text>
          <Text color="cyan">{data.iterations.length}</Text>
        </Box>
        <Box marginRight={3}>
          <Text bold>Tokens: </Text>
          <Text color="yellow">{data.cumulativeTokens.toLocaleString()}</Text>
        </Box>
        <Box marginRight={3}>
          <Text bold>Cost: </Text>
          <Text color="green">${data.cumulativeCost.toFixed(4)}</Text>
        </Box>
        <Box marginRight={3}>
          <Text bold>Elapsed: </Text>
          <Text>{elapsed}</Text>
        </Box>
        <Box>
          <Text bold>Status: </Text>
          <Text color={data.isRunning ? 'green' : 'gray'}>{data.isRunning ? 'RUNNING' : 'IDLE'}</Text>
        </Box>
      </Box>

      <Box>
        {/* Left column: Charts */}
        <Box flexDirection="column" width="60%">
          <Box marginBottom={1} flexDirection="column">
            <Text bold underline>Token Usage per Iteration</Text>
            {tokenData.length > 0 ? (
              <SparkLine data={tokenData} width={50} color="blue" />
            ) : (
              <Text dimColor>No data yet</Text>
            )}
          </Box>

          <Box marginBottom={1} flexDirection="column">
            <Text bold underline>Cache Hit Rate</Text>
            {cacheData.length > 0 ? (
              <Box flexDirection="column">
                <SparkLine data={cacheData} width={50} color="green" />
                <PercentBar percent={data.currentCacheHitRate * 100} label="Current" width={30} />
              </Box>
            ) : (
              <Text dimColor>No data yet</Text>
            )}
          </Box>

          <Box flexDirection="column">
            <Text bold underline>Tool Frequency (Top 10)</Text>
            {toolItems.length > 0 ? (
              <BarChart items={toolItems} maxWidth={30} />
            ) : (
              <Text dimColor>No tool calls yet</Text>
            )}
          </Box>
        </Box>

        {/* Right column: Issues */}
        <Box flexDirection="column" width="40%" paddingLeft={2}>
          <Text bold underline>Live Issues ({data.issues.length})</Text>
          {data.issues.length === 0 ? (
            <Text dimColor>No issues detected</Text>
          ) : (
            data.issues.slice(-10).reverse().map((issue, idx) => (
              <Box key={idx} marginTop={idx > 0 ? 0 : 0}>
                <SeverityBadge severity={issue.severity} />
                <Text> #{issue.iteration} </Text>
                <Text dimColor>{issue.message}</Text>
              </Box>
            ))
          )}
        </Box>
      </Box>
    </Box>
  );
}
