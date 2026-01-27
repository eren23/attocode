/**
 * Lesson 23: Execution Policies & Intent Classification Types
 *
 * Granular control over tool execution with policy-based decisions.
 * Inspired by Codex's approach to command safety and user intent.
 *
 * Key concepts:
 * - Three-tier policies: allow/prompt/forbidden
 * - Conditional policies based on arguments
 * - Intent classification: deliberate vs accidental
 * - Permission grants with audit trail
 */

// =============================================================================
// EXECUTION POLICY TYPES
// =============================================================================

/**
 * The three levels of execution policy.
 */
export type PolicyLevel = 'allow' | 'prompt' | 'forbidden';

/**
 * Configuration for a single tool's execution policy.
 */
export interface ToolPolicy {
  /** The base policy level for this tool */
  policy: PolicyLevel;

  /** Conditional overrides based on arguments */
  conditions?: PolicyCondition[];

  /** Require intent verification for this tool */
  requireIntent?: boolean;

  /** Risk level for audit logging */
  riskLevel?: 'low' | 'medium' | 'high' | 'critical';

  /** Human-readable reason for the policy */
  reason?: string;
}

/**
 * A condition that can override the base policy.
 * Evaluated in order - first match wins.
 */
export interface PolicyCondition {
  /** Pattern to match against arguments */
  argMatch?: ArgMatchPattern;

  /** Context conditions */
  context?: ContextCondition;

  /** The policy to apply if condition matches */
  policy: PolicyLevel;

  /** Reason for this condition */
  reason?: string;
}

/**
 * Pattern for matching tool arguments.
 */
export interface ArgMatchPattern {
  /** Match specific argument values (supports regex via string) */
  [argName: string]: string | number | boolean | RegExp | ArgPatternMatcher;
}

/**
 * Advanced argument pattern matcher.
 */
export interface ArgPatternMatcher {
  /** Match if value contains substring */
  contains?: string;

  /** Match if value starts with */
  startsWith?: string;

  /** Match if value ends with */
  endsWith?: string;

  /** Match against regex pattern */
  pattern?: string;

  /** Match if value is in list */
  oneOf?: (string | number)[];

  /** Match if value is NOT in list */
  notOneOf?: (string | number)[];

  /** Match if numeric value is in range */
  range?: { min?: number; max?: number };
}

/**
 * Context conditions for policy evaluation.
 */
export interface ContextCondition {
  /** Only applies during specific session state */
  sessionState?: 'interactive' | 'batch' | 'automated';

  /** Only applies if user has certain role */
  userRole?: string;

  /** Only applies if previous N tool calls were safe */
  safeHistoryDepth?: number;

  /** Only applies if intent confidence is above threshold */
  minIntentConfidence?: number;

  /** Custom context predicate */
  custom?: (ctx: EvaluationContext) => boolean;
}

/**
 * Complete execution policy configuration.
 */
export interface ExecutionPolicyConfig {
  /** Default policy for unlisted tools */
  defaultPolicy: PolicyLevel;

  /** Per-tool policies */
  toolPolicies: Record<string, ToolPolicy>;

  /** Enable intent classification */
  intentAware?: boolean;

  /** Intent confidence threshold for auto-allow */
  intentThreshold?: number;

  /** Enable detailed audit logging */
  auditLog?: boolean;

  /** Custom policy evaluator */
  customEvaluator?: PolicyEvaluator;
}

// =============================================================================
// INTENT CLASSIFICATION TYPES
// =============================================================================

/**
 * Classification of user intent for a tool call.
 */
export interface IntentClassification {
  /** The type of intent */
  type: IntentType;

  /** Confidence in this classification (0-1) */
  confidence: number;

  /** Evidence supporting this classification */
  evidence: IntentEvidence[];

  /** The tool call being classified */
  toolCall: ToolCallInfo;

  /** Timestamp of classification */
  timestamp: Date;
}

/**
 * Types of user intent.
 */
export type IntentType =
  | 'deliberate'   // User explicitly requested this action
  | 'inferred'     // Reasonable inference from user's request
  | 'accidental'   // Likely hallucinated or unintended by user
  | 'unknown';     // Cannot determine intent

/**
 * Evidence supporting an intent classification.
 */
export interface IntentEvidence {
  /** Type of evidence */
  type: EvidenceType;

  /** The evidence content */
  content: string;

  /** How strongly this supports the classification (-1 to 1) */
  weight: number;

  /** Source of this evidence */
  source: string;
}

/**
 * Types of evidence for intent classification.
 */
export type EvidenceType =
  | 'explicit_request'    // User directly asked for this
  | 'keyword_match'       // Keywords in user message match action
  | 'context_flow'        // Follows logically from conversation
  | 'pattern_match'       // Matches known user patterns
  | 'contradiction'       // Contradicts user's stated intent
  | 'hallucination_sign'  // Shows signs of LLM hallucination
  | 'semantic_distance';  // Semantic similarity to user request

/**
 * Information about a tool call being evaluated.
 */
export interface ToolCallInfo {
  /** Tool name */
  name: string;

  /** Tool arguments */
  args: Record<string, unknown>;

  /** The tool call ID (if available) */
  id?: string;

  /** Raw tool call from LLM */
  raw?: string;
}

/**
 * Configuration for intent classification.
 */
export interface IntentClassifierConfig {
  /** Minimum confidence to consider intent as deliberate */
  deliberateThreshold: number;

  /** Maximum confidence below which intent is accidental */
  accidentalThreshold: number;

  /** Enable semantic similarity analysis */
  useSemantic?: boolean;

  /** Recent message window for context */
  contextWindow: number;

  /** Known patterns for common intents */
  patterns?: IntentPattern[];

  /** Custom classifier function */
  customClassifier?: (
    toolCall: ToolCallInfo,
    conversation: Message[]
  ) => Promise<IntentClassification>;
}

/**
 * A pattern for recognizing specific intents.
 */
export interface IntentPattern {
  /** Pattern name */
  name: string;

  /** Keywords that indicate this intent */
  keywords: string[];

  /** Tools typically associated with this intent */
  tools: string[];

  /** Expected argument patterns */
  argPatterns?: Record<string, string>;

  /** Confidence boost when matched */
  confidenceBoost: number;
}

// =============================================================================
// PERMISSION GRANT TYPES
// =============================================================================

/**
 * A grant of permission for a tool execution.
 */
export interface PermissionGrant {
  /** Unique grant ID */
  id: string;

  /** Tool being granted permission */
  tool: string;

  /** The arguments being allowed (optional - if absent, all args allowed) */
  allowedArgs?: Record<string, unknown>;

  /** Who granted permission */
  grantedBy: PermissionGrantor;

  /** When the grant was made */
  grantedAt: Date;

  /** When the grant expires */
  expiresAt?: Date;

  /** How many times this grant can be used */
  maxUses?: number;

  /** How many times it has been used */
  usedCount: number;

  /** Reason for the grant */
  reason?: string;

  /** Intent classification that led to this grant */
  intent?: IntentClassification;
}

/**
 * Who granted a permission.
 */
export interface PermissionGrantor {
  /** Type of grantor */
  type: 'user' | 'system' | 'policy' | 'intent';

  /** Identifier (user ID, policy name, etc.) */
  id: string;

  /** Display name */
  name?: string;
}

/**
 * Store for managing permission grants.
 */
export interface PermissionStore {
  /** Add a grant */
  add(grant: PermissionGrant): void;

  /** Check if a grant exists for this tool/args */
  hasGrant(tool: string, args: Record<string, unknown>): PermissionGrant | null;

  /** Use a grant (decrements usage count) */
  useGrant(grantId: string): boolean;

  /** Revoke a grant */
  revoke(grantId: string): void;

  /** Clear expired grants */
  clearExpired(): number;

  /** Get all active grants */
  getActive(): PermissionGrant[];
}

// =============================================================================
// EVALUATION TYPES
// =============================================================================

/**
 * Context provided during policy evaluation.
 */
export interface EvaluationContext {
  /** The tool call being evaluated */
  toolCall: ToolCallInfo;

  /** Recent conversation history */
  conversation: Message[];

  /** Intent classification (if enabled) */
  intent?: IntentClassification;

  /** Existing permission grants */
  grants: PermissionGrant[];

  /** Current session info */
  session: SessionInfo;

  /** Tool call history in this session */
  toolHistory: ToolCallRecord[];

  /** Custom context data */
  metadata?: Record<string, unknown>;
}

/**
 * Minimal message interface for conversation context.
 */
export interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  toolCalls?: ToolCallInfo[];
  name?: string;
}

/**
 * Session information.
 */
export interface SessionInfo {
  /** Session ID */
  id: string;

  /** Session state */
  state: 'interactive' | 'batch' | 'automated';

  /** User info (if available) */
  user?: {
    id: string;
    role?: string;
  };

  /** Session start time */
  startedAt: Date;
}

/**
 * Record of a past tool call.
 */
export interface ToolCallRecord {
  /** Tool name */
  tool: string;

  /** Arguments used */
  args: Record<string, unknown>;

  /** Policy decision made */
  decision: PolicyDecision;

  /** When executed */
  executedAt: Date;

  /** Result (if captured) */
  result?: unknown;
}

/**
 * The result of policy evaluation.
 */
export interface PolicyDecision {
  /** Whether execution is allowed */
  allowed: boolean;

  /** The policy level that was applied */
  policy: PolicyLevel;

  /** Reason for the decision */
  reason: string;

  /** Which condition matched (if any) */
  matchedCondition?: PolicyCondition;

  /** Intent classification (if used) */
  intent?: IntentClassification;

  /** Permission grant used (if any) */
  usedGrant?: PermissionGrant;

  /** Suggested modifications to make it allowed */
  suggestions?: PolicySuggestion[];

  /** Whether user prompt is needed */
  promptRequired: boolean;

  /** Risk level of this action */
  riskLevel: 'low' | 'medium' | 'high' | 'critical';
}

/**
 * A suggestion for modifying a tool call to make it allowed.
 */
export interface PolicySuggestion {
  /** Type of suggestion */
  type: 'modify_args' | 'use_alternative' | 'add_safeguard' | 'split_operation';

  /** Description of the suggestion */
  description: string;

  /** Modified arguments (for modify_args) */
  modifiedArgs?: Record<string, unknown>;

  /** Alternative tool (for use_alternative) */
  alternativeTool?: string;
}

// =============================================================================
// POLICY EVALUATOR INTERFACE
// =============================================================================

/**
 * Interface for policy evaluators.
 */
export interface PolicyEvaluator {
  /** Evaluate a tool call against the policy */
  evaluate(
    toolCall: ToolCallInfo,
    context: EvaluationContext
  ): Promise<PolicyDecision>;

  /** Update policy configuration */
  updateConfig(config: Partial<ExecutionPolicyConfig>): void;

  /** Get current configuration */
  getConfig(): ExecutionPolicyConfig;
}

// =============================================================================
// AUDIT TYPES
// =============================================================================

/**
 * An audit log entry.
 */
export interface AuditEntry {
  /** Entry ID */
  id: string;

  /** Timestamp */
  timestamp: Date;

  /** Event type */
  event: AuditEventType;

  /** Tool involved */
  tool: string;

  /** Arguments */
  args: Record<string, unknown>;

  /** Decision made */
  decision: PolicyDecision;

  /** Who triggered this */
  actor: PermissionGrantor;

  /** Additional context */
  context?: Record<string, unknown>;
}

/**
 * Types of audit events.
 */
export type AuditEventType =
  | 'policy_evaluated'
  | 'permission_granted'
  | 'permission_denied'
  | 'permission_prompted'
  | 'intent_classified'
  | 'tool_executed'
  | 'tool_blocked';

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Events emitted by the policy system.
 */
export type PolicyEvent =
  | { type: 'policy.evaluated'; toolCall: ToolCallInfo; decision: PolicyDecision }
  | { type: 'intent.classified'; toolCall: ToolCallInfo; intent: IntentClassification }
  | { type: 'permission.granted'; grant: PermissionGrant }
  | { type: 'permission.denied'; tool: string; reason: string }
  | { type: 'permission.prompted'; tool: string; context: EvaluationContext }
  | { type: 'tool.allowed'; tool: string; decision: PolicyDecision }
  | { type: 'tool.blocked'; tool: string; decision: PolicyDecision }
  | { type: 'audit.logged'; entry: AuditEntry };

/**
 * Listener for policy events.
 */
export type PolicyEventListener = (event: PolicyEvent) => void;

// =============================================================================
// DEFAULT VALUES
// =============================================================================

/**
 * Default execution policy configuration.
 */
export const DEFAULT_POLICY_CONFIG: ExecutionPolicyConfig = {
  defaultPolicy: 'prompt',
  toolPolicies: {},
  intentAware: true,
  intentThreshold: 0.8,
  auditLog: true,
};

/**
 * Default intent classifier configuration.
 */
export const DEFAULT_INTENT_CONFIG: IntentClassifierConfig = {
  deliberateThreshold: 0.7,
  accidentalThreshold: 0.3,
  useSemantic: false,
  contextWindow: 5,
  patterns: [],
};

/**
 * Common policy presets for different tool categories.
 */
export const POLICY_PRESETS = {
  /** Read-only tools are generally safe */
  readOnly: {
    policy: 'allow' as PolicyLevel,
    riskLevel: 'low' as const,
    reason: 'Read-only operation',
  },

  /** Write operations need confirmation */
  write: {
    policy: 'prompt' as PolicyLevel,
    riskLevel: 'medium' as const,
    reason: 'Modifies data',
  },

  /** Destructive operations are forbidden by default */
  destructive: {
    policy: 'forbidden' as PolicyLevel,
    riskLevel: 'critical' as const,
    reason: 'Destructive operation',
  },

  /** Network operations need attention */
  network: {
    policy: 'prompt' as PolicyLevel,
    riskLevel: 'medium' as const,
    reason: 'Network access',
  },

  /** Shell execution needs careful handling */
  shell: {
    policy: 'prompt' as PolicyLevel,
    riskLevel: 'high' as const,
    reason: 'Shell command execution',
  },
} as const;
