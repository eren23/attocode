# Evaluation and benchmarks

Start with `uv run --no-sync python -m eval.quality local` after the development
installation in [contributing](../contributing.md). The controller bounds elapsed
time and managed storage, records incomplete/unsupported outcomes, and cleans
scratch. [Quality](../intelligence-quality.md) documents source packs, reports,
ranking, cloud limits and cleanup.

`eval/matrix` preserves frozen ranking inputs and replay. Source judgments,
candidate traces, rejected trials and agent-study results remain under
`packages/code-intel/evals`. Use [validation](../intelligence-validation.md) for
the evidence and its limitations. New ranking claims require fresh judgments;
old queries cannot be relabeled as fresh validation. External-client studies
remain separate from the offline product gate and require explicit execution
scope. No model study runs as part of default CI.

The retired agent benchmark runner and its instructions are preserved in the
[agent archive](../legacy-agent.md). Do not launch historical cloud or paid-client
scripts using old approvals.
