# OSS Demo Playbook: Code-Intel Across Codex, Claude, and Cursor

This playbook demonstrates Attocode's MCP codebase-intelligence tools on large
open-source repositories using three agent lanes:

- Codex CLI
- Claude Code
- Cursor Composer 1.5

The goal is not "which model wins." The goal is to show practical gains from
structured code intelligence in large repos, especially for cheap/fast lanes.

## What This Includes

- Fixed benchmark manifest: `eval/oss_demo/run_manifest.yaml`
- Prompt packet generator: `python -m eval.oss_demo prepare`
- Results validator: `python -m eval.oss_demo validate-results`
- Comparative report generator: `python -m eval.oss_demo summarize`

## Repositories (Wave 1)

- `microsoft/vscode` (TypeScript monorepo)
- `django/django` (Python framework)
- `pytorch/pytorch` (Python + C++)

Wave 2 roadmap is included in manifest: Kubernetes, Next.js, Airflow.

## Step 1: Verify MCP Setup

```bash
uv run attocode code-intel status
```

If needed:

```bash
uv run attocode code-intel install codex --global
uv run attocode code-intel install claude --global
uv run attocode code-intel install cursor
```

## Step 2: Generate Standardized Task Packets

```bash
python -m eval.oss_demo prepare \
  --manifest eval/oss_demo/run_manifest.yaml \
  --out eval/oss_demo/generated \
  --run-id big3-oss-demo-001 \
  --include-ablation
```

This creates per-agent/per-repo markdown packets plus a JSONL results template.

## Step 3: Run Subagent-Style Exploration in Parallel

Use three lanes in parallel, one per repo archetype:

1. Lane A (`vscode`): TS monorepo exploration and impact tracing.
2. Lane B (`django`): Python framework analysis + with/without code-intel ablation.
3. Lane C (`pytorch`): cross-language dependency/risk analysis.

In Attocode, this can be done with `/spawn` for each lane. In Codex/Claude/Cursor,
run equivalent task packets in parallel sessions.

## Step 4: Fill `results.jsonl`

Populate rows for each `{agent, repo, task, mode}` with:

- status
- time/cost/tool-call fields
- five rubric scores (0-5)
- evidence paths

Then validate:

```bash
python -m eval.oss_demo validate-results \
  --manifest eval/oss_demo/run_manifest.yaml \
  --results eval/oss_demo/results.jsonl
```

## Step 5: Build the Comparative Report

```bash
python -m eval.oss_demo summarize \
  --manifest eval/oss_demo/run_manifest.yaml \
  --results eval/oss_demo/results.jsonl \
  --out eval/oss_demo/report.md
```

Use `eval/oss_demo/report_template.md` when you want a manually narrated
version for publishing.

## Suggested "Convince People" Storyline

1. Show one failure mode without code-intel (slow/noisy search).
2. Show the same task with `bootstrap + relevant_context + impact_analysis`.
3. Quantify quality/time delta on at least one repo.
4. Emphasize ROI: cheap/fast agent + strong structure tools > blind traversal.

## Codespaces Roadmap

Current flow is local-first. For portable demonstrations:

1. Add repo-local devcontainers for the target OSS repos.
2. Re-run the same packets in GitHub Codespaces.
3. Compare drift in latency and reproducibility versus local execution.
