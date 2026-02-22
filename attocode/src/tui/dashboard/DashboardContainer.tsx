import { Box } from 'ink';
import React from 'react';
import { DashboardTabBar } from './DashboardTabBar.js';
import { LiveDashboardTab } from './LiveDashboardTab.js';
import { SessionListTab } from './SessionListTab.js';
import { SessionDetailTab } from './SessionDetailTab.js';
import { CompareTab } from './CompareTab.js';
import { SwarmActivityTab } from './SwarmActivityTab.js';
import { AgentTopologyTab } from './AgentTopologyTab.js';
import type { DashboardTab, DetailSubTab, DashboardState } from '../hooks/use-dashboard-state.js';
import type { LiveDashboardData } from '../hooks/use-live-trace.js';
import type { SessionSummary } from '../hooks/use-session-browser.js';
import type { SessionDetailData } from '../hooks/use-session-detail.js';

interface DashboardContainerProps {
  state: DashboardState;
  liveData: LiveDashboardData;
  sessions: SessionSummary[];
  sessionsLoading: boolean;
  sessionDetail: SessionDetailData;
  selectedIndex: number;
  onTabChange: (tab: DashboardTab) => void;
  onSelectSession: (sessionId: string) => void;
  onDetailSubTabChange: (tab: DetailSubTab) => void;
  swarmData?: any;
  agents?: Array<{ id: string; type: string; status: string; parentId?: string; tokensUsed?: number }>;
}

export function DashboardContainer({
  state,
  liveData,
  sessions,
  sessionsLoading,
  sessionDetail,
  selectedIndex,
  onTabChange,
  onSelectSession,
  onDetailSubTabChange,
  swarmData,
  agents,
}: DashboardContainerProps): React.ReactElement {
  return (
    <Box flexDirection="column" flexGrow={1}>
      <DashboardTabBar activeTab={state.activeTab} onTabChange={onTabChange} />
      <Box flexGrow={1} flexDirection="column">
        {state.activeTab === 'live' && <LiveDashboardTab data={liveData} />}
        {state.activeTab === 'sessions' && (
          <SessionListTab
            sessions={sessions}
            loading={sessionsLoading}
            selectedIndex={selectedIndex}
            filterText={state.searchQuery}
            onSelect={onSelectSession}
          />
        )}
        {state.activeTab === 'detail' && (
          <SessionDetailTab
            data={sessionDetail}
            activeSubTab={state.detailSubTab}
            onSubTabChange={onDetailSubTabChange}
          />
        )}
        {state.activeTab === 'compare' && <CompareTab compareIds={state.compareIds} />}
        {state.activeTab === 'swarm' && <SwarmActivityTab swarmData={swarmData} />}
        {state.activeTab === 'topology' && <AgentTopologyTab agents={agents} />}
      </Box>
    </Box>
  );
}
