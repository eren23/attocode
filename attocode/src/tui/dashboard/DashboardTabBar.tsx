import { Box, Text } from 'ink';
import React from 'react';

export type DashboardTab = 'live' | 'sessions' | 'detail' | 'compare' | 'swarm' | 'topology';

interface DashboardTabBarProps {
  activeTab: DashboardTab;
  onTabChange: (tab: DashboardTab) => void;
}

const TABS: Array<{ key: DashboardTab; label: string; shortcut: string }> = [
  { key: 'live', label: 'Live', shortcut: '1' },
  { key: 'sessions', label: 'Sessions', shortcut: '2' },
  { key: 'detail', label: 'Detail', shortcut: '3' },
  { key: 'compare', label: 'Compare', shortcut: '4' },
  { key: 'swarm', label: 'Swarm', shortcut: '5' },
  { key: 'topology', label: 'Topology', shortcut: '6' },
];

export function DashboardTabBar({ activeTab, onTabChange }: DashboardTabBarProps): React.ReactElement {
  return (
    <Box borderStyle="single" borderBottom={false} paddingX={1}>
      {TABS.map((tab, i) => (
        <React.Fragment key={tab.key}>
          {i > 0 && <Text> </Text>}
          <Text
            color={activeTab === tab.key ? 'blue' : undefined}
            bold={activeTab === tab.key}
            inverse={activeTab === tab.key}
          >
            {` ${tab.shortcut}:${tab.label} `}
          </Text>
        </React.Fragment>
      ))}
    </Box>
  );
}
