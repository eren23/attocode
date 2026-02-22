import { Box, Text } from 'ink';
import React from 'react';
import { SparkLine, BarChart } from './viz/index.js';
import type { SessionDetailData } from '../hooks/use-session-detail.js';

interface TokensSubTabProps {
  data: SessionDetailData;
}

export function TokensSubTab({ data }: TokensSubTabProps): React.ReactElement {
  if (!data.tokenFlow) return <Text dimColor>No token flow data available</Text>;

  const flow = data.tokenFlow;
  const perIteration = flow.perIteration || [];
  const costBreakdown = flow.costBreakdown || {};

  const inputTokens = perIteration.map((it: any) => it.input || 0);
  const outputTokens = perIteration.map((it: any) => it.output || 0);
  const cachedTokens = perIteration.map((it: any) => it.cached || 0);

  return (
    <Box flexDirection="column">
      <Text bold underline>Token Flow Analysis</Text>

      <Box marginTop={1} flexDirection="column">
        <Text bold>Input Tokens per Iteration:</Text>
        {inputTokens.length > 0 ? (
          <SparkLine data={inputTokens} width={60} color="blue" />
        ) : (
          <Text dimColor>No data</Text>
        )}
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text bold>Output Tokens per Iteration:</Text>
        {outputTokens.length > 0 ? (
          <SparkLine data={outputTokens} width={60} color="yellow" />
        ) : (
          <Text dimColor>No data</Text>
        )}
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text bold>Cached Tokens per Iteration:</Text>
        {cachedTokens.length > 0 ? (
          <SparkLine data={cachedTokens} width={60} color="green" />
        ) : (
          <Text dimColor>No data</Text>
        )}
      </Box>

      {/* Cost breakdown */}
      <Box marginTop={1} flexDirection="column">
        <Text bold underline>Cost Breakdown</Text>
        <BarChart
          items={[
            { label: 'Input', value: costBreakdown.inputCost || 0, color: 'blue' },
            { label: 'Output', value: costBreakdown.outputCost || 0, color: 'yellow' },
            { label: 'Cached', value: costBreakdown.cachedCost || 0, color: 'green' },
          ]}
          maxWidth={40}
        />
        <Box marginTop={1}>
          <Text bold>Total: </Text>
          <Text color="cyan">${(costBreakdown.totalCost || 0).toFixed(4)}</Text>
          <Text>  </Text>
          <Text bold>Savings: </Text>
          <Text color="green">${(costBreakdown.savings || 0).toFixed(4)}</Text>
        </Box>
      </Box>
    </Box>
  );
}
