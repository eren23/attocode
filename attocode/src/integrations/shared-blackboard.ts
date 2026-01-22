/**
 * Shared Blackboard Integration
 *
 * Implements the Blackboard pattern for subagent coordination.
 * Enables real-time knowledge sharing between parallel agents without
 * tight coupling.
 *
 * Key features:
 * - Finding posting: Agents share discoveries as they work
 * - Topic subscriptions: Agents subscribe to relevant findings
 * - Resource claiming: Prevent file edit conflicts
 * - Deduplication: Avoid researching what another agent already found
 * - Query interface: Search findings by topic, agent, or content
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * A finding posted to the blackboard by an agent.
 */
export interface Finding {
  /** Unique identifier */
  id: string;
  /** Agent that posted this finding */
  agentId: string;
  /** Topic/category of the finding */
  topic: string;
  /** The actual content/discovery */
  content: string;
  /** Confidence level (0-1) */
  confidence: number;
  /** Type of finding */
  type: FindingType;
  /** Related file paths */
  relatedFiles?: string[];
  /** Related symbols/identifiers */
  relatedSymbols?: string[];
  /** Tags for filtering */
  tags?: string[];
  /** Timestamp */
  timestamp: Date;
  /** Whether this supersedes a previous finding */
  supersedesId?: string;
  /** Metadata */
  metadata?: Record<string, unknown>;
}

export type FindingType =
  | 'discovery'      // Found something interesting
  | 'analysis'       // Analysis/interpretation
  | 'solution'       // Proposed solution
  | 'problem'        // Identified problem
  | 'question'       // Question for other agents
  | 'answer'         // Answer to a question
  | 'progress'       // Progress update
  | 'blocker'        // Blocked on something
  | 'resource';      // Resource location/information

/**
 * A resource claim on the blackboard.
 */
export interface ResourceClaim {
  /** Resource identifier (file path, API endpoint, etc.) */
  resource: string;
  /** Agent that claimed it */
  agentId: string;
  /** Type of claim */
  type: ClaimType;
  /** When the claim was made */
  claimedAt: Date;
  /** When the claim expires */
  expiresAt: Date;
  /** Optional description of intent */
  intent?: string;
}

export type ClaimType =
  | 'read'        // Reading the resource
  | 'write'       // Writing/modifying the resource
  | 'exclusive';  // Exclusive access

/**
 * Subscription to findings.
 */
export interface Subscription {
  /** Unique subscription ID */
  id: string;
  /** Agent that subscribed */
  agentId: string;
  /** Topic filter (supports wildcards) */
  topicPattern?: string;
  /** Type filter */
  types?: FindingType[];
  /** Tag filter */
  tags?: string[];
  /** Callback when matching finding arrives */
  callback: (finding: Finding) => void;
  /** Created timestamp */
  createdAt: Date;
}

/**
 * Filter for querying findings.
 */
export interface FindingFilter {
  /** Filter by agent ID */
  agentId?: string;
  /** Filter by topic (supports wildcards) */
  topic?: string;
  /** Filter by types */
  types?: FindingType[];
  /** Filter by tags (any match) */
  tags?: string[];
  /** Filter by minimum confidence */
  minConfidence?: number;
  /** Filter by time range */
  since?: Date;
  /** Filter by related files */
  relatedFiles?: string[];
  /** Search in content */
  contentSearch?: string;
  /** Maximum results */
  limit?: number;
}

/**
 * Configuration for the blackboard.
 */
export interface BlackboardConfig {
  /** Maximum findings to store */
  maxFindings?: number;
  /** Default claim expiry in milliseconds */
  defaultClaimTTL?: number;
  /** Enable finding deduplication */
  deduplicateFindings?: boolean;
  /** Similarity threshold for deduplication (0-1) */
  deduplicationThreshold?: number;
  /** Enable persistence to file */
  persistToFile?: boolean;
  /** Persistence file path */
  persistencePath?: string;
}

/**
 * Events emitted by the blackboard.
 */
export type BlackboardEvent =
  | { type: 'finding.posted'; finding: Finding }
  | { type: 'finding.updated'; finding: Finding }
  | { type: 'finding.superseded'; oldId: string; newId: string }
  | { type: 'claim.acquired'; claim: ResourceClaim }
  | { type: 'claim.released'; resource: string; agentId: string }
  | { type: 'claim.expired'; claim: ResourceClaim }
  | { type: 'claim.conflict'; resource: string; existingAgent: string; requestingAgent: string }
  | { type: 'subscription.matched'; subscriptionId: string; findingId: string };

export type BlackboardEventListener = (event: BlackboardEvent) => void;

/**
 * Blackboard statistics.
 */
export interface BlackboardStats {
  totalFindings: number;
  findingsByType: Map<FindingType, number>;
  findingsByAgent: Map<string, number>;
  activeClaims: number;
  activeSubscriptions: number;
  duplicatesAvoided: number;
}

// =============================================================================
// SHARED BLACKBOARD
// =============================================================================

/**
 * Shared blackboard for subagent coordination.
 *
 * @example
 * ```typescript
 * const blackboard = createSharedBlackboard();
 *
 * // Agent A posts a finding
 * blackboard.post('agent-a', {
 *   topic: 'authentication',
 *   content: 'Found JWT implementation in src/auth/jwt.ts',
 *   type: 'discovery',
 *   confidence: 0.9,
 *   relatedFiles: ['src/auth/jwt.ts'],
 * });
 *
 * // Agent B subscribes to authentication findings
 * blackboard.subscribe({
 *   agentId: 'agent-b',
 *   topicPattern: 'auth*',
 *   callback: (finding) => {
 *     console.log('Got finding:', finding.content);
 *   },
 * });
 *
 * // Agent A claims a file for editing
 * const claimed = blackboard.claim('src/auth/jwt.ts', 'agent-a', 'write');
 * if (claimed) {
 *   // Safe to edit
 * }
 * ```
 */
export class SharedBlackboard {
  private config: Required<BlackboardConfig>;
  private findings: Map<string, Finding> = new Map();
  private claims: Map<string, ResourceClaim> = new Map();
  private subscriptions: Map<string, Subscription> = new Map();
  private listeners: BlackboardEventListener[] = [];
  private duplicatesAvoided = 0;
  private findingCounter = 0;
  private subscriptionCounter = 0;

  constructor(config: BlackboardConfig = {}) {
    this.config = {
      maxFindings: config.maxFindings ?? 1000,
      defaultClaimTTL: config.defaultClaimTTL ?? 60000, // 1 minute
      deduplicateFindings: config.deduplicateFindings ?? true,
      deduplicationThreshold: config.deduplicationThreshold ?? 0.85,
      persistToFile: config.persistToFile ?? false,
      persistencePath: config.persistencePath ?? '.blackboard.json',
    };

    // Start claim expiry checker
    this.startClaimExpiryChecker();
  }

  // ===========================================================================
  // FINDINGS
  // ===========================================================================

  /**
   * Post a finding to the blackboard.
   */
  post(
    agentId: string,
    input: Omit<Finding, 'id' | 'agentId' | 'timestamp'>
  ): Finding {
    // Check for duplicates
    if (this.config.deduplicateFindings) {
      const duplicate = this.findDuplicate(input);
      if (duplicate) {
        this.duplicatesAvoided++;
        return duplicate;
      }
    }

    const finding: Finding = {
      ...input,
      id: `finding-${++this.findingCounter}-${Date.now()}`,
      agentId,
      timestamp: new Date(),
    };

    // Handle supersession
    if (finding.supersedesId) {
      this.emit({
        type: 'finding.superseded',
        oldId: finding.supersedesId,
        newId: finding.id,
      });
    }

    // Enforce max findings
    if (this.findings.size >= this.config.maxFindings) {
      this.evictOldestFinding();
    }

    this.findings.set(finding.id, finding);
    this.emit({ type: 'finding.posted', finding });

    // Notify subscribers
    this.notifySubscribers(finding);

    return finding;
  }

  /**
   * Update an existing finding.
   */
  update(findingId: string, updates: Partial<Omit<Finding, 'id' | 'agentId' | 'timestamp'>>): Finding | null {
    const existing = this.findings.get(findingId);
    if (!existing) return null;

    const updated: Finding = {
      ...existing,
      ...updates,
    };

    this.findings.set(findingId, updated);
    this.emit({ type: 'finding.updated', finding: updated });

    return updated;
  }

  /**
   * Get a finding by ID.
   */
  getFinding(id: string): Finding | undefined {
    return this.findings.get(id);
  }

  /**
   * Query findings with filters.
   */
  query(filter: FindingFilter = {}): Finding[] {
    let results = Array.from(this.findings.values());

    // Apply filters
    if (filter.agentId) {
      results = results.filter((f) => f.agentId === filter.agentId);
    }

    if (filter.topic) {
      const pattern = this.topicToRegex(filter.topic);
      results = results.filter((f) => pattern.test(f.topic));
    }

    if (filter.types && filter.types.length > 0) {
      results = results.filter((f) => filter.types!.includes(f.type));
    }

    if (filter.tags && filter.tags.length > 0) {
      results = results.filter((f) =>
        f.tags?.some((tag) => filter.tags!.includes(tag))
      );
    }

    if (filter.minConfidence !== undefined) {
      results = results.filter((f) => f.confidence >= filter.minConfidence!);
    }

    if (filter.since) {
      results = results.filter((f) => f.timestamp >= filter.since!);
    }

    if (filter.relatedFiles && filter.relatedFiles.length > 0) {
      results = results.filter((f) =>
        f.relatedFiles?.some((file) => filter.relatedFiles!.includes(file))
      );
    }

    if (filter.contentSearch) {
      const searchLower = filter.contentSearch.toLowerCase();
      results = results.filter((f) =>
        f.content.toLowerCase().includes(searchLower)
      );
    }

    // Sort by timestamp (newest first)
    results.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());

    // Apply limit
    if (filter.limit) {
      results = results.slice(0, filter.limit);
    }

    return results;
  }

  /**
   * Get all findings.
   */
  getAllFindings(): Finding[] {
    return Array.from(this.findings.values());
  }

  /**
   * Get findings by topic.
   */
  getByTopic(topic: string): Finding[] {
    return this.query({ topic });
  }

  /**
   * Get findings by agent.
   */
  getByAgent(agentId: string): Finding[] {
    return this.query({ agentId });
  }

  /**
   * Check if a finding similar to the input already exists.
   */
  private findDuplicate(
    input: Omit<Finding, 'id' | 'agentId' | 'timestamp'>
  ): Finding | null {
    for (const existing of this.findings.values()) {
      if (existing.topic === input.topic && existing.type === input.type) {
        const similarity = this.calculateSimilarity(existing.content, input.content);
        if (similarity >= this.config.deduplicationThreshold) {
          return existing;
        }
      }
    }
    return null;
  }

  /**
   * Calculate content similarity (simple Jaccard index).
   */
  private calculateSimilarity(a: string, b: string): number {
    const wordsA = new Set(a.toLowerCase().split(/\s+/));
    const wordsB = new Set(b.toLowerCase().split(/\s+/));

    const intersection = new Set([...wordsA].filter((x) => wordsB.has(x)));
    const union = new Set([...wordsA, ...wordsB]);

    return intersection.size / union.size;
  }

  /**
   * Evict the oldest finding.
   */
  private evictOldestFinding(): void {
    let oldest: Finding | null = null;
    let oldestTime = Infinity;

    for (const finding of this.findings.values()) {
      const time = finding.timestamp.getTime();
      if (time < oldestTime) {
        oldestTime = time;
        oldest = finding;
      }
    }

    if (oldest) {
      this.findings.delete(oldest.id);
    }
  }

  // ===========================================================================
  // SUBSCRIPTIONS
  // ===========================================================================

  /**
   * Subscribe to findings matching a pattern.
   */
  subscribe(options: Omit<Subscription, 'id' | 'createdAt'>): string {
    const subscription: Subscription = {
      ...options,
      id: `sub-${++this.subscriptionCounter}-${Date.now()}`,
      createdAt: new Date(),
    };

    this.subscriptions.set(subscription.id, subscription);
    return subscription.id;
  }

  /**
   * Unsubscribe from findings.
   */
  unsubscribe(subscriptionId: string): boolean {
    return this.subscriptions.delete(subscriptionId);
  }

  /**
   * Unsubscribe all subscriptions for an agent.
   */
  unsubscribeAgent(agentId: string): number {
    let count = 0;
    for (const [id, sub] of this.subscriptions) {
      if (sub.agentId === agentId) {
        this.subscriptions.delete(id);
        count++;
      }
    }
    return count;
  }

  /**
   * Notify matching subscribers of a new finding.
   */
  private notifySubscribers(finding: Finding): void {
    for (const [id, sub] of this.subscriptions) {
      if (this.matchesSubscription(finding, sub)) {
        try {
          sub.callback(finding);
          this.emit({
            type: 'subscription.matched',
            subscriptionId: id,
            findingId: finding.id,
          });
        } catch {
          // Ignore callback errors
        }
      }
    }
  }

  /**
   * Check if a finding matches a subscription.
   */
  private matchesSubscription(finding: Finding, sub: Subscription): boolean {
    // Don't notify the posting agent
    if (finding.agentId === sub.agentId) {
      return false;
    }

    // Check topic pattern
    if (sub.topicPattern) {
      const pattern = this.topicToRegex(sub.topicPattern);
      if (!pattern.test(finding.topic)) {
        return false;
      }
    }

    // Check types
    if (sub.types && sub.types.length > 0) {
      if (!sub.types.includes(finding.type)) {
        return false;
      }
    }

    // Check tags
    if (sub.tags && sub.tags.length > 0) {
      if (!finding.tags?.some((tag) => sub.tags!.includes(tag))) {
        return false;
      }
    }

    return true;
  }

  /**
   * Convert a topic pattern to a regex.
   */
  private topicToRegex(pattern: string): RegExp {
    const escaped = pattern
      .replace(/[.+^${}()|[\]\\]/g, '\\$&')
      .replace(/\*/g, '.*')
      .replace(/\?/g, '.');
    return new RegExp(`^${escaped}$`, 'i');
  }

  // ===========================================================================
  // RESOURCE CLAIMS
  // ===========================================================================

  /**
   * Claim a resource for exclusive or shared access.
   */
  claim(
    resource: string,
    agentId: string,
    type: ClaimType,
    options: { ttl?: number; intent?: string } = {}
  ): boolean {
    const existing = this.claims.get(resource);

    // Check for conflicts
    if (existing) {
      // Same agent can upgrade/extend claim
      if (existing.agentId === agentId) {
        const newClaim: ResourceClaim = {
          resource,
          agentId,
          type,
          claimedAt: existing.claimedAt,
          expiresAt: new Date(Date.now() + (options.ttl ?? this.config.defaultClaimTTL)),
          intent: options.intent,
        };
        this.claims.set(resource, newClaim);
        return true;
      }

      // Check if claims are compatible
      if (existing.type === 'exclusive' || type === 'exclusive' || type === 'write') {
        this.emit({
          type: 'claim.conflict',
          resource,
          existingAgent: existing.agentId,
          requestingAgent: agentId,
        });
        return false;
      }

      // Read claims are compatible with other read claims
      if (existing.type === 'read' && type === 'read') {
        // Allow multiple read claims - but track the latest
        // In a full implementation, we'd track multiple claims
      }
    }

    const claim: ResourceClaim = {
      resource,
      agentId,
      type,
      claimedAt: new Date(),
      expiresAt: new Date(Date.now() + (options.ttl ?? this.config.defaultClaimTTL)),
      intent: options.intent,
    };

    this.claims.set(resource, claim);
    this.emit({ type: 'claim.acquired', claim });

    return true;
  }

  /**
   * Release a resource claim.
   */
  release(resource: string, agentId: string): boolean {
    const existing = this.claims.get(resource);

    if (!existing || existing.agentId !== agentId) {
      return false;
    }

    this.claims.delete(resource);
    this.emit({ type: 'claim.released', resource, agentId });

    return true;
  }

  /**
   * Release all claims for an agent.
   */
  releaseAll(agentId: string): number {
    let count = 0;
    for (const [resource, claim] of this.claims) {
      if (claim.agentId === agentId) {
        this.claims.delete(resource);
        this.emit({ type: 'claim.released', resource, agentId });
        count++;
      }
    }
    return count;
  }

  /**
   * Check if a resource is claimed.
   */
  isClaimed(resource: string): boolean {
    const claim = this.claims.get(resource);
    if (!claim) return false;

    // Check expiry
    if (claim.expiresAt < new Date()) {
      this.claims.delete(resource);
      this.emit({ type: 'claim.expired', claim });
      return false;
    }

    return true;
  }

  /**
   * Get the claim on a resource.
   */
  getClaim(resource: string): ResourceClaim | undefined {
    const claim = this.claims.get(resource);
    if (!claim) return undefined;

    // Check expiry
    if (claim.expiresAt < new Date()) {
      this.claims.delete(resource);
      this.emit({ type: 'claim.expired', claim });
      return undefined;
    }

    return claim;
  }

  /**
   * Get all claims by an agent.
   */
  getAgentClaims(agentId: string): ResourceClaim[] {
    const claims: ResourceClaim[] = [];
    const now = new Date();

    for (const claim of this.claims.values()) {
      if (claim.agentId === agentId) {
        if (claim.expiresAt < now) {
          this.claims.delete(claim.resource);
          this.emit({ type: 'claim.expired', claim });
        } else {
          claims.push(claim);
        }
      }
    }

    return claims;
  }

  /**
   * Start periodic claim expiry checking.
   */
  private startClaimExpiryChecker(): void {
    setInterval(() => {
      const now = new Date();
      for (const [resource, claim] of this.claims) {
        if (claim.expiresAt < now) {
          this.claims.delete(resource);
          this.emit({ type: 'claim.expired', claim });
        }
      }
    }, 10000); // Check every 10 seconds
  }

  // ===========================================================================
  // COORDINATION HELPERS
  // ===========================================================================

  /**
   * Check if an agent has already researched a topic.
   */
  hasResearched(topic: string, options: { minConfidence?: number } = {}): boolean {
    const findings = this.query({
      topic,
      types: ['discovery', 'analysis'],
      minConfidence: options.minConfidence ?? 0.7,
    });
    return findings.length > 0;
  }

  /**
   * Get the best finding for a topic.
   */
  getBestFinding(topic: string): Finding | undefined {
    const findings = this.query({ topic });
    if (findings.length === 0) return undefined;

    // Return highest confidence
    return findings.reduce((best, current) =>
      current.confidence > best.confidence ? current : best
    );
  }

  /**
   * Ask a question to other agents.
   */
  askQuestion(
    agentId: string,
    topic: string,
    question: string,
    tags?: string[]
  ): Finding {
    return this.post(agentId, {
      topic,
      content: question,
      type: 'question',
      confidence: 1,
      tags,
    });
  }

  /**
   * Answer a question.
   */
  answerQuestion(
    agentId: string,
    questionId: string,
    answer: string,
    confidence: number
  ): Finding {
    const question = this.getFinding(questionId);
    if (!question) {
      throw new Error(`Question ${questionId} not found`);
    }

    return this.post(agentId, {
      topic: question.topic,
      content: answer,
      type: 'answer',
      confidence,
      tags: question.tags,
      metadata: { answersQuestionId: questionId },
    });
  }

  /**
   * Report a blocker.
   */
  reportBlocker(
    agentId: string,
    topic: string,
    description: string,
    relatedFiles?: string[]
  ): Finding {
    return this.post(agentId, {
      topic,
      content: description,
      type: 'blocker',
      confidence: 1,
      relatedFiles,
    });
  }

  /**
   * Report progress.
   */
  reportProgress(
    agentId: string,
    topic: string,
    description: string,
    metadata?: Record<string, unknown>
  ): Finding {
    return this.post(agentId, {
      topic,
      content: description,
      type: 'progress',
      confidence: 1,
      metadata,
    });
  }

  // ===========================================================================
  // STATISTICS & UTILITIES
  // ===========================================================================

  /**
   * Get blackboard statistics.
   */
  getStats(): BlackboardStats {
    const findingsByType = new Map<FindingType, number>();
    const findingsByAgent = new Map<string, number>();

    for (const finding of this.findings.values()) {
      findingsByType.set(
        finding.type,
        (findingsByType.get(finding.type) ?? 0) + 1
      );
      findingsByAgent.set(
        finding.agentId,
        (findingsByAgent.get(finding.agentId) ?? 0) + 1
      );
    }

    return {
      totalFindings: this.findings.size,
      findingsByType,
      findingsByAgent,
      activeClaims: this.claims.size,
      activeSubscriptions: this.subscriptions.size,
      duplicatesAvoided: this.duplicatesAvoided,
    };
  }

  /**
   * Generate a summary of the blackboard state.
   */
  summarize(): string {
    const stats = this.getStats();
    const lines: string[] = [
      `Blackboard Summary`,
      `==================`,
      `Total findings: ${stats.totalFindings}`,
      `Active claims: ${stats.activeClaims}`,
      `Active subscriptions: ${stats.activeSubscriptions}`,
      `Duplicates avoided: ${stats.duplicatesAvoided}`,
      ``,
      `Findings by type:`,
    ];

    for (const [type, count] of stats.findingsByType) {
      lines.push(`  - ${type}: ${count}`);
    }

    lines.push(``, `Findings by agent:`);
    for (const [agent, count] of stats.findingsByAgent) {
      lines.push(`  - ${agent}: ${count}`);
    }

    // Recent findings
    const recent = this.query({ limit: 5 });
    if (recent.length > 0) {
      lines.push(``, `Recent findings:`);
      for (const f of recent) {
        lines.push(`  - [${f.type}] ${f.topic}: ${f.content.slice(0, 50)}...`);
      }
    }

    return lines.join('\n');
  }

  /**
   * Clear all data.
   */
  clear(): void {
    this.findings.clear();
    this.claims.clear();
    this.subscriptions.clear();
    this.duplicatesAvoided = 0;
  }

  /**
   * Clear findings only (keep claims and subscriptions).
   */
  clearFindings(): void {
    this.findings.clear();
    this.duplicatesAvoided = 0;
  }

  /**
   * Subscribe to blackboard events.
   */
  on(listener: BlackboardEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  private emit(event: BlackboardEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a shared blackboard.
 *
 * @example
 * ```typescript
 * // Create blackboard for a multi-agent task
 * const blackboard = createSharedBlackboard({
 *   maxFindings: 500,
 *   deduplicateFindings: true,
 * });
 *
 * // Agent A posts discovery
 * blackboard.post('agent-a', {
 *   topic: 'database.schema',
 *   content: 'Found User table with columns: id, email, password_hash',
 *   type: 'discovery',
 *   confidence: 0.95,
 *   relatedFiles: ['migrations/001_users.sql'],
 * });
 *
 * // Agent B subscribes to database findings
 * blackboard.subscribe({
 *   agentId: 'agent-b',
 *   topicPattern: 'database.*',
 *   callback: (finding) => {
 *     // Use the finding in context
 *   },
 * });
 *
 * // Agent A claims a file for editing
 * if (blackboard.claim('src/models/user.ts', 'agent-a', 'write')) {
 *   // Safe to edit
 *   // ... make changes ...
 *   blackboard.release('src/models/user.ts', 'agent-a');
 * }
 * ```
 */
export function createSharedBlackboard(
  config: BlackboardConfig = {}
): SharedBlackboard {
  return new SharedBlackboard(config);
}

/**
 * Create a context-aware finding from agent output.
 */
export function createFindingFromOutput(
  _agentId: string,
  output: string,
  options: {
    topic: string;
    type?: FindingType;
    confidence?: number;
    relatedFiles?: string[];
  }
): Omit<Finding, 'id' | 'agentId' | 'timestamp'> {
  return {
    topic: options.topic,
    content: output,
    type: options.type ?? 'analysis',
    confidence: options.confidence ?? 0.8,
    relatedFiles: options.relatedFiles,
  };
}

/**
 * Extract key findings from a text summary.
 */
export function extractFindings(
  text: string,
  topic: string
): Array<Omit<Finding, 'id' | 'agentId' | 'timestamp'>> {
  const findings: Array<Omit<Finding, 'id' | 'agentId' | 'timestamp'>> = [];

  // Look for bullet points or numbered items
  const lines = text.split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.match(/^[-*•]\s+/) || trimmed.match(/^\d+\.\s+/)) {
      const content = trimmed.replace(/^[-*•\d.]+\s+/, '');
      if (content.length > 10) {
        findings.push({
          topic,
          content,
          type: 'discovery',
          confidence: 0.7,
        });
      }
    }
  }

  return findings;
}
