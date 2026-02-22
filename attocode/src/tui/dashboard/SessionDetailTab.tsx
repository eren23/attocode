import { Box, Text } from 'ink';
import React from 'react';
import type { SessionDetailData } from '../hooks/use-session-detail.js';
import type { DetailSubTab } from '../hooks/use-dashboard-state.js';
import { SummarySubTab } from './SummarySubTab.js';
import { TimelineSubTab } from './TimelineSubTab.js';
import { TreeSubTab } from './TreeSubTab.js';
import { TokensSubTab } from './TokensSubTab.js';
import { IssuesSubTab } from './IssuesSubTab.js';

interface SessionDetailTabProps {
  data: SessionDetailData;
  activeSubTab: DetailSubTab;
  onSubTabChange: (tab: DetailSubTab) => void;
}

const SUB_TABS: Array<{ key: DetailSubTab; label: string; shortcut: string }> = [
  { key: 'summary', label: 'Summary', shortcut: 'a' },
  { key: 'timeline', label: 'Timeline', shortcut: 'b' },
  { key: 'tree', label: 'Tree', shortcut: 'c' },
  { key: 'tokens', label: 'Tokens', shortcut: 'd' },
  { key: 'issues', label: 'Issues', shortcut: 'e' },
];

export function SessionDetailTab({ data, activeSubTab }: SessionDetailTabProps): React.ReactElement {
  if (data.loading) {
    return <Box paddingX={1}><Text>Loading session {data.sessionId}...</Text></Box>;
  }

  if (data.error) {
    return <Box paddingX={1}><Text color="red">{data.error}</Text></Box>;
  }

  return (
    <Box flexDirection="column">
      {/* Sub-tab bar */}
      <Box paddingX={1} marginBottom={1}>
        {SUB_TABS.map((tab, i) => (
          <React.Fragment key={tab.key}>
            {i > 0 && <Text> </Text>}
            <Text
              color={activeSubTab === tab.key ? 'cyan' : undefined}
              bold={activeSubTab === tab.key}
              inverse={activeSubTab === tab.key}
            >
              {` ${tab.shortcut}:${tab.label} `}
            </Text>
          </React.Fragment>
        ))}
        <Text dimColor>  Session: {data.sessionId.slice(0, 12)}</Text>
      </Box>

      {/* Sub-tab content */}
      <Box paddingX={1}>
        {activeSubTab === 'summary' && <SummarySubTab data={data} />}
        {activeSubTab === 'timeline' && <TimelineSubTab data={data} />}
        {activeSubTab === 'tree' && <TreeSubTab data={data} />}
        {activeSubTab === 'tokens' && <TokensSubTab data={data} />}
        {activeSubTab === 'issues' && <IssuesSubTab data={data} />}
      </Box>
    </Box>
  );
}
