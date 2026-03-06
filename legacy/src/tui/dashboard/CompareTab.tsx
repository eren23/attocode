import { Box, Text } from 'ink';
import React from 'react';

interface CompareTabProps {
  compareIds: [string | null, string | null];
}

export function CompareTab({ compareIds }: CompareTabProps): React.ReactElement {
  const [idA, idB] = compareIds;

  if (!idA && !idB) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text bold>Session Comparison</Text>
        <Text dimColor>Select two sessions to compare:</Text>
        <Text dimColor>1. Go to Sessions tab</Text>
        <Text dimColor>2. Press 'c' on a session to mark it for comparison</Text>
        <Text dimColor>3. Press 'c' on another session</Text>
        <Text dimColor>4. Return to this tab to see the comparison</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold>Session Comparison</Text>
      <Box marginTop={1}>
        <Box flexDirection="column" width="50%">
          <Text bold color="blue">Session A: {idA || '(not selected)'}</Text>
        </Box>
        <Box flexDirection="column" width="50%">
          <Text bold color="green">Session B: {idB || '(not selected)'}</Text>
        </Box>
      </Box>
      {idA && idB && (
        <Text dimColor>Comparison data loading...</Text>
      )}
    </Box>
  );
}
