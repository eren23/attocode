# Explicit test search and transient precision recovery

**Decision: adopt one measured test-intent partition and bounded language-server
recovery.** This batch also exercises repeated navigation workflows and cached
large-repository behavior. It does not publish a release, change model defaults,
or retire the agent.

## Search usefulness

The [frozen twelve-question manifest](../designs/2026-10-16-test-intent.json)
contains eight explicit test requests and four production controls across
Express (JavaScript), ripgrep (Rust), Cats Effect (Scala) and OkHttp (Kotlin).
Source quotes and file hashes were verified before retrieval. These questions
were new; the repositories and related source files had prior exposure. Labels
are non-exhaustive judgments by the implementer, not independent relevance or
agent-outcome measurements.

The single predeclared candidate stably places recognized test files first for
short requests containing `test` or `tests`, using the existing twenty-term
intent boundary. Production queries remain source-first. Scores, candidate
creation, expansion and file diversity do not change. Each arm ran three times
in alternating order on a shared warmed index; repeated results were stable.

| Measurement | Baseline | Candidate |
| --- | ---: | ---: |
| Test questions with a labeled file in first five | 3/8 | 6/8 |
| All questions with a labeled file at 24 | 8/12 | 12/12 |
| p95 of per-question median latency | 27.145 ms | 27.783 ms |

Both ripgrep test questions and OkHttp form encoding gained a top-five target.
No individual labeled hit was lost. All four production result pages/scores and
all candidate-generation stages matched. The predeclared gain, cross-repository,
no-loss and latency gates passed. With twelve samples, nearest-rank p95 is the
maximum per-question median. The questions are now consumed; no subsequent
candidate tuning is justified by calling them fresh again.

The [raw observations](2026-10-16-test-intent.json) preserve pools, scores,
orders, source identity and timings. Four supervised comparisons took 8.245
seconds, peaking at 38.2 MiB managed disk and 111.9 MiB sampled RSS. Cached sources
only, 64 MiB materialized-source cap per pack, 512 MiB managed-disk and 1.5 GiB RSS
limits; scratch cleanup verified. The product uses the evaluated partition.

Manifest SHA-256:
`8eb3b399ac231647ba4477c7268a8558366fd39acc8517a41ab1dec04fd55d41`.
The raw trial source fingerprint predates product adoption and the final precision
repair; final validation binds those changes separately.

## Precision recovery

Four deterministic real-subprocess regressions failed before the repair:
unresolved definitions, protocol errors, timeouts and empty reference results
stayed cached even after the server recovered without a source edit. Partial
results now expire after a one-second cooldown. Immediate repeated requests
reuse the fallback, later explicit requests retry, and successful results remain
cached until invalidation. Syntax references remain available throughout.

The third of three actual Rust trials reproduced an intermittent first-call
failure. Its wire trace contained a valid caller during warmup followed by null
definition/reference replies for the unchanged symbol. Document opens were
balanced; no duplicate open, Content Modified error or readiness notification
explained that failure. The upstream cause is unknown.

Two additional subprocess regressions reproduced a transient run of null or
Content Modified responses. Both failed before the same-request repair. The
lookup now makes at most four attempts, separated by 50/100/200 ms, inside the
unchanged two-second deadline. Indexed-caller priming remains limited to eight
files and 256 KB once per request. Other errors fall back as before. Genuine
empty results with syntactic caller candidates can incur the bounded retry delay.

Six new, sequential Rust fixtures passed on the repaired source in 28.141
supervised seconds. Each checks selected identity, edits and shutdown using the
unchanged real-server test. The original two-pass/one-fail sequence and all wire
traces are retained privately; the successful sequence is recovery evidence,
not proof that all language-server readiness races are eliminated. A sandboxed
preflight refused process inspection before starting a trial; it was rerun with
normal process access. No servers or toolchains were downloaded locally.

## Repeated workflows

Five language cases (Python, JavaScript, TypeScript, Go and Rust) each execute
three cycles of eight checkpoints: original callers, edit, rename, delete,
restore, branch switch, gateway close/reopen and return to the original branch.
All 120 checkpoints check exact current caller paths/lines for both definitions,
with partial-evidence metadata and impact-response checks. These are same-file
syntax fixtures; they do not establish compiler-complete cross-file resolution.
Existing database and independent-process cases remain separate required checks.

## Large repository and final verification

The CockroachDB pack uses a pinned, bounded Go source slice: 9,779 files under
`pkg/server`, `pkg/cli`, `pkg/sql` and `pkg/kv`. Baseline materialization and a fresh
local index passed in 51.483 supervised seconds, peaking at 1,225.6 MiB managed
disk and 783.0 MiB sampled RSS; scratch cleanup passed. Cached Git inputs are
read-only. This Mac result cannot be compared as a speedup against the prior
167.970-second cloud workload, whose 180-second limit remains unchanged.

Final cached validation `20261016T133358-fdfeafce` passed in **171.081 seconds**:
**829 tests, nine explicit skips**, Ruff, scale, lifecycle, seven pinned packs and
the unchanged frozen ranking gate. Peak managed disk was **1,269.5 MiB** and
sampled process-tree RSS **838.8 MiB**, below the 2 GiB disk budget; cleanup passed.
The seven packs (Cats Effect, CockroachDB, Express, OkHttp, Phoenix, Redis and
ripgrep) produced 36 passing assertions, 20 label-limited checks, zero failed or
incomplete checks, and all 28 retrieval observations (20 known-target hits at five,
25 at 24). These reused development queries are regression evidence, not fresh
search validation. The Cockroach check/query total was 45.889 seconds versus
43.789 in the local baseline, excluding materialization; no performance gain is
claimed. The separate cloud timing remains unresolved.

The [validation summary](2026-10-16-search-recovery-validation.json) records source,
fixture and private full-artifact hashes. Full reports and failed traces remain
under `.attocode/quality/runs/20261016-whole-batch`. PostgreSQL, four real language
servers and all required upstream checks gate merge. Limited source labels and unsupported operations are not passing
semantic assertions. No new cloud rental is covered by the old conditional
retry: its prerequisite was a failed target, and that target passed.

The proposed next package is the [intelligence-only transition](../../../../docs/intelligence-workstream.md#proposed-next-package-intelligence-only-repository).
It preserves an agent archive and useful tests before removing agent-only
maintenance. No deletion or rebrand is part of this batch.
