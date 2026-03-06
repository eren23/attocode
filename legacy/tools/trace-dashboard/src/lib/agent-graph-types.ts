/**
 * Agent topology and data flow visualization types.
 * Represents agent hierarchy and data flowing between agents.
 */

export interface AgentGraphData {
  agents: AgentNode[];
  dataFlows: DataFlow[];
}

export interface AgentNode {
  id: string;
  label: string;
  model: string;
  type: 'root' | 'subagent' | 'orchestrator' | 'worker' | 'judge' | 'manager';
  status: 'running' | 'completed' | 'failed';
  parentId?: string;
  tokensUsed: number;
  costUsed: number;
  filesAccessed: string[];
  findingsPosted: number;
}

export interface DataFlow {
  id: string;
  timestamp: number;
  sourceAgentId: string;
  targetAgentId: string;
  type: DataFlowType;
  payload: {
    summary: string;
    size?: number;
    topic?: string;
    confidence?: number;
  };
}

export type DataFlowType =
  | 'finding'
  | 'file_share'
  | 'budget_transfer'
  | 'context_injection'
  | 'task_assignment'
  | 'result_return';

/** Edge style configuration for each flow type */
export const FLOW_TYPE_STYLES: Record<DataFlowType, {
  stroke: string;
  dash: string;
  color: string;
  label: string;
}> = {
  finding: { stroke: 'dashed', dash: '4,4', color: '#3b82f6', label: 'Finding' },
  file_share: { stroke: 'solid', dash: '', color: '#6b7280', label: 'File Share' },
  budget_transfer: { stroke: 'dotted', dash: '2,4', color: '#10b981', label: 'Budget' },
  context_injection: { stroke: 'solid', dash: '', color: '#8b5cf6', label: 'Context' },
  task_assignment: { stroke: 'solid', dash: '', color: '#f59e0b', label: 'Task' },
  result_return: { stroke: 'solid', dash: '', color: '#22c55e', label: 'Result' },
};

/** Blackboard snapshot from swarm-live/ */
export interface BlackboardSnapshot {
  findings: Array<{
    id: string;
    topic: string;
    type: string;
    agentId: string;
    confidence: number;
    content: string;
  }>;
  claims: Array<{
    resource: string;
    agentId: string;
    type: string;
  }>;
  updatedAt: string;
}

/** Budget pool snapshot from swarm-live/ */
export interface BudgetPoolSnapshot {
  poolTotal: number;
  poolUsed: number;
  poolRemaining: number;
  allocations: Array<{
    agentId: string;
    tokensAllocated: number;
    tokensUsed: number;
  }>;
  updatedAt: string;
}
