/**
 * Lesson 17: Consensus Protocols
 *
 * Implements different strategies for reaching agreement
 * among multiple agents with potentially conflicting opinions.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The conflict resolution logic is crucial for multi-agent systems.
 * You could implement:
 * - Custom voting schemes (ranked choice, approval voting)
 * - Debate simulation with rebuttals
 * - Learning-based consensus weights
 */

import type {
  Opinion,
  Decision,
  VoteResult,
  ConsensusStrategy,
  Agent,
  AgentRole,
} from './types.js';

// =============================================================================
// CONSENSUS ENGINE
// =============================================================================

/**
 * Reaches consensus among agents using configurable strategies.
 */
export class ConsensusEngine {
  private strategy: ConsensusStrategy;
  private maxDebateRounds: number;

  constructor(
    strategy: ConsensusStrategy = 'authority',
    maxDebateRounds = 3
  ) {
    this.strategy = strategy;
    this.maxDebateRounds = maxDebateRounds;
  }

  /**
   * Reach a decision from multiple opinions.
   */
  async decide(
    opinions: Opinion[],
    agents: Agent[]
  ): Promise<Decision> {
    if (opinions.length === 0) {
      throw new Error('Cannot reach consensus with no opinions');
    }

    // If all opinions agree, return immediately
    if (this.isUnanimous(opinions)) {
      return this.createDecision(
        opinions[0].position,
        this.strategy,
        opinions,
        1.0,
        []
      );
    }

    // Apply strategy
    switch (this.strategy) {
      case 'authority':
        return this.decideByAuthority(opinions, agents);

      case 'voting':
        return this.decideByVoting(opinions);

      case 'unanimous':
        return this.decideUnanimous(opinions);

      case 'debate':
        return this.decideByDebate(opinions, agents);

      case 'weighted':
        return this.decideByWeightedVote(opinions, agents);

      default:
        return this.decideByAuthority(opinions, agents);
    }
  }

  // ===========================================================================
  // CONSENSUS STRATEGIES
  // ===========================================================================

  /**
   * Highest authority agent decides.
   */
  private async decideByAuthority(
    opinions: Opinion[],
    agents: Agent[]
  ): Promise<Decision> {
    // Find opinion from highest authority agent
    let highestAuthority = -1;
    let decidingOpinion: Opinion | null = null;

    for (const opinion of opinions) {
      const agent = agents.find((a) => a.id === opinion.agentId);
      if (agent && agent.role.authority > highestAuthority) {
        highestAuthority = agent.role.authority;
        decidingOpinion = opinion;
      }
    }

    if (!decidingOpinion) {
      // Fallback to first opinion if no authority found
      decidingOpinion = opinions[0];
    }

    const dissent = opinions.filter(
      (o) => o.position !== decidingOpinion!.position
    );

    return this.createDecision(
      decidingOpinion.position,
      'authority',
      opinions,
      decidingOpinion.confidence,
      dissent
    );
  }

  /**
   * Majority vote decides.
   */
  private async decideByVoting(opinions: Opinion[]): Promise<Decision> {
    const voteResult = this.countVotes(opinions);

    const supportingOpinions = opinions.filter(
      (o) => o.position === voteResult.winner
    );
    const dissent = opinions.filter(
      (o) => o.position !== voteResult.winner
    );

    // Calculate support as weighted average confidence
    const support = supportingOpinions.length > 0
      ? supportingOpinions.reduce((sum, o) => sum + o.confidence, 0) /
        supportingOpinions.length
      : 0;

    return this.createDecision(
      voteResult.winner,
      'voting',
      opinions,
      support * voteResult.supportPercentage,
      dissent
    );
  }

  /**
   * Require unanimous agreement (or fail).
   */
  private async decideUnanimous(opinions: Opinion[]): Promise<Decision> {
    if (this.isUnanimous(opinions)) {
      return this.createDecision(
        opinions[0].position,
        'unanimous',
        opinions,
        1.0,
        []
      );
    }

    // No consensus - return with low support
    const voteResult = this.countVotes(opinions);
    const dissent = opinions.filter(
      (o) => o.position !== voteResult.winner
    );

    return this.createDecision(
      voteResult.winner,
      'unanimous',
      opinions,
      0, // Zero support means no consensus
      dissent
    );
  }

  /**
   * Debate until agreement (or max rounds).
   */
  private async decideByDebate(
    opinions: Opinion[],
    agents: Agent[]
  ): Promise<Decision> {
    let currentOpinions = [...opinions];
    let round = 0;

    while (round < this.maxDebateRounds && !this.isUnanimous(currentOpinions)) {
      round++;

      // Simulate debate: agents can update their opinions based on others
      currentOpinions = this.simulateDebateRound(currentOpinions, agents);
    }

    // After debate, decide by weighted vote
    return this.decideByWeightedVote(currentOpinions, agents);
  }

  /**
   * Weighted vote by confidence and authority.
   *
   * USER CONTRIBUTION OPPORTUNITY:
   * Implement custom weighting logic here. Consider:
   * - Past accuracy of each agent
   * - Task-specific expertise weights
   * - Dynamic weight adjustment based on evidence
   */
  private async decideByWeightedVote(
    opinions: Opinion[],
    agents: Agent[]
  ): Promise<Decision> {
    // Calculate weighted scores for each position
    const scores = new Map<string, number>();

    for (const opinion of opinions) {
      const agent = agents.find((a) => a.id === opinion.agentId);
      const authority = agent?.role.authority ?? 1;

      // Weight = confidence × authority
      const weight = opinion.confidence * (authority / 5);

      const currentScore = scores.get(opinion.position) || 0;
      scores.set(opinion.position, currentScore + weight);
    }

    // Find highest scored position
    let winner = opinions[0].position;
    let highestScore = 0;
    let totalScore = 0;

    for (const [position, score] of scores) {
      totalScore += score;
      if (score > highestScore) {
        highestScore = score;
        winner = position;
      }
    }

    const support = totalScore > 0 ? highestScore / totalScore : 0;
    const dissent = opinions.filter((o) => o.position !== winner);

    return this.createDecision(winner, 'weighted', opinions, support, dissent);
  }

  // ===========================================================================
  // VOTING HELPERS
  // ===========================================================================

  /**
   * Count votes for each position.
   */
  countVotes(opinions: Opinion[]): VoteResult {
    const votes = new Map<string, string[]>();
    const options: string[] = [];

    for (const opinion of opinions) {
      if (!votes.has(opinion.position)) {
        votes.set(opinion.position, []);
        options.push(opinion.position);
      }
      votes.get(opinion.position)!.push(opinion.agentId);
    }

    // Find winner
    let winner = options[0];
    let maxVotes = 0;

    for (const [position, voters] of votes) {
      if (voters.length > maxVotes) {
        maxVotes = voters.length;
        winner = position;
      }
    }

    return {
      options,
      votes,
      winner,
      unanimous: options.length === 1,
      supportPercentage: opinions.length > 0 ? maxVotes / opinions.length : 0,
    };
  }

  /**
   * Check if all opinions agree.
   */
  isUnanimous(opinions: Opinion[]): boolean {
    if (opinions.length === 0) return true;
    const firstPosition = opinions[0].position;
    return opinions.every((o) => o.position === firstPosition);
  }

  /**
   * Simulate a debate round.
   * In a real system, this would involve LLM calls for each agent
   * to potentially update their opinion based on others' reasoning.
   */
  private simulateDebateRound(
    opinions: Opinion[],
    agents: Agent[]
  ): Opinion[] {
    const updated: Opinion[] = [];

    for (const opinion of opinions) {
      const agent = agents.find((a) => a.id === opinion.agentId);
      const otherOpinions = opinions.filter((o) => o.agentId !== opinion.agentId);

      // Simple simulation: lower confidence agents may change their mind
      // if higher confidence agents disagree
      const higherConfidenceDisagreement = otherOpinions.filter(
        (o) => o.position !== opinion.position && o.confidence > opinion.confidence
      );

      if (higherConfidenceDisagreement.length > 0 && opinion.confidence < 0.7) {
        // Agent might change opinion
        const strongestOpposition = higherConfidenceDisagreement.reduce(
          (strongest, current) =>
            current.confidence > strongest.confidence ? current : strongest
        );

        // 30% chance to switch if opposition is significantly more confident
        if (strongestOpposition.confidence - opinion.confidence > 0.2) {
          updated.push({
            ...opinion,
            position: strongestOpposition.position,
            confidence: opinion.confidence + 0.1,
            reasoning: `After considering ${strongestOpposition.agentId}'s reasoning: ${strongestOpposition.reasoning}`,
          });
          continue;
        }
      }

      // Otherwise, slightly increase confidence in own position
      updated.push({
        ...opinion,
        confidence: Math.min(1, opinion.confidence + 0.05),
      });
    }

    return updated;
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  /**
   * Create a decision object.
   */
  private createDecision(
    decision: string,
    method: ConsensusStrategy,
    opinions: Opinion[],
    support: number,
    dissent: Opinion[]
  ): Decision {
    return {
      decision,
      method,
      opinions,
      support: Math.max(0, Math.min(1, support)),
      dissent,
      timestamp: new Date(),
    };
  }

  /**
   * Get current strategy.
   */
  getStrategy(): ConsensusStrategy {
    return this.strategy;
  }

  /**
   * Set strategy.
   */
  setStrategy(strategy: ConsensusStrategy): void {
    this.strategy = strategy;
  }
}

// =============================================================================
// OPINION BUILDERS
// =============================================================================

/**
 * Create an opinion.
 */
export function createOpinion(
  agentId: string,
  position: string,
  reasoning: string,
  confidence: number,
  evidence?: string[]
): Opinion {
  return {
    agentId,
    position,
    reasoning,
    confidence: Math.max(0, Math.min(1, confidence)),
    evidence,
  };
}

// =============================================================================
// ANALYSIS UTILITIES
// =============================================================================

/**
 * Analyze decision quality.
 */
export function analyzeDecision(decision: Decision): {
  consensus: 'strong' | 'moderate' | 'weak' | 'none';
  dissentLevel: 'none' | 'low' | 'moderate' | 'high';
  recommendations: string[];
} {
  const dissentRatio = decision.dissent.length / decision.opinions.length;

  let consensus: 'strong' | 'moderate' | 'weak' | 'none';
  if (decision.support >= 0.9) consensus = 'strong';
  else if (decision.support >= 0.7) consensus = 'moderate';
  else if (decision.support >= 0.5) consensus = 'weak';
  else consensus = 'none';

  let dissentLevel: 'none' | 'low' | 'moderate' | 'high';
  if (dissentRatio === 0) dissentLevel = 'none';
  else if (dissentRatio < 0.25) dissentLevel = 'low';
  else if (dissentRatio < 0.5) dissentLevel = 'moderate';
  else dissentLevel = 'high';

  const recommendations: string[] = [];

  if (consensus === 'weak' || consensus === 'none') {
    recommendations.push('Consider additional debate rounds');
    recommendations.push('Review dissenting opinions for valid concerns');
  }

  if (dissentLevel === 'high') {
    recommendations.push('Address dissenting viewpoints before proceeding');
  }

  if (decision.method === 'authority' && dissentLevel !== 'none') {
    recommendations.push('Consider switching to voting or debate for more buy-in');
  }

  return { consensus, dissentLevel, recommendations };
}

/**
 * Format decision for display.
 */
export function formatDecision(decision: Decision): string {
  const lines: string[] = [];

  lines.push(`Decision: ${decision.decision}`);
  lines.push(`Method: ${decision.method}`);
  lines.push(`Support: ${(decision.support * 100).toFixed(0)}%`);

  if (decision.dissent.length > 0) {
    lines.push(`Dissent: ${decision.dissent.length} agent(s)`);
    for (const d of decision.dissent) {
      lines.push(`  - ${d.agentId}: ${d.position} (${(d.confidence * 100).toFixed(0)}% confidence)`);
    }
  }

  return lines.join('\n');
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createConsensusEngine(
  strategy: ConsensusStrategy = 'authority',
  maxDebateRounds = 3
): ConsensusEngine {
  return new ConsensusEngine(strategy, maxDebateRounds);
}
