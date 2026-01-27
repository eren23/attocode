/**
 * Lesson 21: Human-in-the-Loop Types
 *
 * Types for approval workflows, escalation policies,
 * audit logging, and rollback capabilities.
 */

// =============================================================================
// RISK LEVELS
// =============================================================================

/**
 * Risk level classification.
 */
export type RiskLevel = 'none' | 'low' | 'medium' | 'high' | 'critical';

/**
 * Risk assessment result.
 */
export interface RiskAssessment {
  level: RiskLevel;
  score: number; // 0-100
  factors: RiskFactor[];
  recommendation: 'auto_approve' | 'require_approval' | 'block';
}

/**
 * Factor contributing to risk.
 */
export interface RiskFactor {
  name: string;
  weight: number;
  description: string;
}

// =============================================================================
// APPROVAL TYPES
// =============================================================================

/**
 * Action pending approval.
 */
export interface PendingAction {
  /** Unique identifier */
  id: string;

  /** Type of action */
  type: ActionType;

  /** Action description */
  description: string;

  /** Detailed action data */
  data: ActionData;

  /** Risk assessment */
  risk: RiskAssessment;

  /** Context for decision-making */
  context: ActionContext;

  /** When the action was requested */
  requestedAt: Date;

  /** Timeout for approval */
  timeout?: number;

  /** Who/what to escalate to */
  escalateTo?: string;

  /** Current status */
  status: ApprovalStatus;

  /** Approval result (if decided) */
  result?: ApprovalResult;
}

/**
 * Types of actions that may require approval.
 */
export type ActionType =
  | 'file_write'
  | 'file_delete'
  | 'command_execute'
  | 'network_request'
  | 'database_modify'
  | 'config_change'
  | 'deployment'
  | 'user_data_access'
  | 'external_api_call'
  | 'system_modification';

/**
 * Action-specific data.
 */
export type ActionData =
  | { type: 'file_write'; path: string; content: string; overwrite: boolean }
  | { type: 'file_delete'; path: string; recursive: boolean }
  | { type: 'command_execute'; command: string; args: string[]; cwd: string }
  | { type: 'network_request'; url: string; method: string; headers?: Record<string, string> }
  | { type: 'database_modify'; query: string; params: unknown[]; database: string }
  | { type: 'config_change'; key: string; oldValue: unknown; newValue: unknown }
  | { type: 'deployment'; environment: string; version: string; services: string[] }
  | { type: 'user_data_access'; userId: string; dataType: string; purpose: string }
  | { type: 'external_api_call'; service: string; endpoint: string; data: unknown }
  | { type: 'system_modification'; target: string; operation: string; details: unknown };

/**
 * Context for the action.
 */
export interface ActionContext {
  /** Session or conversation ID */
  sessionId: string;

  /** User or agent making the request */
  requestor: string;

  /** Why this action is being taken */
  reason: string;

  /** Related actions in the workflow */
  relatedActions?: string[];

  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Approval status.
 */
export type ApprovalStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'expired'
  | 'escalated'
  | 'auto_approved'
  | 'auto_rejected';

/**
 * Approval decision result.
 */
export interface ApprovalResult {
  decision: 'approved' | 'rejected';
  decidedBy: string;
  decidedAt: Date;
  reason?: string;
  conditions?: string[];
  modifiedAction?: Partial<ActionData>;
}

// =============================================================================
// APPROVAL REQUEST
// =============================================================================

/**
 * Request for approval.
 */
export interface ApprovalRequest {
  /** Action requiring approval */
  action: PendingAction;

  /** Urgency level */
  urgency: 'low' | 'normal' | 'high' | 'critical';

  /** Notification channels */
  notifyChannels?: string[];

  /** Alternative actions if rejected */
  alternatives?: AlternativeAction[];
}

/**
 * Alternative action suggestion.
 */
export interface AlternativeAction {
  description: string;
  data: ActionData;
  risk: RiskLevel;
}

// =============================================================================
// APPROVAL POLICY
// =============================================================================

/**
 * Policy for automatic approval decisions.
 */
export interface ApprovalPolicy {
  /** Policy name */
  name: string;

  /** Risk threshold for auto-approval */
  autoApproveThreshold: RiskLevel;

  /** Risk threshold for auto-rejection */
  autoRejectThreshold: RiskLevel;

  /** Patterns that are always approved */
  allowPatterns: ApprovalPattern[];

  /** Patterns that always require approval */
  requirePatterns: ApprovalPattern[];

  /** Patterns that are always blocked */
  blockPatterns: ApprovalPattern[];

  /** Escalation rules */
  escalationRules: EscalationRule[];

  /** Default timeout in milliseconds */
  defaultTimeout: number;
}

/**
 * Pattern for matching actions.
 */
export interface ApprovalPattern {
  /** Pattern name */
  name: string;

  /** Action type to match */
  actionType?: ActionType;

  /** Path pattern (glob) */
  pathPattern?: string;

  /** Command pattern (regex) */
  commandPattern?: string;

  /** Custom matcher function */
  matcher?: (action: PendingAction) => boolean;
}

// =============================================================================
// ESCALATION
// =============================================================================

/**
 * Rule for escalating approval requests.
 */
export interface EscalationRule {
  /** Rule name */
  name: string;

  /** When to trigger escalation */
  trigger: EscalationTrigger;

  /** Who to escalate to */
  escalateTo: string;

  /** How to notify */
  notificationMethod: NotificationMethod;

  /** Priority level */
  priority: number;
}

/**
 * Conditions that trigger escalation.
 */
export type EscalationTrigger =
  | { type: 'timeout'; durationMs: number }
  | { type: 'risk_level'; minLevel: RiskLevel }
  | { type: 'action_type'; types: ActionType[] }
  | { type: 'repeated_rejection'; count: number; windowMs: number }
  | { type: 'custom'; condition: (action: PendingAction) => boolean };

/**
 * How to notify on escalation.
 */
export type NotificationMethod =
  | { type: 'console' }
  | { type: 'email'; address: string }
  | { type: 'slack'; channel: string; webhook?: string }
  | { type: 'webhook'; url: string }
  | { type: 'callback'; handler: (action: PendingAction) => void };

// =============================================================================
// AUDIT LOG
// =============================================================================

/**
 * Audit log entry.
 */
export interface AuditEntry {
  /** Unique entry ID */
  id: string;

  /** Timestamp */
  timestamp: Date;

  /** Type of event */
  eventType: AuditEventType;

  /** Actor who performed the action */
  actor: AuditActor;

  /** Action that was taken */
  action: AuditAction;

  /** Outcome of the action */
  outcome: AuditOutcome;

  /** Whether this action can be rolled back */
  reversible: boolean;

  /** Data needed to rollback */
  rollbackData?: RollbackData;

  /** Related entries */
  relatedEntries?: string[];

  /** Session context */
  sessionId?: string;

  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Type of audit event.
 */
export type AuditEventType =
  | 'action_requested'
  | 'action_approved'
  | 'action_rejected'
  | 'action_executed'
  | 'action_failed'
  | 'action_rolled_back'
  | 'escalation_triggered'
  | 'policy_applied'
  | 'session_started'
  | 'session_ended';

/**
 * Actor in an audit entry.
 */
export interface AuditActor {
  type: 'human' | 'agent' | 'system' | 'policy';
  id: string;
  name?: string;
}

/**
 * Action in an audit entry.
 */
export interface AuditAction {
  type: ActionType;
  description: string;
  data: Record<string, unknown>;
}

/**
 * Outcome of an action.
 */
export interface AuditOutcome {
  success: boolean;
  message?: string;
  error?: string;
  duration?: number;
}

// =============================================================================
// ROLLBACK
// =============================================================================

/**
 * Data needed to rollback an action.
 */
export type RollbackData =
  | { type: 'file_restore'; path: string; originalContent: string | null }
  | { type: 'command_undo'; undoCommand: string }
  | { type: 'database_restore'; query: string; params: unknown[] }
  | { type: 'config_restore'; key: string; previousValue: unknown }
  | { type: 'custom'; handler: () => Promise<void>; description: string };

/**
 * Rollback request.
 */
export interface RollbackRequest {
  /** Entry to rollback */
  entryId: string;

  /** Reason for rollback */
  reason: string;

  /** Who requested the rollback */
  requestedBy: string;
}

/**
 * Rollback result.
 */
export interface RollbackResult {
  success: boolean;
  entryId: string;
  message: string;
  newEntryId?: string; // Audit entry for the rollback itself
}

// =============================================================================
// APPROVAL WORKFLOW
// =============================================================================

/**
 * Approval workflow interface.
 */
export interface ApprovalWorkflow {
  /** Request approval for an action */
  requestApproval(request: ApprovalRequest): Promise<PendingAction>;

  /** Process a pending action (approve/reject) */
  processAction(actionId: string, result: ApprovalResult): Promise<void>;

  /** Get pending actions */
  getPendingActions(): PendingAction[];

  /** Get action by ID */
  getAction(actionId: string): PendingAction | undefined;

  /** Cancel a pending action */
  cancelAction(actionId: string, reason: string): Promise<void>;

  /** Apply policy to an action */
  applyPolicy(action: PendingAction): Promise<ApprovalStatus>;
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Human-in-loop events.
 */
export type HILEvent =
  | { type: 'approval.requested'; action: PendingAction }
  | { type: 'approval.decided'; action: PendingAction; result: ApprovalResult }
  | { type: 'approval.expired'; action: PendingAction }
  | { type: 'approval.escalated'; action: PendingAction; escalateTo: string }
  | { type: 'action.executed'; action: PendingAction; outcome: AuditOutcome }
  | { type: 'action.rolled_back'; entry: AuditEntry; result: RollbackResult }
  | { type: 'policy.matched'; action: PendingAction; pattern: ApprovalPattern };

export type HILEventListener = (event: HILEvent) => void;

// =============================================================================
// HELPER TYPES
// =============================================================================

/**
 * Generate unique ID.
 */
export function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Default approval policy.
 */
export const DEFAULT_POLICY: ApprovalPolicy = {
  name: 'default',
  autoApproveThreshold: 'low',
  autoRejectThreshold: 'critical',
  allowPatterns: [],
  requirePatterns: [],
  blockPatterns: [],
  escalationRules: [],
  defaultTimeout: 300000, // 5 minutes
};
