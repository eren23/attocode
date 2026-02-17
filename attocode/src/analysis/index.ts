/**
 * Analysis module exports
 *
 * Provides LLM-powered trace analysis capabilities.
 */

export { TraceSummaryGenerator, createTraceSummaryGenerator } from './trace-summary.js';

export {
  PROMPT_TEMPLATES,
  generateAnalysisPrompt,
  getAvailableTemplates,
  type AnalysisTemplate,
  type PromptContext,
} from './prompt-templates.js';

export {
  FeedbackLoopManager,
  createFeedbackLoopManager,
  type AnalysisRecord,
  type ProposedFix,
  type ImprovementMetric,
} from './feedback-loop.js';
