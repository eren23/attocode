/**
 * Dashboard State Hook
 *
 * Manages all state for the TUI dashboard mode using a reducer pattern.
 * Handles tab navigation, session selection, comparison mode, search,
 * scroll positions, and mode toggling between chat and dashboard views.
 */

import { useReducer, useCallback } from 'react';

export type DashboardTab = 'live' | 'sessions' | 'detail' | 'compare' | 'swarm' | 'topology';
export type DetailSubTab = 'summary' | 'timeline' | 'tree' | 'tokens' | 'issues';

export interface DashboardState {
  mode: 'chat' | 'dashboard';
  activeTab: DashboardTab;
  selectedSessionId: string | null;
  detailSubTab: DetailSubTab;
  compareIds: [string | null, string | null];
  searchQuery: string;
  scrollPositions: Record<string, number>;
  focusedPane: string | null;
}

type DashboardAction =
  | { type: 'TOGGLE_MODE' }
  | { type: 'SET_TAB'; tab: DashboardTab }
  | { type: 'SELECT_SESSION'; sessionId: string }
  | { type: 'SET_DETAIL_SUB_TAB'; subTab: DetailSubTab }
  | { type: 'SET_COMPARE_A'; sessionId: string }
  | { type: 'SET_COMPARE_B'; sessionId: string }
  | { type: 'SET_SEARCH'; query: string }
  | { type: 'SCROLL'; pane: string; position: number }
  | { type: 'GO_BACK' }
  | { type: 'RESET' };

const initialState: DashboardState = {
  mode: 'chat',
  activeTab: 'live',
  selectedSessionId: null,
  detailSubTab: 'summary',
  compareIds: [null, null],
  searchQuery: '',
  scrollPositions: {},
  focusedPane: null,
};

function dashboardReducer(state: DashboardState, action: DashboardAction): DashboardState {
  switch (action.type) {
    case 'TOGGLE_MODE':
      return { ...state, mode: state.mode === 'chat' ? 'dashboard' : 'chat' };
    case 'SET_TAB':
      return { ...state, activeTab: action.tab };
    case 'SELECT_SESSION':
      return { ...state, selectedSessionId: action.sessionId, activeTab: 'detail', detailSubTab: 'summary' };
    case 'SET_DETAIL_SUB_TAB':
      return { ...state, detailSubTab: action.subTab };
    case 'SET_COMPARE_A':
      return { ...state, compareIds: [action.sessionId, state.compareIds[1]] };
    case 'SET_COMPARE_B':
      return { ...state, compareIds: [state.compareIds[0], action.sessionId] };
    case 'SET_SEARCH':
      return { ...state, searchQuery: action.query };
    case 'SCROLL':
      return { ...state, scrollPositions: { ...state.scrollPositions, [action.pane]: action.position } };
    case 'GO_BACK':
      if (state.activeTab === 'detail') return { ...state, activeTab: 'sessions', selectedSessionId: null };
      return { ...state, mode: 'chat' };
    case 'RESET':
      return initialState;
    default:
      return state;
  }
}

/**
 * Hook for managing dashboard navigation and UI state.
 *
 * @example
 * ```tsx
 * const { state, toggleMode, setTab, selectSession } = useDashboardState();
 *
 * // Toggle between chat and dashboard
 * toggleMode();
 *
 * // Navigate to a session detail
 * selectSession('session-abc-123');
 *
 * // Switch detail sub-tab
 * setDetailSubTab('tokens');
 * ```
 */
export function useDashboardState() {
  const [state, dispatch] = useReducer(dashboardReducer, initialState);

  const toggleMode = useCallback(() => dispatch({ type: 'TOGGLE_MODE' }), []);
  const setTab = useCallback((tab: DashboardTab) => dispatch({ type: 'SET_TAB', tab }), []);
  const selectSession = useCallback((sessionId: string) => dispatch({ type: 'SELECT_SESSION', sessionId }), []);
  const setDetailSubTab = useCallback((subTab: DetailSubTab) => dispatch({ type: 'SET_DETAIL_SUB_TAB', subTab }), []);
  const setCompareA = useCallback((sessionId: string) => dispatch({ type: 'SET_COMPARE_A', sessionId }), []);
  const setCompareB = useCallback((sessionId: string) => dispatch({ type: 'SET_COMPARE_B', sessionId }), []);
  const setSearch = useCallback((query: string) => dispatch({ type: 'SET_SEARCH', query }), []);
  const goBack = useCallback(() => dispatch({ type: 'GO_BACK' }), []);

  return {
    state,
    dispatch,
    toggleMode,
    setTab,
    selectSession,
    setDetailSubTab,
    setCompareA,
    setCompareB,
    setSearch,
    goBack,
  };
}
