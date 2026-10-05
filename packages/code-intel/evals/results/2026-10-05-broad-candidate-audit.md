# Broad-query candidate audit — 2026-10-05

No default ranking change was made. A file-wide all-query-terms source hint
looked useful on the live `cache generation` example but failed the frozen
ten-query check: it rescued **0/7** queries whose labeled source files missed
the first five. Merely displaying the next three candidate files rescued
**2/7**. The prototype was removed from the product path.

The retained audit distinguishes ranking/page misses from retrieval misses.
Run from the repository root with the editable code-intel environment:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/code-intel/src .venv/bin/python \
  -m eval.broad_candidate_audit \
  --case-pack packages/code-intel/evals/broad_candidate_audit.yaml \
  --repos attocode fastapi pandas redis gh-cli \
  --output /private/tmp/attocode-broad-candidate-audit.json
```

The case list was frozen before the first hint trial. The current case-pack
SHA-256 is `13330be88f6d3e5c048ec9fc7e3bb82d8793afc70f21bd2c9ab9a981bd09a009`
(its comment changed when renamed from the prototype pack; the cases did not).
All five source-body indexes were ready before scoring. External repositories
were copied to temporary workspaces. Tested source revisions:
`attocode 0b655b7`, `fastapi 11614be9`, `pandas 0039f168`,
`redis 20f163eb`, `gh-cli 6e49747f`.

| Known relevant source in… | Queries / 10 |
| --- | ---: |
| First five files | 3 |
| First eight files | 5 |
| First 24 files | 9 |
| Missed at five, present by 24 | 6 |
| Missing even from 24 | 1 |

First labeled-file rank by query:

| Repository | Query | Rank |
| --- | --- | ---: |
| attocode | message routing | 7 |
| attocode | safety guardrails | not in 24 |
| fastapi | openapi schema | 8 |
| fastapi | request validation | 14 |
| pandas | label indexing | 10 |
| pandas | timedelta operations | 22 |
| redis | command handling | 3 |
| redis | sorted sets | 10 |
| gh-cli | command factory | 1 |
| gh-cli | repository cloning | 3 |

The audit's median warm lexical search was 29.98 ms (p95 32.19 ms across ten
queries), excluding indexing. These are local timings, not service latency
claims. The labels are source-bound but not exhaustive: a top-five file can be
useful even if it is not listed, and an unlisted file is not automatically a
false positive. File-level first occurrence is used for ranks.

Interpretation: for this pack, buried candidates are more common than complete
retrieval misses. A larger page is now offered as an explicit follow-up;
the separate [source-view transfer check](2026-10-05-source-view-transfer.md)
did not justify a new ranking default. Use fresh, independent query phrasing
and source judgments before changing ranking behavior; measure the full
returned result, fallback behavior, and latency, not only known-file recall.

The follow-up navigation implementation was subsequently smoke-tested through
the compact daily MCP response on `message routing`: the first page contained
five files, the suggested `top_k=24` request delivered 24 without truncation at
its suggested 4,352-token budget, and the known `src/attocode/types/messages.py`
target appeared at rank 7. The follow-up re-runs the current index and leaves
the original order intact; it is a navigation affordance, not a new ranker.
