/**
 * Attocode Evaluation Framework
 *
 * Public API for programmatic usage of the evaluation system.
 */

// Core types
export type {
  EvalTask,
  EvalResult,
  EvalDataset,
  EvalRunConfig,
  EvalComparison,
  EvalSummary,
  EvalMetrics,
  EvalRunner,
  Grader,
  GradeResult,
  GraderType,
  AgentOutput,
  ExpectedResult,
  TaskMetadata,
  Reporter,
} from './types.js';

// Dataset loading
export { loadDataset, filterTasks } from './lib/dataset-loader.js';

// Runners
export { ProductionAgentRunner, createRunner } from './runners/agent-runner.js';

// Graders
export {
  grade,
  getGrader,
  registerGrader,
  ExactMatchGrader,
  TestBasedGrader,
  FileContainsGrader,
} from './graders/index.js';
