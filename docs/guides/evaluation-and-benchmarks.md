# Evaluation & Benchmarks

Attocode includes a comprehensive evaluation framework for measuring code intelligence quality across repositories and languages.

## Quick Start

### Run the benchmark suite

```bash
# Benchmark on default 3 repos (attocode, gh-cli, redis)
python scripts/benchmark_ci.py

# Benchmark on specific repos
python scripts/benchmark_ci.py --repos attocode fastapi pandas

# Single run (faster, no median)
python scripts/benchmark_ci.py --repos attocode --num-runs 1

# Update baseline after improvements
python scripts/benchmark_ci.py --update-baseline
```

### Run search quality evaluation

```bash
# Evaluate semantic search with ground-truth relevance judgments
python -m eval.search_quality

# Single repo
python -m eval.search_quality --repo attocode

# Generate markdown report
python -m eval.search_quality --report eval/search_quality_report.md
```

### Run needle-in-haystack tasks

```bash
# All 15 deep code understanding tasks
python -m eval.needle_tasks

# Filter by type
python -m eval.needle_tasks --type trace_call_chain
python -m eval.needle_tasks --type architecture_quiz
python -m eval.needle_tasks --type impact_assessment

# Single task
python -m eval.needle_tasks --id arch_highest_fanin
```

### Run competitive comparison

```bash
# Compare search quality and latency across repos
python -m eval.competitive

# Generate report
python -m eval.competitive --report eval/competitive_report.md
```

## Benchmark Tasks (10 per repo)

| Task | What It Measures | Service Method |
|------|-----------------|----------------|
| bootstrap | Project orientation speed and quality | `svc.bootstrap()` |
| symbol_discovery | Symbol search + cross-reference quality | `svc.search_symbols()` + `svc.cross_references()` |
| dependency_tracing | Forward/reverse dependency graph quality | `svc.dependency_graph()` + `svc.impact_analysis()` |
| architecture | Community detection + hotspot quality | `svc.community_detection()` + `svc.hotspots()` |
| code_navigation | File symbol listing + reference quality | `svc.symbols()` + `svc.cross_references()` |
| semantic_search | Ranked search result quality | `svc.semantic_search()` |
| dead_code | Unreferenced symbol detection | `svc.dead_code_data()` |
| distill | Code compression/signature extraction | `svc.distill_data()` |
| graph_dsl | Cypher-like dependency query | `svc.graph_dsl()` |
| code_evolution | Git history for a file | `svc.code_evolution_data()` |

### Run 3-way comparison (grep vs ast-grep vs code-intel)

```bash
# Default 3 repos
python scripts/benchmark_3way.py

# All 49 repos
python scripts/benchmark_3way.py --repos all

# Specific repos
python scripts/benchmark_3way.py --repos fastapi,redis,metabase

# Skip code-intel (quick grep vs ast-grep only)
python scripts/benchmark_3way.py --skip-code-intel
```

### Latest Results (v0.2.11, 20 repos)

| Metric | grep | ast-grep | code-intel |
|--------|------|----------|------------|
| **Avg Quality** | 4.0/5 | 2.8/5 | **4.7/5** |
| **Avg Bootstrap** | 91ms | 538ms | 1.7s* |
| **Perfect Scores (5/5)** | 48/120 | 36/120 | **101/120** |
| **Zero Scores (0/5)** | 0 | 24 | 0 |

\* Bootstrap time after progressive hydration. Pre-hydration large repo times were 7-25s.

**Key findings:**
- Code-intel delivers the highest quality (4.7/5) with structured, concise output
- grep is fast (91ms) and surprisingly competitive (4.0/5) for simple lookups
- ast-grep adds limited value — slower than grep with lower quality (2.8/5)
- Progressive hydration brings all repos under 4s bootstrap (cockroach: 24.5s → 1.2s)

Charts and per-repo analysis: `eval/3WAY_BENCHMARK_REPORT.md`

## Configured Repos (49)

The 3-way benchmark covers 49 repositories across 30+ languages:

| Language | Repos |
|----------|-------|
| Python | attocode, fastapi, pandas, requests |
| Go | gh-cli, cockroach |
| Rust | deno, ripgrep, starship, nickel |
| C/C++ | redis, spdlog, cosmopolitan, protobuf |
| Java/Kotlin/Scala | spring-boot, okhttp, spark, cats-effect |
| JavaScript/TypeScript | express, prisma |
| Ruby | faker, rails |
| PHP | laravel, WordPress |
| Swift | SwiftFormat, vapor |
| Elixir/Erlang | phoenix, elixir, emqx, otp |
| Clojure | metabase, ring |
| Other | zls (Zig), luarocks (Lua), postgrest (Haskell), acme-sh (Bash), terraform-eks (HCL), crystal, dart-sdk, fsharp, ggplot2 (R), iTerm2 (Obj-C), julia, kemal (Crystal), mojo (Perl), Nim, ocaml, perl5 |

## Search Quality Metrics

The ground-truth evaluation computes standard information retrieval metrics:

- **MRR@10** (Mean Reciprocal Rank) — Position of the first relevant result
- **NDCG@10** (Normalized Discounted Cumulative Gain) — Ranking quality
- **Precision@10** — Fraction of top-10 results that are relevant
- **Recall@20** — Fraction of relevant files found in top-20

### Ground-Truth Format

Ground-truth files live in `eval/ground_truth/` as YAML:

```yaml
repo: attocode
queries:
  - query: "token budget management and enforcement"
    relevant_files:
      - src/attocode/types/budget.py
      - src/attocode/integrations/budget/economics.py
      - src/attocode/core/context.py
```

### Adding a New Repo

1. Add the repo to `REPO_CONFIGS` in `scripts/benchmark_ci.py`
2. Create `eval/ground_truth/<repo>.yaml` with 5-10 queries and verified relevant files
3. Run: `python -m eval.search_quality --repo <repo>`

## Needle-in-Haystack Tasks

Five task types that test deep code understanding:

| Type | What It Tests | Pass Criteria |
|------|--------------|---------------|
| `trace_call_chain` | Dependency tracing accuracy | Found callers match ground truth |
| `find_dead_code` | Unreferenced symbol detection | Non-empty results returned |
| `impact_assessment` | Blast radius estimation | Correct files identified as affected |
| `architecture_quiz` | Structural understanding | Answers match ground truth |
| `cross_file_symbol_resolution` | Symbol search completeness | All definitions + minimum usages found |

Tasks are defined in `eval/needle_tasks/tasks.yaml`.

## Advanced: Online Benchmarks

Adapters exist for external benchmark datasets (require `pip install datasets`):

### SWE-Atlas QnA

124 deep codebase understanding tasks from Scale Labs. Top models score <31.5%.

```bash
pip install datasets
python -m eval.sweatlas list
python -m eval.sweatlas run --limit 10
```

### PyCG Call Graphs

Verified Python call graph ground truth for evaluating dependency tracing precision/recall.

```bash
python -m eval.pycg setup    # Clone benchmark repo
python -m eval.pycg run      # Evaluate
python -m eval.pycg report   # Generate report
```

### SWE-bench

Repository-level issue resolution (300 instances in Lite, 500 in Verified).

```bash
pip install datasets
python -m eval.swebench run --limit 10
python -m eval.swebench grade --run-id <id>
python -m eval.swebench leaderboard
```

## Regression Detection

The benchmark CI pipeline detects regressions against a committed baseline:

- **bootstrap_time_ms**: 15% threshold (relaxed for timing jitter)
- **symbol_count**: 10% threshold
- **quality_score**: 10% threshold

Results are persisted in `eval/benchmarks.db` (SQLite) for time-series tracking.

## File Cap

The file indexing cap controls how many files are analyzed during bootstrap. Default is 2,000 files. For large repos, increase it:

```bash
export ATTOCODE_FILE_CAP=5000
python scripts/benchmark_ci.py --repos fastapi
```

Higher caps improve coverage but increase bootstrap time.
