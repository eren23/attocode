/**
 * Lesson 23: Intent Classifier
 *
 * Classifies whether a tool call was deliberately requested by the user
 * or potentially hallucinated by the LLM.
 *
 * Key techniques:
 * - Keyword matching against user messages
 * - Contextual flow analysis
 * - Pattern recognition for common requests
 * - Hallucination detection signals
 */

import type {
  IntentClassification,
  IntentType,
  IntentEvidence,
  EvidenceType,
  IntentClassifierConfig,
  IntentPattern,
  ToolCallInfo,
  Message,
} from './types.js';
import { DEFAULT_INTENT_CONFIG } from './types.js';

// =============================================================================
// INTENT CLASSIFIER
// =============================================================================

/**
 * Classifies the intent behind tool calls.
 */
export class IntentClassifier {
  private config: IntentClassifierConfig;
  private classificationCounter = 0;

  constructor(config: Partial<IntentClassifierConfig> = {}) {
    this.config = { ...DEFAULT_INTENT_CONFIG, ...config };
  }

  // ===========================================================================
  // MAIN CLASSIFICATION
  // ===========================================================================

  /**
   * Classify the intent behind a tool call.
   */
  async classify(
    toolCall: ToolCallInfo,
    conversation: Message[]
  ): Promise<IntentClassification> {
    // Use custom classifier if provided
    if (this.config.customClassifier) {
      return this.config.customClassifier(toolCall, conversation);
    }

    const evidence: IntentEvidence[] = [];

    // Get recent user messages for analysis
    const recentMessages = this.getRecentUserMessages(conversation);

    // Gather evidence from different sources
    evidence.push(...this.findExplicitRequests(toolCall, recentMessages));
    evidence.push(...this.findKeywordMatches(toolCall, recentMessages));
    evidence.push(...this.analyzeContextFlow(toolCall, conversation));
    evidence.push(...this.matchPatterns(toolCall, recentMessages));
    evidence.push(...this.detectHallucinationSigns(toolCall, conversation));

    // Calculate confidence and determine type
    const { type, confidence } = this.calculateIntent(evidence);

    return {
      type,
      confidence,
      evidence,
      toolCall,
      timestamp: new Date(),
    };
  }

  /**
   * Quick check if a tool call appears deliberate.
   */
  isDeliberate(classification: IntentClassification): boolean {
    return (
      classification.type === 'deliberate' &&
      classification.confidence >= this.config.deliberateThreshold
    );
  }

  /**
   * Quick check if a tool call appears accidental.
   */
  isAccidental(classification: IntentClassification): boolean {
    return (
      classification.type === 'accidental' ||
      classification.confidence <= this.config.accidentalThreshold
    );
  }

  // ===========================================================================
  // EVIDENCE GATHERING
  // ===========================================================================

  /**
   * Find explicit requests for this tool in user messages.
   */
  private findExplicitRequests(
    toolCall: ToolCallInfo,
    messages: Message[]
  ): IntentEvidence[] {
    const evidence: IntentEvidence[] = [];
    const toolName = toolCall.name.toLowerCase();
    const toolWords = this.splitToolName(toolCall.name);

    for (const message of messages) {
      const content = message.content.toLowerCase();

      // Check for direct tool name mentions
      if (content.includes(toolName)) {
        evidence.push({
          type: 'explicit_request',
          content: `User mentioned "${toolCall.name}" directly`,
          weight: 0.9,
          source: 'user_message',
        });
      }

      // Check for tool words (e.g., "read" from "read_file")
      for (const word of toolWords) {
        if (word.length > 3 && content.includes(word)) {
          evidence.push({
            type: 'explicit_request',
            content: `User mentioned "${word}" which relates to ${toolCall.name}`,
            weight: 0.6,
            source: 'user_message',
          });
        }
      }

      // Check for action verbs that match tool semantics
      const actionVerbs = this.getToolActionVerbs(toolCall.name);
      for (const verb of actionVerbs) {
        if (content.includes(verb)) {
          evidence.push({
            type: 'explicit_request',
            content: `User used action verb "${verb}" matching tool semantics`,
            weight: 0.7,
            source: 'user_message',
          });
        }
      }
    }

    return evidence;
  }

  /**
   * Find keyword matches between tool args and user messages.
   */
  private findKeywordMatches(
    toolCall: ToolCallInfo,
    messages: Message[]
  ): IntentEvidence[] {
    const evidence: IntentEvidence[] = [];

    // Extract significant strings from tool arguments
    const argValues = this.extractArgStrings(toolCall.args);

    for (const message of messages) {
      const content = message.content.toLowerCase();

      for (const argValue of argValues) {
        // Check if argument value appears in user message
        if (content.includes(argValue.toLowerCase())) {
          evidence.push({
            type: 'keyword_match',
            content: `User mentioned "${argValue}" which is used in tool args`,
            weight: 0.8,
            source: 'argument_match',
          });
        }
      }
    }

    return evidence;
  }

  /**
   * Analyze if the tool call follows logically from conversation context.
   */
  private analyzeContextFlow(
    toolCall: ToolCallInfo,
    conversation: Message[]
  ): IntentEvidence[] {
    const evidence: IntentEvidence[] = [];

    // Find the last user message
    const lastUserMsg = [...conversation]
      .reverse()
      .find(m => m.role === 'user');

    if (!lastUserMsg) {
      evidence.push({
        type: 'context_flow',
        content: 'No user message found in context',
        weight: -0.5,
        source: 'context_analysis',
      });
      return evidence;
    }

    // Check if this is a follow-up to a previous tool call
    const previousToolCalls = this.getPreviousToolCalls(conversation);
    const isFollowUp = this.isLogicalFollowUp(toolCall, previousToolCalls);

    if (isFollowUp) {
      evidence.push({
        type: 'context_flow',
        content: 'Tool call follows logically from previous actions',
        weight: 0.6,
        source: 'context_analysis',
      });
    }

    // Check if user's request implies multi-step operation
    if (this.impliesMultiStep(lastUserMsg.content)) {
      evidence.push({
        type: 'context_flow',
        content: 'User request implies multi-step operation',
        weight: 0.4,
        source: 'context_analysis',
      });
    }

    return evidence;
  }

  /**
   * Match against known intent patterns.
   */
  private matchPatterns(
    toolCall: ToolCallInfo,
    messages: Message[]
  ): IntentEvidence[] {
    const evidence: IntentEvidence[] = [];

    for (const pattern of this.config.patterns || []) {
      // Check if tool matches pattern
      if (!pattern.tools.includes(toolCall.name)) continue;

      const combinedContent = messages.map(m => m.content).join(' ').toLowerCase();

      // Check for keyword matches
      const matchedKeywords = pattern.keywords.filter(kw =>
        combinedContent.includes(kw.toLowerCase())
      );

      if (matchedKeywords.length > 0) {
        evidence.push({
          type: 'pattern_match',
          content: `Matched pattern "${pattern.name}" with keywords: ${matchedKeywords.join(', ')}`,
          weight: pattern.confidenceBoost,
          source: 'pattern_matching',
        });
      }

      // Check argument patterns if specified
      if (pattern.argPatterns) {
        const argsMatch = Object.entries(pattern.argPatterns).every(
          ([key, valuePattern]) => {
            const argValue = String(toolCall.args[key] || '');
            return new RegExp(valuePattern, 'i').test(argValue);
          }
        );

        if (argsMatch) {
          evidence.push({
            type: 'pattern_match',
            content: `Tool arguments match pattern "${pattern.name}"`,
            weight: pattern.confidenceBoost * 0.5,
            source: 'pattern_matching',
          });
        }
      }
    }

    return evidence;
  }

  /**
   * Detect signs that the tool call might be hallucinated.
   */
  private detectHallucinationSigns(
    toolCall: ToolCallInfo,
    conversation: Message[]
  ): IntentEvidence[] {
    const evidence: IntentEvidence[] = [];

    // Check for sudden topic shift
    if (this.isSuddenTopicShift(toolCall, conversation)) {
      evidence.push({
        type: 'hallucination_sign',
        content: 'Tool call appears unrelated to conversation topic',
        weight: -0.6,
        source: 'hallucination_detection',
      });
    }

    // Check for fabricated-looking paths or values
    if (this.hasFabricatedArgs(toolCall.args)) {
      evidence.push({
        type: 'hallucination_sign',
        content: 'Tool arguments contain suspicious fabricated-looking values',
        weight: -0.7,
        source: 'hallucination_detection',
      });
    }

    // Check for repetitive patterns (sign of looping/hallucination)
    if (this.hasRepetitivePattern(toolCall, conversation)) {
      evidence.push({
        type: 'hallucination_sign',
        content: 'Tool call follows repetitive pattern',
        weight: -0.4,
        source: 'hallucination_detection',
      });
    }

    // Check if user explicitly said NOT to do something
    if (this.contradictUserIntent(toolCall, conversation)) {
      evidence.push({
        type: 'contradiction',
        content: 'Tool call appears to contradict user instructions',
        weight: -0.9,
        source: 'contradiction_detection',
      });
    }

    return evidence;
  }

  // ===========================================================================
  // INTENT CALCULATION
  // ===========================================================================

  /**
   * Calculate the final intent type and confidence from evidence.
   */
  private calculateIntent(
    evidence: IntentEvidence[]
  ): { type: IntentType; confidence: number } {
    if (evidence.length === 0) {
      return { type: 'unknown', confidence: 0.5 };
    }

    // Calculate weighted score
    let totalWeight = 0;
    let weightedSum = 0;

    for (const e of evidence) {
      const absWeight = Math.abs(e.weight);
      totalWeight += absWeight;
      // Convert weight to 0-1 scale centered at 0.5
      weightedSum += (e.weight + 1) / 2 * absWeight;
    }

    const confidence = totalWeight > 0 ? weightedSum / totalWeight : 0.5;

    // Determine type based on confidence thresholds
    let type: IntentType;
    if (confidence >= this.config.deliberateThreshold) {
      type = 'deliberate';
    } else if (confidence <= this.config.accidentalThreshold) {
      type = 'accidental';
    } else if (confidence >= 0.4 && confidence < this.config.deliberateThreshold) {
      type = 'inferred';
    } else {
      type = 'unknown';
    }

    return { type, confidence };
  }

  // ===========================================================================
  // HELPER METHODS
  // ===========================================================================

  /**
   * Get recent user messages within the context window.
   */
  private getRecentUserMessages(conversation: Message[]): Message[] {
    return conversation
      .filter(m => m.role === 'user')
      .slice(-this.config.contextWindow);
  }

  /**
   * Split tool name into component words.
   */
  private splitToolName(name: string): string[] {
    return name
      .split(/[_\-]/)
      .flatMap(word => word.split(/(?=[A-Z])/))
      .map(w => w.toLowerCase())
      .filter(w => w.length > 0);
  }

  /**
   * Get action verbs commonly associated with a tool.
   */
  private getToolActionVerbs(toolName: string): string[] {
    const verbMap: Record<string, string[]> = {
      read_file: ['read', 'show', 'display', 'view', 'open', 'get', 'look'],
      write_file: ['write', 'save', 'create', 'update', 'modify', 'change'],
      delete_file: ['delete', 'remove', 'erase', 'destroy'],
      list_files: ['list', 'show', 'find', 'search', 'browse'],
      search: ['search', 'find', 'look for', 'locate'],
      bash: ['run', 'execute', 'command', 'shell'],
      web_fetch: ['fetch', 'get', 'download', 'retrieve'],
    };

    return verbMap[toolName] || this.splitToolName(toolName);
  }

  /**
   * Extract string values from tool arguments.
   */
  private extractArgStrings(args: Record<string, unknown>): string[] {
    const strings: string[] = [];

    for (const value of Object.values(args)) {
      if (typeof value === 'string' && value.length > 2) {
        strings.push(value);
        // Also add filename/path components
        if (value.includes('/')) {
          strings.push(...value.split('/').filter(s => s.length > 2));
        }
      }
    }

    return strings;
  }

  /**
   * Get tool calls from previous assistant messages.
   */
  private getPreviousToolCalls(conversation: Message[]): ToolCallInfo[] {
    const calls: ToolCallInfo[] = [];

    for (const msg of conversation) {
      if (msg.role === 'assistant' && msg.toolCalls) {
        calls.push(...msg.toolCalls);
      }
    }

    return calls;
  }

  /**
   * Check if a tool call is a logical follow-up to previous calls.
   */
  private isLogicalFollowUp(
    toolCall: ToolCallInfo,
    previousCalls: ToolCallInfo[]
  ): boolean {
    if (previousCalls.length === 0) return false;

    // Common follow-up patterns
    const followUpPatterns: Record<string, string[]> = {
      read_file: ['write_file', 'delete_file'],
      search: ['read_file'],
      list_files: ['read_file'],
      bash: ['bash'], // Commands often chain
    };

    const lastCall = previousCalls[previousCalls.length - 1];
    const expectedFollowUps = followUpPatterns[lastCall.name] || [];

    return expectedFollowUps.includes(toolCall.name);
  }

  /**
   * Check if content implies a multi-step operation.
   */
  private impliesMultiStep(content: string): boolean {
    const multiStepIndicators = [
      'and then',
      'after that',
      'first',
      'next',
      'finally',
      'step by step',
      'also',
      'and also',
      'then',
    ];

    const lower = content.toLowerCase();
    return multiStepIndicators.some(indicator => lower.includes(indicator));
  }

  /**
   * Check if tool call represents a sudden topic shift.
   */
  private isSuddenTopicShift(
    toolCall: ToolCallInfo,
    conversation: Message[]
  ): boolean {
    // Simple heuristic: check if any arg values appear in conversation
    const argValues = this.extractArgStrings(toolCall.args);
    const conversationText = conversation
      .map(m => m.content)
      .join(' ')
      .toLowerCase();

    // If no argument values appear in conversation, might be a shift
    const anyArgInConversation = argValues.some(arg =>
      conversationText.includes(arg.toLowerCase())
    );

    return argValues.length > 0 && !anyArgInConversation;
  }

  /**
   * Check for fabricated-looking argument values.
   */
  private hasFabricatedArgs(args: Record<string, unknown>): boolean {
    const suspiciousPatterns = [
      /example\.com/i,
      /test\.txt/i,
      /foo|bar|baz/i,
      /lorem ipsum/i,
      /placeholder/i,
      /sample/i,
    ];

    for (const value of Object.values(args)) {
      if (typeof value === 'string') {
        for (const pattern of suspiciousPatterns) {
          if (pattern.test(value)) {
            return true;
          }
        }
      }
    }

    return false;
  }

  /**
   * Check for repetitive call patterns (potential infinite loop).
   */
  private hasRepetitivePattern(
    toolCall: ToolCallInfo,
    conversation: Message[]
  ): boolean {
    const previousCalls = this.getPreviousToolCalls(conversation);

    // Check if this exact call was made recently
    const recentSame = previousCalls
      .slice(-5)
      .filter(
        call =>
          call.name === toolCall.name &&
          JSON.stringify(call.args) === JSON.stringify(toolCall.args)
      );

    return recentSame.length >= 2;
  }

  /**
   * Check if tool call contradicts explicit user instructions.
   */
  private contradictUserIntent(
    toolCall: ToolCallInfo,
    conversation: Message[]
  ): boolean {
    const negativePatterns = [
      /don't\s+(\w+)/gi,
      /do not\s+(\w+)/gi,
      /never\s+(\w+)/gi,
      /stop\s+(\w+)/gi,
      /avoid\s+(\w+)/gi,
    ];

    const toolWords = this.splitToolName(toolCall.name);

    for (const msg of conversation) {
      if (msg.role !== 'user') continue;

      for (const pattern of negativePatterns) {
        const matches = msg.content.matchAll(pattern);
        for (const match of matches) {
          const forbiddenAction = match[1].toLowerCase();
          if (toolWords.includes(forbiddenAction)) {
            return true;
          }
        }
      }
    }

    return false;
  }

  // ===========================================================================
  // CONFIGURATION
  // ===========================================================================

  /**
   * Add a pattern for intent recognition.
   */
  addPattern(pattern: IntentPattern): void {
    this.config.patterns = this.config.patterns || [];
    this.config.patterns.push(pattern);
  }

  /**
   * Remove a pattern by name.
   */
  removePattern(name: string): void {
    if (this.config.patterns) {
      this.config.patterns = this.config.patterns.filter(p => p.name !== name);
    }
  }

  /**
   * Update configuration.
   */
  updateConfig(updates: Partial<IntentClassifierConfig>): void {
    this.config = { ...this.config, ...updates };
  }

  /**
   * Get current configuration.
   */
  getConfig(): IntentClassifierConfig {
    return { ...this.config };
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create an intent classifier with common patterns.
 */
export function createIntentClassifier(
  options: Partial<IntentClassifierConfig> = {}
): IntentClassifier {
  const classifier = new IntentClassifier(options);

  // Add common patterns
  classifier.addPattern({
    name: 'file_read',
    keywords: ['read', 'show', 'display', 'content', 'what is in', 'open'],
    tools: ['read_file'],
    confidenceBoost: 0.3,
  });

  classifier.addPattern({
    name: 'file_write',
    keywords: ['write', 'save', 'create', 'add', 'update', 'modify'],
    tools: ['write_file'],
    confidenceBoost: 0.3,
  });

  classifier.addPattern({
    name: 'file_delete',
    keywords: ['delete', 'remove', 'erase'],
    tools: ['delete_file'],
    confidenceBoost: 0.3,
  });

  classifier.addPattern({
    name: 'search',
    keywords: ['find', 'search', 'look for', 'where is', 'locate'],
    tools: ['search', 'list_files', 'grep'],
    confidenceBoost: 0.3,
  });

  classifier.addPattern({
    name: 'command',
    keywords: ['run', 'execute', 'command', 'terminal', 'shell'],
    tools: ['bash', 'shell', 'exec'],
    confidenceBoost: 0.3,
  });

  return classifier;
}

/**
 * Create a strict intent classifier with higher thresholds.
 */
export function createStrictClassifier(): IntentClassifier {
  return new IntentClassifier({
    deliberateThreshold: 0.85,
    accidentalThreshold: 0.4,
    contextWindow: 3,
  });
}

/**
 * Create a lenient intent classifier with lower thresholds.
 */
export function createLenientClassifier(): IntentClassifier {
  return new IntentClassifier({
    deliberateThreshold: 0.5,
    accidentalThreshold: 0.2,
    contextWindow: 10,
  });
}
