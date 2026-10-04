# Local SystemOne HTTP ranking trial

**Status: exploratory. Do not enable Bosun as a default code-search ranker
from this result.** This run exercises the production
`SystemOneChoiceReranker` through an actual loopback HTTP server, using the same
frozen twelve-file candidate pages and source excerpts as the earlier
[decision-reranker trial](2026-10-04-decision-reranker-trial.md). No repository
source was sent to a remote inference service.

| Public-repo pack | Queries | Baseline MRR@5 | Bosun MRR@5 | Wins / losses | Median / p95 inference | Failed calls |
|---|---:|---:|---:|---:|---:|---:|
| Final lexical holdout | 20 | 0.423 | 0.542 | 7 / 2 | 1.45 / 2.01 s | 0 |
| Separate external pack | 20 | 0.596 | 0.554 | 6 / 8 | 1.52 / 2.45 s | 0 |

The model was `Hanno-Labs/bosun-v3.1-0.6b` at revision
`87cea31da06559b0f6509f7b45e2724c38e45c03`, served with
`jev-compatible-server` 0.1.1, Transformers 5.18.0, and torch 2.14.1 on this
machine's CPU (MPS and CUDA unavailable). Requests used one typed `choice`, a
maximum of twelve distinct files, the trial's query-focused 1,350-character
excerpts, and a 10-second evaluation timeout. Timing excludes model startup,
retrieval, and candidate-evidence construction. The frozen pool SHA-256 values
were `ff4dd6dff5783aae9128547ecd45f8ebd210e0dcec9bd0146326870aa4cb6312`
and `e9856ef427c9ed97be6e5b907a8352dafd5b8ca5246649f5314d9cb03c1486b1`.
All benchmark repositories matched their recorded HEAD and had no tracked edits.

The published server's built-in Bosun recipe requested `sdpa` attention and
failed while loading `BosunForDecision` on this stack. A temporary registry
overrode only `decision.loader.attn_implementation` to `eager`, retaining the
published model revision and other recipe settings. The packaged CLI then
started but bound to `0.0.0.0`; it was stopped and restarted programmatically
with Uvicorn bound explicitly to `127.0.0.1`. Do not copy the bare CLI command
as a loopback-only deployment recipe on this version.

The adapter also worked through `CodeIntelService._rank_search_results`: for a
two-file FTS5-table query over this checkout, it promoted `semantic_search.py`
ahead of `ast_service.py` in 3.3 seconds. A separate synthetic two-file request
ranked the FTS5 implementation first with Bosun in 3.0 seconds. Earlier local
Decision 2.0 Kai likewise passed the HTTP/service integration checks, but its
three frozen-query trial took 15–27 seconds per query; those three labels are
not a quality comparison.

The external-pack regression is substantive: among the labeled losses, Bosun
put incidental tests/docs ahead of Express request protocol and cookie-clearing
implementations, and demoted Starship's `src/config.rs` on the first pack.
Some narrow target-file labels remain incomplete (for example, Requests cookie
merging has relevant evidence in both `sessions.py` and `cookies.py`), but that
does not explain away the broader external losses. The earlier Jev `choice`
trial scored 0.667 and 0.825 MRR@5 on these two packs, respectively; its
remote API timing and privacy/cost profile are different and were not rerun
here. These are not fresh blind post-selection queries or end-to-end task
success measures.

All 40 warm Bosun calls exceeded the original 800 ms adapter deadline (minimum
1.04 s). The opt-in adapter now defaults to 5 seconds for loopback endpoints
and 800 ms for remote endpoints; both can be overridden. The model itself
remains off by default. The next useful test is a fresh broad-query pack with
multi-relevant labels and a better local model or faster hardware, alongside
candidate-retrieval improvements; this run does not justify a quality claim
for Bosun on code navigation.

Raw result files (temporary, may be purged):

- `/private/tmp/attocode-bosun-http-holdout20.json`
- `/private/tmp/attocode-bosun-http-external20.json`
- `/private/tmp/attocode-kai-http-three.json`
