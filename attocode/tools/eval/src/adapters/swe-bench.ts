/**
 * SWE-bench Lite Adapter
 *
 * Loads SWE-bench Lite dataset and converts to EvalTask format.
 * Uses the official SWE-bench harness for grading.
 */

import type { EvalTask, GraderType } from '../types.js';
import { execSync, spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

// =============================================================================
// TYPES
// =============================================================================

export interface SWEBenchInstance {
  instance_id: string; // e.g., "sympy__sympy-20590"
  repo: string; // e.g., "sympy/sympy"
  base_commit: string; // commit hash before fix
  problem_statement: string; // issue description
  hints_text: string; // optional hints
  patch: string; // gold solution (for reference)
  test_patch: string; // test code added
  version: string; // repo version
  environment_setup_commit?: string;
  FAIL_TO_PASS: string; // JSON array of failing tests
  PASS_TO_PASS: string; // JSON array of passing tests
}

export interface SWEBenchPrediction {
  instance_id: string;
  model_name_or_path: string;
  model_patch: string;
}

export interface SWEBenchEvalResult {
  instance_id: string;
  status: 'resolved' | 'unresolved' | 'error' | 'timeout';
  test_results?: {
    fail_to_pass: string[];
    pass_to_pass: string[];
  };
  error_message?: string;
}

// =============================================================================
// DATASET LOADING
// =============================================================================

/**
 * Load SWE-bench Lite dataset from HuggingFace.
 * Requires Python with `datasets` package installed.
 */
export async function loadSWEBenchLite(
  options: {
    split?: 'test' | 'dev';
    limit?: number;
    instanceIds?: string[];
  } = {}
): Promise<SWEBenchInstance[]> {
  const { split = 'test', limit, instanceIds } = options;

  // Write Python script to temp file to avoid shell escaping issues
  const pythonScript = `
import json
from datasets import load_dataset

dataset = load_dataset('princeton-nlp/SWE-bench_Lite', split='${split}')

instances = []
for item in dataset:
    instances.append({
        'instance_id': item['instance_id'],
        'repo': item['repo'],
        'base_commit': item['base_commit'],
        'problem_statement': item['problem_statement'],
        'hints_text': item.get('hints_text', ''),
        'patch': item['patch'],
        'test_patch': item['test_patch'],
        'version': item.get('version', ''),
        'FAIL_TO_PASS': item.get('FAIL_TO_PASS', '[]'),
        'PASS_TO_PASS': item.get('PASS_TO_PASS', '[]'),
    })

print(json.dumps(instances))
`;

  const scriptPath = path.join('/tmp', `swe-bench-loader-${Date.now()}.py`);

  try {
    fs.writeFileSync(scriptPath, pythonScript);

    // Use execFileSync for safety (no shell injection)
    const result = execSync(`python3 "${scriptPath}"`, {
      encoding: 'utf-8',
      maxBuffer: 100 * 1024 * 1024, // 100MB buffer for large dataset
    });

    // Cleanup
    fs.unlinkSync(scriptPath);

    let instances: SWEBenchInstance[] = JSON.parse(result);

    // Filter by instance IDs if specified
    if (instanceIds && instanceIds.length > 0) {
      const idSet = new Set(instanceIds);
      instances = instances.filter((i) => idSet.has(i.instance_id));
    }

    // Limit if specified
    if (limit && limit > 0) {
      instances = instances.slice(0, limit);
    }

    return instances;
  } catch (error) {
    // Cleanup on error
    if (fs.existsSync(scriptPath)) {
      fs.unlinkSync(scriptPath);
    }
    throw new Error(
      `Failed to load SWE-bench Lite. Ensure Python 3 and 'datasets' package are installed:\n` +
        `  pip install datasets\n\n` +
        `Error: ${error}`
    );
  }
}

/**
 * Options for converting SWE-bench instances to eval tasks.
 */
export interface ConvertOptions {
  /**
   * When true, skips repo clone/checkout setup commands.
   * The isolation provider (WorktreeProvider) handles repo setup instead.
   * The prompt uses relative paths instead of absolute /tmp paths.
   */
  isolationManaged?: boolean;
}

/**
 * Convert SWE-bench instance to EvalTask format.
 *
 * @param instance - SWE-bench instance data
 * @param options - Conversion options
 */
export function convertToEvalTask(
  instance: SWEBenchInstance,
  options: ConvertOptions = {},
): EvalTask {
  const { isolationManaged = false } = options;

  return {
    id: instance.instance_id,
    name: `SWE-bench: ${instance.instance_id}`,
    prompt: isolationManaged
      ? buildIsolatedAgentPrompt(instance)
      : buildAgentPrompt(instance),
    timeout_ms: 1200000, // 20 minutes per task (SWE-bench tasks are complex)
    grader: 'swe-bench' as GraderType,
    expected: {
      swe_bench: {
        instance_id: instance.instance_id,
        repo: instance.repo,
        base_commit: instance.base_commit,
        fail_to_pass: instance.FAIL_TO_PASS,
        pass_to_pass: instance.PASS_TO_PASS,
        test_patch: instance.test_patch,
      },
    },
    metadata: {
      difficulty: 'medium',
      category: 'swe-bench',
      source: 'swe-bench-lite',
      repo: instance.repo,
      version: instance.version,
    },
    setup: isolationManaged
      ? undefined // WorktreeProvider handles repo setup
      : { commands: [buildSetupCommand(instance)] },
    teardown: isolationManaged
      ? undefined
      : { commands: ['rm -rf /tmp/swe-bench-workspace'] },
  };
}

/**
 * Build the prompt for the agent (legacy mode with hardcoded paths).
 */
function buildAgentPrompt(instance: SWEBenchInstance): string {
  const workdir = `/tmp/swe-bench-workspace/${instance.instance_id}`;

  return `You are working on fixing a GitHub issue in the ${instance.repo} repository.

## Repository Setup
The repository has been cloned to: ${workdir}
The repository is checked out at commit ${instance.base_commit} (before the fix).

## Issue Description
${instance.problem_statement}

${instance.hints_text ? `## Hints\n${instance.hints_text}\n` : ''}

## Your Task
1. Navigate to the repository directory: ${workdir}
2. Understand the codebase and the issue
3. Make the necessary code changes to fix the issue
4. Verify your changes work (run relevant tests if possible)

## Important Notes
- Make minimal, targeted changes to fix the issue
- Do NOT commit your changes - just make the edits
- The fix should pass the existing test suite
- Focus on the specific issue described above

Start by exploring the repository structure and understanding the codebase.`;
}

/**
 * Build the prompt for isolation-managed mode.
 * Uses the current working directory (set by workingDirectory config) instead of hardcoded paths.
 * Includes structured workflow, test commands, and budget awareness.
 */
function buildIsolatedAgentPrompt(instance: SWEBenchInstance): string {
  // Parse FAIL_TO_PASS test IDs
  let failToPassTests: string[] = [];
  try {
    const rawFTP = instance.FAIL_TO_PASS;
    failToPassTests = Array.isArray(rawFTP)
      ? rawFTP
      : typeof rawFTP === 'string' ? JSON.parse(rawFTP) : [];
  } catch {
    // Field might already be an array or malformed
    if (typeof instance.FAIL_TO_PASS === 'string' && instance.FAIL_TO_PASS.trim()) {
      failToPassTests = [instance.FAIL_TO_PASS];
    }
  }

  const testCommand = failToPassTests.length > 0
    ? `python -m pytest ${failToPassTests.join(' ')} -xvs`
    : 'python -m pytest -x';

  const testSection = failToPassTests.length > 0
    ? `## Failing Tests (MUST fix these)
The following tests should FAIL on the current code and PASS after your fix:
${failToPassTests.map(t => `- \`${t}\``).join('\n')}

Run them with:
\`\`\`bash
${testCommand}
\`\`\``
    : '';

  return `You are fixing a GitHub issue in the **${instance.repo}** repository.

## Environment
- The repo is set up in the current working directory (commit \`${instance.base_commit}\`)
- Run \`pip install -e .\` if needed before running tests
- **pytest is available** — use it to verify your fix
- All file paths should be relative to the current directory

## Issue Description
${instance.problem_statement}

${instance.hints_text ? `## Hints\n${instance.hints_text}\n` : ''}
${testSection}

## Workflow (follow this order)

### Phase 1: Understand the failing tests (1-3 iterations)
- Read the failing test files to understand what the expected behavior is
- Identify the relevant source files that need to change

### Phase 2: Fix the code (1-3 iterations)
- Make minimal, targeted changes to fix the issue
- Do NOT modify test files — only fix source code

### Phase 3: Verify (1-2 iterations)
- Run the failing tests: \`${testCommand}\`
- If tests still fail, iterate on your fix

### Phase 4: Done
- Once tests pass, you're done. Provide a brief summary.

## Critical Rules
- You MUST run the failing tests before finishing. A fix without verification is incomplete.
- Make minimal changes — do not refactor unrelated code.
- Do NOT commit your changes — just make the edits.
- You have ~50 iterations. Budget them wisely: don't over-explore.

Start by reading the failing test files to understand the expected behavior.`;
}

/**
 * Build the setup command to clone and prepare the repo.
 */
function buildSetupCommand(instance: SWEBenchInstance): string {
  const workdir = `/tmp/swe-bench-workspace/${instance.instance_id}`;

  // Use full clone since SWE-bench commits are often old and not in shallow history
  // Alternative: could use `git fetch --unshallow` but full clone is more reliable
  return `
mkdir -p /tmp/swe-bench-workspace && \\
cd /tmp/swe-bench-workspace && \\
if [ -d "${instance.instance_id}" ]; then rm -rf "${instance.instance_id}"; fi && \\
git clone https://github.com/${instance.repo}.git ${instance.instance_id} && \\
cd ${instance.instance_id} && \\
git checkout ${instance.base_commit}
`.trim();
}

// =============================================================================
// PREDICTION GENERATION
// =============================================================================

/**
 * Extract git diff from a workspace directory.
 */
export function extractGitDiff(workdir: string): string | null {
  try {
    // Get both staged and unstaged changes
    const diff = execSync('git diff HEAD', {
      cwd: workdir,
      encoding: 'utf-8',
      maxBuffer: 10 * 1024 * 1024, // 10MB buffer
    });

    return diff.trim() || null;
  } catch (error) {
    console.error(`Failed to extract git diff from ${workdir}:`, error);
    return null;
  }
}

/**
 * Write predictions to JSONL file.
 */
export function writePredictions(
  predictions: SWEBenchPrediction[],
  outputPath: string
): void {
  const content = predictions.map((p) => JSON.stringify(p)).join('\n') + '\n';
  fs.writeFileSync(outputPath, content);
}

/**
 * Append a single prediction to JSONL file.
 */
export function appendPrediction(prediction: SWEBenchPrediction, outputPath: string): void {
  fs.appendFileSync(outputPath, JSON.stringify(prediction) + '\n');
}

// =============================================================================
// EVALUATION (Using Official Harness)
// =============================================================================

/**
 * Run SWE-bench evaluation using the official harness.
 */
export async function runSWEBenchEvaluation(options: {
  predictionsPath: string;
  runId: string;
  maxWorkers?: number;
  timeout?: number;
  cacheLevel?: 'none' | 'base' | 'env' | 'instance';
  outputDir?: string;
}): Promise<{
  total: number;
  resolved: number;
  resolutionRate: number;
  results: SWEBenchEvalResult[];
}> {
  const {
    predictionsPath,
    runId,
    maxWorkers = 4,
    timeout = 1800,
    cacheLevel = 'env',
    outputDir = './swe-bench-results',
  } = options;

  // Ensure output directory exists
  fs.mkdirSync(outputDir, { recursive: true });

  const args = [
    '-m',
    'swebench.harness.run_evaluation',
    '--dataset_name',
    'princeton-nlp/SWE-bench_Lite',
    '--predictions_path',
    predictionsPath,
    '--max_workers',
    String(maxWorkers),
    '--run_id',
    runId,
    '--timeout',
    String(timeout),
    '--cache_level',
    cacheLevel,
  ];

  console.log(`Running SWE-bench evaluation: python3 ${args.join(' ')}`);

  return new Promise((resolve, reject) => {
    const proc = spawn('python3', args, {
      cwd: outputDir,
      stdio: ['inherit', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    proc.stdout?.on('data', (data) => {
      stdout += data.toString();
      process.stdout.write(data);
    });

    proc.stderr?.on('data', (data) => {
      stderr += data.toString();
      process.stderr.write(data);
    });

    proc.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`SWE-bench evaluation failed with code ${code}\n${stderr}`));
        return;
      }

      // Parse results
      const resultsPath = path.join(outputDir, runId, 'results.json');
      if (!fs.existsSync(resultsPath)) {
        reject(new Error(`Results file not found: ${resultsPath}`));
        return;
      }

      const results = JSON.parse(fs.readFileSync(resultsPath, 'utf-8'));

      resolve({
        total: results.total_instances || 0,
        resolved: results.instances_resolved || 0,
        resolutionRate: results.resolution_rate || 0,
        results: results.detailed_results || [],
      });
    });

    proc.on('error', (error) => {
      reject(
        new Error(
          `Failed to run SWE-bench harness. Ensure swebench is installed:\n` +
            `  pip install swebench\n\n` +
            `Error: ${error}`
        )
      );
    });
  });
}

// =============================================================================
// SIMPLIFIED LOCAL GRADING (Without Official Harness)
// =============================================================================

/**
 * Simple grader that checks if a patch was generated.
 * Use this for quick testing without the full SWE-bench harness.
 */
export function gradeSimple(
  instance: SWEBenchInstance,
  patch: string | null
): {
  success: boolean;
  partial_credit: number;
  explanation: string;
} {
  if (!patch) {
    return {
      success: false,
      partial_credit: 0,
      explanation: 'No patch generated',
    };
  }

  // Basic validation - patch should be a valid diff
  if (!patch.includes('diff --git') && !patch.includes('---') && !patch.includes('+++')) {
    return {
      success: false,
      partial_credit: 0.1,
      explanation: 'Patch does not appear to be a valid git diff',
    };
  }

  // Check if patch modifies relevant files (not just test files)
  const modifiesSource = !patch.split('\n').every((line) => {
    if (line.startsWith('diff --git') || line.startsWith('---') || line.startsWith('+++')) {
      return line.includes('test') || line.includes('Test');
    }
    return true;
  });

  if (!modifiesSource) {
    return {
      success: false,
      partial_credit: 0.2,
      explanation: 'Patch only modifies test files',
    };
  }

  // Patch was generated but not verified
  // Full grading requires the official harness
  return {
    success: false, // Not verified - actual success determined by harness
    partial_credit: 0.5, // Give partial credit for generating a patch
    explanation: 'Patch generated but unverified (full grading requires SWE-bench harness)',
  };
}

// Also export loadSWEBenchLite as loadDataset for convenience
export { loadSWEBenchLite as loadDataset };
