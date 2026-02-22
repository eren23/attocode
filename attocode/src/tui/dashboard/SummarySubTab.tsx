import { Box, Text } from 'ink';
import React from 'react';
import type { SessionDetailData } from '../hooks/use-session-detail.js';

interface SummarySubTabProps {
  data: SessionDetailData;
}

export function SummarySubTab({ data }: SummarySubTabProps): React.ReactElement {
  if (!data.summary) return <Text dimColor>No summary data available</Text>;

  const sections = Array.isArray(data.summary) ? data.summary : data.summary.sections || [data.summary];

  return (
    <Box flexDirection="column">
      {sections.map((section: any, sIdx: number) => (
        <Box key={sIdx} flexDirection="column" marginBottom={1}>
          {section.title && <Text bold underline>{section.title}</Text>}
          {(section.items || []).map((item: any, iIdx: number) => (
            <Box key={iIdx}>
              <Text>{(item.label + ':').padEnd(25)}</Text>
              <Text
                color={item.status === 'good' ? 'green' : item.status === 'warn' ? 'yellow' : item.status === 'bad' ? 'red' : undefined}
                bold={item.status === 'bad'}
              >
                {String(item.value)}
              </Text>
            </Box>
          ))}
        </Box>
      ))}
    </Box>
  );
}
