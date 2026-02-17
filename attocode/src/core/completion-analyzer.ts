/**
 * Completion Analyzer
 *
 * Shared logic for identifying responses that describe future intent
 * ("I'll do X") instead of completed work. This must stay centralized so
 * execution-loop and final run guardrails classify consistently.
 */

export interface CompletionIntentAnalysis {
  isIncompleteAction: boolean;
  reason: 'none' | 'future_intent' | 'failure_admission' | 'narrative_action';
  confidence: number;
}

export function analyzeCompletionIntent(content: string): CompletionIntentAnalysis {
  const trimmed = content.trim();
  if (!trimmed) {
    return { isIncompleteAction: false, reason: 'none', confidence: 0 };
  }

  const lower = trimmed.toLowerCase();

  // Positive completion signals should override weaker future-intent cues.
  const completionSignals =
    /\b(done|completed|finished|here is the (final|complete)|created successfully|saved|wrote|all (changes|tasks) (are )?complete)\b/;
  if (completionSignals.test(lower)) {
    return { isIncompleteAction: false, reason: 'none', confidence: 0.9 };
  }

  const futureIntentPatterns: RegExp[] = [
    /\b(i\s+will|i'll|let me)\s+(create|write|save|update|modify|fix|add|edit|implement|change|run|execute|build|set up|start)\b/,
    /\b(i\s+need to|i\s+should|i\s+can)\s+(create|write|update|modify|fix|add|edit|implement)\b/,
    /\b(the next step|first[, ]+i|now i)\b/,
    /\b(i am going to|i'm going to)\b/,
  ];
  if (futureIntentPatterns.some((pattern) => pattern.test(lower))) {
    return { isIncompleteAction: true, reason: 'future_intent', confidence: 0.95 };
  }

  const failureAdmissionPatterns: RegExp[] = [
    /\bran out of budget\b/,
    /\bbudget exhausted\b/,
    /\bunable to complete\b/,
    /\bcould not complete\b/,
    /\bno changes were made\b/,
    /\bno files were modified\b/,
  ];
  if (failureAdmissionPatterns.some((pattern) => pattern.test(lower))) {
    return { isIncompleteAction: true, reason: 'failure_admission', confidence: 0.9 };
  }

  // Heuristic: short narrative about "changing code" with no artifact.
  const hasCodeBlock = /```/.test(trimmed);
  const mentionsCodeConcepts =
    /\b(file|function|class|module|component|import|export|variable|method)\b/i.test(trimmed);
  if (!hasCodeBlock && mentionsCodeConcepts && trimmed.length < 600) {
    const actionWords = /\b(update|modify|create|add|change|fix|implement|refactor|write|edit)\b/i;
    if (actionWords.test(lower)) {
      return { isIncompleteAction: true, reason: 'narrative_action', confidence: 0.65 };
    }
  }

  return { isIncompleteAction: false, reason: 'none', confidence: 0.3 };
}

export function detectIncompleteActionResponse(content: string): boolean {
  return analyzeCompletionIntent(content).isIncompleteAction;
}
