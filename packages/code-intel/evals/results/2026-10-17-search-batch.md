# Dogfood fixes and one search candidate (2026-10-17)

We used Attocode on its own repository and compared each answer with `rg`
and the source. The check found three defects. This batch fixes them and
measures each fix. It also tests one retrieval candidate on fresh, frozen
questions. The fixes ship. The candidate failed two predeclared rules and
does not ship.

## Defects found by dogfooding

| Id | Defect | Fix |
| --- | --- | --- |
| A1 | The tree-sitter path dropped Python docstrings and parameter types. Project conventions reported 0% docstrings and 0% typed parameters. | Read the Python docstring and each parameter's type annotation (Python, TypeScript and Java). The keyword cache schema goes from 3 to 4, so old caches rebuild once. |
| A2 | `impact_analysis` listed impacted files alphabetically. A token budget then cut the nearest dependents first. | List files by dependency depth, nearest first. This applies to the local service, the text tool and the database provider. |
| A3 | The words "into", "onto" and "one" were search terms. A fusion query ranked `SystemOneChoiceReranker` first. | Add the three words to the stop words. |

A fresh stdio MCP process repeated the original calls on a frozen snapshot
of `packages/code-intel` (720 files):

| Call | A0 | F |
| --- | --- | --- |
| Conventions (bootstrap) | 0% typed parameters, 0% docstrings | 87% typed parameters, 64% of functions and 85% of classes have docstrings |
| "how keyword and body search scores are fused into one ranking" | `SystemOneChoiceReranker` first, `llm.py:one` fourth | A `SemanticSearchManager` method first, no `one` hit |
| "trim search results to fit max_tokens budget" | No `output.py` hit | `output.py:bounded_bootstrap` second |
| `impact_analysis` of `output.py`, 1,200 tokens | 3 of 14 direct dependents delivered | All 14 direct dependents delivered, first |

## Questions and arms

The [development](../designs/2026-10-17-search-batch-development.json) and
[validation](../designs/2026-10-17-search-batch-validation.json) sets each
have 12 new questions. They cover four pinned packs: pandas (Python), Prisma
(TypeScript), Starship (Rust) and GitHub CLI (Go). Each pack and split has
two natural-language questions and one exact-symbol control. The two splits
use disjoint subsystems that we declared before we wrote any question. The
[freeze record](../designs/2026-10-17-search-batch-freeze.json) holds the
acceptance rules. We froze it before the first search.

A private set of six questions about this repository was a development-only
check. It is not published, because it describes a private snapshot.

| Arm | Source |
| --- | --- |
| A0 | `94d345b` (0.1.8) |
| A1, A2, A3 | A0 plus one fix each |
| F | All three fixes (`6812475`) |
| C | F plus one candidate |

Every observation is the real daily MCP delivery: 5, 24 and scoped results,
2,000 tokens, auto mode. A supervisor bounded each pack run to 180 seconds,
512 MiB of disk and 1.5 GiB RSS. All runs passed inside these bounds. No
run used a model, a download or a cloud worker.

## What the fixes change

The fixes are reported, not gated. The user decided that correctness fixes
ship even if a ranking metric moves.

| Measure | A0 | F | Note |
| --- | --- | --- | --- |
| Ranking gate MRR@5 (68 queries, product method) | 0.530 | 0.555 | Against the committed baseline (0.537), Acc@5 losses/gains are 1/0 for A0 and 2/3 for F. Both pass. The gain comes from A1. |
| Development files at 5 / 24 / scoped (25 judged) | 12 / 15 / 12 | 12 / 15 / 12 | A1 swaps one pandas label at 5 (one loss, one gain). |
| Validation files at 5 / 24 / scoped (27 judged) | 13 / 14 / 12 | 13 / 14 / 12 | Identical. Zero individual losses or gains. |
| 40 earlier regression questions, files | unchanged | unchanged | Visible quotes: 2 losses, 1 gain. Both losses come from A1. |
| Workflow retrieval labels, pandas/Prisma/Starship/gh-cli (hit@5) | 10/16 | 8/16 | Both losses are pandas and come from A1. All 20 workflow assertions pass on both arms. |
| Private self set, files at 5 | 5 | 7 | Inspection quotes 2 → 1. |

Notes on the measured losses:

- A1 adds docstrings (capped at 300 characters, as designed) to keyword
  documents. On pandas, long docstrings now match short queries. For
  "Detect missing values in an array", `ExtensionArray` methods now outrank
  `pandas/core/dtypes/missing.py` (rank 3 → 7).
- In one Requests regression question, the budget-trimmed snippet now starts
  in the middle of an identifier. The snippet window starts a quarter of its
  budget before the first match, without a word boundary. This is an older
  defect that the new ranking exposes.
- A3 alone failed the local ranking gate by one Loc-Bench query
  (`avantifellows__quiz-backend-84`). One of its two gold files left the
  first five (R@5 1.00 → 0.50). F, with all fixes, passes the gate.
- A2 changes no search output. Its search results are identical to A0, as
  the negative control predicts.

## Diagnosis of the development misses

Generation found every judged file. All 13 first-five misses happened in
fusion or delivery ordering. In the eight natural-language development
questions, two causes filled the first five slots:

- Prose documents (`.md`, `.rst`, `.txt`) took 6 of 40 first-five slots.
  On Starship, the body stage ranked six translated READMEs before code.
- Hits that matched one query concept outranked hits that matched several.
  Leaked prose words (`when`, `that`, `still`, `they`) caused some of these
  matches.

Query expansion hurt one Prisma question: "database" added "query model
schema migration table". Expansion helped one gh-cli question, so we did not
test the removal of expansion.

## Candidate and decision

We tested three variants on development only:

| Variant | Development files at 5 / 24 | Result |
| --- | --- | --- |
| v1: question and pronoun words as stop words | 12 → 12 / 15 → 17 | Two individual losses. Rejected. |
| v2: prose documents after source | 12 → 13 / 15 → 18 | Zero losses, below the +2 rule. Rejected. |
| v3 (C): hits that match fewer than two query concepts go after the others | 12 → 14 / 15 → 18 | Zero losses, but all four controls changed. |

C is the plan's predeclared option (a). It changes only fusion order:
candidate generation is identical in every page. The
[candidate patch](../designs/2026-10-17-search-batch-candidate.patch.gz)
is hash-bound in the decision record.

C fails two rules:

1. **Controls identical (development).** All four exact-symbol control
   responses changed. One control gained a file at 5. The rule requires
   identical responses, so a gain also fails it.
2. **Zero individual losses (validation).** C lost the primary label of
   `starship:search-batch-validation-1` at 5 and 24. The best chunk of
   `src/modules/aws.rs` matched one query concept, so C moved the file out of
   the first 24. Prose words such as "have", "out" and "once" also counted as
   concepts and promoted unrelated hits.

On validation, C also gained one file at 5 and two visible quotes. These
gains do not change the decision. We did not run C on the 40 regression
questions or the ranking gate, because C was already rejected.

A later candidate needs file-level coverage (not chunk-level) and a cleaner
concept set. It also needs new frozen questions. All 24 questions in this
batch are now consumed.

## Artifacts

- [Decision record](2026-10-17-search-batch-decision.json): `compare()`
  output for A0 → F and F → C in each split, rule outcomes and hashes.
- [Observations](2026-10-17-search-batch-observations.json.gz): 24 MCP
  observations (two splits, three arms, four packs). The per-stage
  generation lists are omitted for size. The private full observations
  confirm that C kept generation identical.
- `test_search_batch_decisions_replay_from_hash_bound_observations`
  recomputes both comparisons and the control check from these files.

## Limits

The labels are author-written, source-bound and not exhaustive. They are
not independent user or agent outcomes. The latency numbers are
descriptive. The workflow labels and the 40 regression questions were
already consumed before this batch.
