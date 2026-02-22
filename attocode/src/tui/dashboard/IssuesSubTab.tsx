import { Box, Text } from 'ink';
import React from 'react';
import { SeverityBadge } from './viz/index.js';
import type { SessionDetailData } from '../hooks/use-session-detail.js';

interface IssuesSubTabProps {
  data: SessionDetailData;
}

export function IssuesSubTab({ data }: IssuesSubTabProps): React.ReactElement {
  const issues = data.inefficiencies || [];

  if (issues.length === 0) {
    return (
      <Box flexDirection="column">
        <Text bold>No inefficiencies detected</Text>
        <Text color="green">This session appears to be running efficiently.</Text>
      </Box>
    );
  }

  const bySeverity = {
    critical: issues.filter((i: any) => i.severity === 'critical'),
    high: issues.filter((i: any) => i.severity === 'high'),
    medium: issues.filter((i: any) => i.severity === 'medium'),
    low: issues.filter((i: any) => i.severity === 'low'),
  };

  return (
    <Box flexDirection="column">
      <Text bold underline>Detected Inefficiencies ({issues.length})</Text>
      <Box marginBottom={1}>
        <Text color="red">{bySeverity.critical.length} critical</Text>
        <Text>  </Text>
        <Text color="redBright">{bySeverity.high.length} high</Text>
        <Text>  </Text>
        <Text color="yellow">{bySeverity.medium.length} medium</Text>
        <Text>  </Text>
        <Text color="blue">{bySeverity.low.length} low</Text>
      </Box>

      {issues.map((issue: any, idx: number) => (
        <Box key={idx} flexDirection="column" marginBottom={1}>
          <Box>
            <SeverityBadge severity={issue.severity || 'low'} />
            <Text bold> {issue.type}</Text>
          </Box>
          <Text>  {issue.description}</Text>
          {issue.evidence && <Text dimColor>  Evidence: {issue.evidence}</Text>}
          {issue.suggestedFix && <Text color="green">  Fix: {issue.suggestedFix}</Text>}
        </Box>
      ))}
    </Box>
  );
}
