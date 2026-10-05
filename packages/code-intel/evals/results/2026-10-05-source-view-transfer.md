# Source-only view transfer check — 2026-10-05

A path-only source view was evaluated as an alternative first page, not as a
default ranking change. The view keeps the lexical order within implementation
source files and leaves explicit test/doc queries alone. Its code remains in
`eval/source_view_trial.py`; production search does not call it.

The [case pack](../source_view_transfer.yaml) was frozen before this run,
using new phrasings of source-changing commits from the existing git-derived
ground truth. SHA-256:
`8e9c441858df164decece685871de094201b41c44ede739bbf534d3a88f46310`.
Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/code-intel/src .venv/bin/python \
  -m eval.broad_candidate_audit \
  --case-pack packages/code-intel/evals/source_view_transfer.yaml \
  --repos attocode express fastapi \
  --output /private/tmp/attocode-source-view-transfer.json
```

All three lexical indexes were ready. Source revisions were `attocode 0b655b7`,
`express 6c4249fe`, and `fastapi 11614be9`. The same 24-candidate pool was
used for both views on each query.

| Measure | Current first five | Source-only first five |
| --- | ---: | ---: |
| Source-intent queries with any labeled file | 8/11 | 8/11 |
| Gained / lost queries | — | 0 / 0 |
| Explicit test-intent controls left unchanged | — | 2/2 |

This gives no reason to expose or default to the source-only view. It also
shows a limitation of narrow changed-file labels: two `attocode` queries name
old `src/attocode/code_intel` files while search now surfaces implementation in
`packages/code-intel`. A missing labeled file need not mean an unhelpful
result. The test was intentionally not retuned after seeing its results.
