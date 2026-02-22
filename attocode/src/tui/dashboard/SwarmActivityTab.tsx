import { Box, Text } from 'ink';
import React from 'react';
import { PercentBar, ASCIITable } from './viz/index.js';

interface SwarmActivityTabProps {
  swarmData?: any;
}

export function SwarmActivityTab({ swarmData }: SwarmActivityTabProps): React.ReactElement {
  if (!swarmData) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text bold>Swarm Activity</Text>
        <Text dimColor>No swarm activity detected. Start a swarm session with --swarm flag.</Text>
      </Box>
    );
  }

  const tasks = swarmData.tasks || [];
  const stats = swarmData.stats || {};

  const taskRows = tasks.slice(0, 20).map((t: any) => [
    t.id?.slice(0, 8) || '',
    String(t.wave || 0),
    t.status || 'unknown',
    t.model?.slice(0, 15) || '',
    t.description?.slice(0, 35) || '',
  ]);

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold underline>Swarm Activity</Text>

      {/* Stats summary */}
      <Box marginTop={1} marginBottom={1}>
        <Text bold>Tasks: </Text>
        <Text color="cyan">{stats.totalTasks || tasks.length}</Text>
        <Text>  </Text>
        <Text bold>Completed: </Text>
        <Text color="green">{stats.completedTasks || 0}</Text>
        <Text>  </Text>
        <Text bold>Failed: </Text>
        <Text color="red">{stats.failedTasks || 0}</Text>
        <Text>  </Text>
        <Text bold>Waves: </Text>
        <Text>{swarmData.totalWaves || 0}</Text>
      </Box>

      {/* Budget progress */}
      {swarmData.config && (
        <Box marginBottom={1} flexDirection="column">
          <Text bold>Budget Usage:</Text>
          <PercentBar
            percent={stats.totalTokens ? (stats.totalTokens / swarmData.config.totalBudget) * 100 : 0}
            label="Tokens"
            width={40}
          />
          <PercentBar
            percent={stats.totalCost ? (stats.totalCost / swarmData.config.maxCost) * 100 : 0}
            label="Cost"
            width={40}
          />
        </Box>
      )}

      {/* Task grid */}
      <ASCIITable
        headers={['ID', 'Wave', 'Status', 'Model', 'Description']}
        rows={taskRows}
        columnWidths={[8, 5, 10, 15, 35]}
      />
    </Box>
  );
}
