# Search evaluation helpers

`eval/meta_harness` retains search/rule evaluation helpers and frozen split
logic used by intelligence benchmarks. It imports `attocode_intel` directly;
its shared `EvalResult` record now lives in `eval/result.py` and no longer
requires swarm orchestration.

Use [the bounded quality workflow](../intelligence-quality.md) and
[benchmark guidance](evaluation-and-benchmarks.md) for current validation.
Optional proposal loops can call external models and are not part of ordinary
CI or this repository transition. Historical tuning examples and their original
agent-based paths remain in the
[archive](https://github.com/eren23/attocode/blob/agent-archive-2026-10-16/docs/guides/meta-harness-optimization.md).
