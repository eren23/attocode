/**
 * Evaluation Framework Types
 *
 * Core types for the attocode evaluation system. These define the structure
 * of evaluation tasks, results, and configuration.
 */

// =============================================================================
// TASK DEFINITIONS
// =============================================================================

/**
 * A single evaluation task that the agent will attempt to complete.
 */
export interface EvalTask {
  /** Unique identifier for this task */
  id: string;

  /** Human-readable name */
  name: string;

  /** The prompt given to the agent */
  prompt: string;

  /** Maximum time allowed for task completion (ms) */
  timeout_ms: number;

  /** Which grader to use for evaluation */
  grader: GraderType;

  /** Expected results for grading */
  expected?: ExpectedResult;

  /** Task metadata for categorization and filtering */
  metadata: TaskMetadata;

  /** Optional setup function to run before the task */
  setup?: SetupConfig;

  /** Optional teardown/cleanup function */
  teardown?: TeardownConfig;
}

export type GraderType =
  | 'exact-match'      // Exact string/file content match
  | 'test-based'       // Run tests and check pass rate
  | 'file-contains'    // Check if files contain expected content
  | 'llm-judge'        // Use LLM to evaluate quality
  | 'swe-bench'        // SWE-bench evaluation (patch generation)
  | 'custom';          // Custom grading function

export interface ExpectedResult {
  /** Expected output text (for exact-match) */
  output?: string;

  /** Files that should be modified */
  files_modified?: string[];

  /** Files that should be created */
  files_created?: string[];

  /** Content that should appear in files (path -> content) */
  file_contains?: Record<string, string | string[]>;

  /** Tests that should pass */
  tests_pass?: boolean;

  /** Specific test command to run */
  test_command?: string;

  /** Minimum partial credit score (0-1) */
  min_score?: number;

  /** For custom graders */
  custom?: Record<string, unknown>;

  /** SWE-bench specific metadata */
  swe_bench?: {
    instance_id: string;
    repo: string;
    base_commit: string;
    fail_to_pass?: string;
    pass_to_pass?: string;
  };
}

export interface TaskMetadata {
  /** Difficulty level */
  difficulty: 'easy' | 'medium' | 'hard' | 'expert';

  /** Category of the task */
  category: 'bug-fix' | 'feature' | 'refactor' | 'test' | 'docs' | 'should-fail' | 'edge-case' | 'swe-bench';

  /** Source of the task */
  source: 'golden' | 'humaneval' | 'swe-bench' | 'swe-bench-lite' | 'custom';

  /** Repository (for SWE-bench) */
  repo?: string;

  /** Version (for SWE-bench) */
  version?: string;

  /** Programming language(s) involved */
  languages?: string[];

  /** Tags for filtering */
  tags?: string[];

  /** Whether this task should fail (for negative test cases) */
  should_fail?: boolean;
}

export interface SetupConfig {
  /** Shell commands to run before the task */
  commands?: string[];

  /** Files to create before the task */
  files?: Record<string, string>;

  /** Working directory for the task */
  workdir?: string;

  /** Git operations (checkout branch, etc.) */
  git?: {
    checkout?: string;
    reset?: boolean;
  };
}

export interface TeardownConfig {
  /** Shell commands to run after the task */
  commands?: string[];

  /** Files to delete after the task */
  delete_files?: string[];

  /** Restore git state */
  git_restore?: boolean;
}

// =============================================================================
// EVALUATION RESULTS
// =============================================================================

/**
 * Result of running a single evaluation task.
 */
export interface EvalResult {
  /** Task that was evaluated */
  task_id: string;

  /** Model used for evaluation */
  model: string;

  /** Provider used (anthropic, openrouter, etc.) */
  provider: string;

  /** Whether the task succeeded */
  success: boolean;

  /** Partial credit score (0-1) */
  partial_credit: number;

  /** Detailed grading breakdown */
  grading_details?: GradingDetails;

  /** Execution metrics */
  metrics: EvalMetrics;

  /** Path to trace file for detailed debugging */
  trace_path?: string;

  /** Error message if failed */
  error?: string;

  /** Timestamp when evaluation ran */
  timestamp: string;
}

export interface GradingDetails {
  /** Tests passed vs total */
  tests?: { passed: number; total: number };

  /** Files correctly modified */
  files?: { correct: number; total: number };

  /** Content matches */
  content_matches?: { matched: number; total: number };

  /** LLM judge score */
  llm_score?: { score: number; reasoning: string };

  /** Custom grader output */
  custom?: Record<string, unknown>;
}

export interface EvalMetrics {
  /** Total tokens used */
  tokens: {
    input: number;
    output: number;
    total: number;
    cached?: number;
  };

  /** Number of agent iterations */
  iterations: number;

  /** Number of tool calls */
  tool_calls: number;

  /** Total duration in milliseconds */
  duration_ms: number;

  /** Estimated cost in USD */
  estimated_cost: number;
}

// =============================================================================
// DATASETS
// =============================================================================

/**
 * A collection of evaluation tasks.
 */
export interface EvalDataset {
  /** Dataset name */
  name: string;

  /** Dataset description */
  description: string;

  /** Version for tracking changes */
  version: string;

  /** Tasks in this dataset */
  tasks: EvalTask[];

  /** Default configuration for tasks */
  defaults?: Partial<EvalTask>;
}

// =============================================================================
// RUN CONFIGURATION
// =============================================================================

/**
 * Configuration for an evaluation run.
 */
export interface EvalRunConfig {
  /** Dataset to evaluate */
  dataset: string;

  /** Model to use */
  model: string;

  /** Provider to use */
  provider: 'anthropic' | 'openrouter' | 'openai';

  /** Maximum parallel evaluations */
  parallelism?: number;

  /** Filter tasks by difficulty */
  difficulty?: TaskMetadata['difficulty'][];

  /** Filter tasks by category */
  category?: TaskMetadata['category'][];

  /** Filter tasks by tags */
  tags?: string[];

  /** Specific task IDs to run */
  task_ids?: string[];

  /** Output directory for results */
  output_dir?: string;

  /** Enable detailed tracing */
  trace?: boolean;

  /** Use mock LLM (for testing eval framework) */
  mock_llm?: boolean;

  /** Maximum cost budget in USD */
  cost_limit?: number;

  /** Retry failed tasks */
  retry_failed?: number;
}

// =============================================================================
// COMPARISON
// =============================================================================

/**
 * Comparison between two evaluation runs.
 */
export interface EvalComparison {
  /** Baseline run results */
  baseline: {
    model: string;
    provider: string;
    results: EvalResult[];
    summary: EvalSummary;
  };

  /** Challenger run results */
  challenger: {
    model: string;
    provider: string;
    results: EvalResult[];
    summary: EvalSummary;
  };

  /** Comparison statistics */
  comparison: {
    /** Tasks where baseline performed better */
    baseline_wins: number;

    /** Tasks where challenger performed better */
    challenger_wins: number;

    /** Tasks with equal performance */
    ties: number;

    /** Cost difference (negative = challenger cheaper) */
    cost_delta: number;

    /** Speed difference (negative = challenger faster) */
    speed_delta_ms: number;

    /** Per-task breakdown */
    per_task: TaskComparison[];
  };
}

export interface TaskComparison {
  task_id: string;
  baseline_success: boolean;
  challenger_success: boolean;
  baseline_score: number;
  challenger_score: number;
  winner: 'baseline' | 'challenger' | 'tie';
}

export interface EvalSummary {
  /** Total tasks evaluated */
  total_tasks: number;

  /** Tasks that succeeded */
  passed: number;

  /** Tasks that failed */
  failed: number;

  /** Pass rate (0-1) */
  pass_rate: number;

  /** Average partial credit */
  avg_partial_credit: number;

  /** Total cost */
  total_cost: number;

  /** Total duration */
  total_duration_ms: number;

  /** By difficulty breakdown */
  by_difficulty: Record<string, { passed: number; total: number }>;

  /** By category breakdown */
  by_category: Record<string, { passed: number; total: number }>;
}

// =============================================================================
// RUNNER INTERFACE
// =============================================================================

/**
 * Interface for task runners that execute evaluations.
 */
export interface EvalRunner {
  /** Run a single task */
  runTask(task: EvalTask, config: EvalRunConfig): Promise<EvalResult>;

  /** Run all tasks in a dataset */
  runDataset(tasks: EvalTask[], config: EvalRunConfig): Promise<EvalResult[]>;

  /** Cleanup resources */
  cleanup(): Promise<void>;
}

// =============================================================================
// GRADER INTERFACE
// =============================================================================

/**
 * Interface for graders that evaluate task results.
 */
export interface Grader {
  /** Type of grader */
  type: GraderType;

  /** Grade a completed task */
  grade(
    task: EvalTask,
    agentOutput: AgentOutput,
    workdir: string
  ): Promise<GradeResult>;
}

export interface AgentOutput {
  /** Whether the agent reported success */
  success: boolean;

  /** Agent's final response */
  response: string;

  /** Files modified during execution */
  files_modified: string[];

  /** Files created during execution */
  files_created: string[];

  /** Error if failed */
  error?: string;
}

export interface GradeResult {
  /** Overall success */
  success: boolean;

  /** Partial credit (0-1) */
  partial_credit: number;

  /** Detailed breakdown */
  details?: GradingDetails;

  /** Human-readable explanation */
  explanation?: string;
}

// =============================================================================
// REPORTER INTERFACE
// =============================================================================

/**
 * Interface for reporters that output results.
 */
export interface Reporter {
  /** Report results for a single task */
  reportTask(result: EvalResult): void;

  /** Report summary for a full run */
  reportSummary(results: EvalResult[], summary: EvalSummary): void;

  /** Report comparison between runs */
  reportComparison(comparison: EvalComparison): void;

  /** Finalize and write output */
  finalize(): Promise<void>;
}
