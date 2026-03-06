/**
 * Hierarchy Panel
 *
 * Shows the role hierarchy (Executor/Manager/Judge) with their models,
 * colors, and action counts.
 */

import { ROLE_INFO, type SwarmWorkerRole, type SwarmLiveState } from '../../lib/swarm-types';

interface HierarchyPanelProps {
  state: SwarmLiveState;
}

/** Count role.action events from the timeline */
function countRoleActions(timeline: SwarmLiveState['timeline']): Record<SwarmWorkerRole, number> {
  const counts: Record<SwarmWorkerRole, number> = { executor: 0, manager: 0, judge: 0 };
  for (const entry of timeline) {
    if (entry.type.startsWith('role.')) {
      const role = entry.type.split('.')[1] as SwarmWorkerRole;
      if (role in counts) counts[role]++;
    }
  }
  return counts;
}

export function HierarchyPanel({ state }: HierarchyPanelProps) {
  const roleCounts = countRoleActions(state.timeline);
  const hierarchy = state.config.hierarchy;
  const roles: SwarmWorkerRole[] = ['manager', 'judge', 'executor'];

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-semibold text-gray-400 mb-3">Role Hierarchy</h3>
      <div className="space-y-3">
        {roles.map((role) => {
          const info = ROLE_INFO[role];
          const count = roleCounts[role];
          const model = role === 'manager'
            ? hierarchy?.manager?.model
            : role === 'judge'
              ? hierarchy?.judge?.model
              : undefined;

          return (
            <div key={role} className="flex items-center gap-3">
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center text-sm"
                style={{ backgroundColor: info.color + '20', color: info.color }}
              >
                {info.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-white">{info.label}</span>
                  {count > 0 && (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-gray-800 text-gray-400">
                      {count} action{count !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                <div className="text-xs text-gray-500 truncate">
                  {model ? model.split('/').pop() : role === 'executor' ? `${state.config.workerModels.length} model(s)` : info.description}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
