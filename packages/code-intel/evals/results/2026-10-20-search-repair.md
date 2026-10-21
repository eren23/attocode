# Search delivery repair and rejected ranking candidates — 2026-10-20

The retained local change fills spare response space with consecutive ranked
hits and offers a progressing follow-up when final serialization removes rows.
The packing step preserves the already-fitted prefix; a new hint is omitted
if it would displace that evidence. Ranking,
query expansion and the body-index schema are unchanged. This is not a release.

On the 13 consumed Express/Mojo development questions, judged file matches at
five stay **13** and at 24 increase **17 → 18**, with no individual file or
visible-evidence loss at five, 24 or scoped search. Inspection is unchanged.
The Mojo `query-source-s2-1` page delivers **8 → 14 rows** at 2,000 tokens and
recovers its second judged file. This does not recover the timeout assertion
previously traced at rank 17, nor the Express accepts file outside the pool.

The three original ranking candidates are rejected. A later clause-balancing
candidate is also rejected; its separate frozen comparison appears below. No feature flag or dormant candidate
is added to the product.

The later continuation work below provides a verified path to both target files
and their evidence. It does not improve their first-page ranks.

| Arm | Fixed mechanism | Decision |
| --- | --- | --- |
| R | Delivery repair, shared by the candidate arms | Retain after verification |
| D | Fuse metadata/body votes only within one definition, then select the strongest definition per name group | Development unchanged; fresh validation loses the Rails restart test at five and 24, and changes controls. Reject. |
| G | Original query weight 1, generated hints .25 | Gains one first-page match on development, but loses Mojo `query-source-s2-1` implementation label 1 at 24. Reject without fresh validation. |
| M | Porter body postings, max(exact vote, .5 × morphology vote) | Gains one first-page match on development, but loses the same Mojo implementation label at 24. Reject without fresh validation. |

## Frozen comparison

Base: `d2a6d2933091d659ce9b2ea82035668ecb767afd`. All arms retain RRF k=20
and the existing 1.15 body weight. B is the unchanged base, R is delivery-only;
D/G/M each start from R. The development pass used 13 already-consumed questions.
Only D survived its no-loss screen, so D itself was the fixed combined candidate.
An operator accidentally added a development first-five-gain prerequisite. The
accepted plan did not contain that prerequisite; the correction was recorded
before validation, with the historical freeze preserved. No final gate was relaxed.

[Validation questions](../designs/2026-10-20-search-repair-validation.json) were
frozen before candidate responses: 24 new source-anchored questions, six each
for pinned Requests, Phoenix, OkHttp and Rails sources. Each repository has
three behavioral-test questions and helper, exact-symbol and tested-code
controls. They are implementer-authored, non-exhaustive judgments; repository
exposure in previous studies remains a limitation. These questions are now
consumed and must not be reused as fresh validation.

Three alternating rounds (R/D, D/R, R/D) used a fresh index per arm/pack, real
compact MCP calls at 2,000 tokens, pages of five and 24, scoped search, and the
same first-named-result inspection rule. Each warmed page has three samples.
The final rule required at least two gained judged test files at five across
two repositories, no individual file/visible loss at five/24/scoped, no net
inspection loss and preserved control identities. Candidate parameters were
not changed after results.

| Fresh result (same in all three rounds) | R | D |
| --- | ---: | ---: |
| Judged file matches at five | 25 | 25 |
| Judged file matches at 24 | 27 | 26 |
| Visible evidence at five | 13 | 13 |
| Visible evidence at 24 | 1 | 1 |
| Scoped file matches | 24 | 24 |
| Inspection evidence matches | 5 | 7 |
| New behavioral-test file matches at five versus R | — | 0 |

Totals count labeled query/file pairs, not unique files. Unchanged totals can
hide individual losses: the Rails restart test loses both file and visible
coverage at five and file coverage at 24. D therefore fails independently of
its inspection gain. First-page control identities also change.

Median round warm p95 is **75.1 ms R / 81.3 ms D**, within the fixed
max(100 ms, 1.5 × R) limit. Per-pack median cold ratios are 0.990–1.137,
RSS ratios 1.023–1.041 and disk ratios 1.000–1.001; resource gates pass.
Development takes 54.2 seconds and confirmation 189.9 seconds. Across those
34 supervised pack runs, peak process RSS is 187.6 MiB and peak managed storage
195.3 MiB. Every worker exits and cleanup verifies. No model or cloud run occurs.
These are bounded local source checks, not evidence of better agent outcomes.

## Retained implementation

The compact fitter first preserves its previous fitted prefix and evidence,
then tries the next ranked omitted row, using the existing bounded snippet
policy if needed. It stops if that next row cannot fit; it never skips ahead.
The gateway retains the selected rows until serialization instead of discarding
them at the early estimated row cap. Delivered/omitted counts reflect the final
payload. A follow-up reserves its own budget and increases page size or token
budget; an identical retry at the 32,000-token ceiling is suppressed. If a new
hint cannot fit alongside the legacy fitted prefix, the usable page is retained
without that hint. Remote retries carry the resolved snapshot revision.

Budget packing changes apply to compact semantic-search delivery. The remote
revision fix also applies to noncompact search follow-ups. A follow-up reruns the current
index, not a stable cursor. Source evidence shortened to fit remains explicitly
marked. Selection and ranking are not improved by this delivery repair.

## Evidence and verification

The [decision](2026-10-20-search-repair-decision.json) hash-binds the compressed
[observations](2026-10-20-search-repair-observations.json.gz). The archive contains
questions, freezes, all responses, source/engine identities, supervision records,
operators, candidate tests and exact B→R / R→D/G/M patches. Private operator and
verification logs are in `.attocode/quality/runs/20261020-search-repair/`.

- Delivery regressions failed before the fix, then 70 focused checks passed;
  the reviewed final version passes 75 focused checks.
- Full suite: 4,012 passed initially; all 13 process/socket failures passed with
  normal local permissions. Combined initial result: 4,025 passed, 14 skipped, one expected failure.
  After the review fixes, one complete run passes **4,030 tests**, with 14 skips
  and one expected failure, in 186.94 seconds.
- Bounded quick: 196 passed, 5 skipped in 10.32s; lint and cleanup passed.
- Unchanged ranking gate passed with stable input fingerprints before the final
  two response/follow-up fixes; its ranking implementation remains unchanged. A preceding run
  passed the inner ranking checks but was invalidated by a concurrent test-import
  formatting edit; it was preserved and repeated within the original limit.
- Broad: lint, 999 contracts, scale, lifecycle and five workflow packs passed;
  the all-36-pack run stopped at its scratch cap during Cockroach. Overall broad
  status is **incomplete**, not passed. The operator should have selected a small
  pack set. No cap was increased. Its archive-copy error involving disposable
  pytest symlinks was corrected by retaining only logs/reports and cleaning scratch.
- Offline wheel build and unchanged installed-wheel smoke passed. All 271 wheel
  Python files match the retained source and installed copy. Dependencies were
  reused from the existing standalone tool; this is not a fresh dependency install.
  A sandbox Git warning broke the first smoke attempt's root detection; the
  unchanged smoke passed with normal permissions.
- Ruff, whitespace checks and strict documentation build passed. The original archive hashes
  and all **666 scored search pages** (including the reviewed delivery
  confirmation) were recomputed successfully.

All supervised experiments and quality runs, including invalidated/interrupted
runs and the final consumed-question confirmation, total **590.4 seconds**, below the 600-second cap. The broad sampler observed
520.4 MiB at its 512 MiB stop threshold (sampling overshoot); maximum reported
aggregate managed storage was 678.6 MiB and process RSS 871.2 MiB. Archive cleanup
is separate from those sampled run peaks. No benchmark expansion follows.

The fresh final review found two important edge cases: adding a hint could
crowd out previously fitted rows at tiny budgets, and remote retries dropped
the requested revision. Both have failing regression tests followed by passing
fixes. A final confirmation on the 13 consumed development questions has no
individual file/visible loss or net inspection loss versus either B or frozen R.
The final product is RF: R plus those two fixes. Frozen D/G/M experiments remain
unchanged; no ranking mechanism was retuned. The final archive carries the RF
patch, tests, source hashes, observations and comparison separately.

At the end of the original review, one finding was deferred: complete row recovery can leave a
conservative `metadata.truncated=true` even when no row/snippet omission remains.
Delivered/omitted counts remain correct. Live remote infrastructure, an existing
host MCP connection, complete 36-pack compatibility and relevance beyond the
frozen labels were not established by this review. The subsequent audit below
fixes the truncation finding; this paragraph records the original RF state.

The local change is uncommitted and unreleased. The connected MCP process was
not restarted, so these checks do not establish that a host's existing connection
has loaded the edited source. First-page relevance and the rejected mechanisms
remain open research questions; further ranking work needs a new mechanism and
fresh judgments.

## Subsequent audit and corrections

The original user-visible search failures remain unresolved: the repair does
not bring the Express accepts target into the 24-result pool or show the Mojo
timeout assertion in its 2,000-token response. The existing larger-budget
follow-up can expose the Mojo assertion. The retained change improves delivery;
it does not meet the proposed first-page relevance improvement. Thousands of
passing unit tests are correctness evidence, not evidence of that improvement.

Two response defects were reproduced with failing tests and fixed locally:

- The gateway marked its preliminary row cap as truncation before compact
  packing recovered the rows. The fitter now derives the flag from remaining
  row omissions and shortened snippets, removes zero-count omission entries,
  and preserves unrelated upstream truncation. A complete 24-row gateway
  response at 2,500 tokens now reports no truncation when its snippets are whole.
- An oversized continuation already attached by the gateway could make fitting
  raise an error, even though results fit without it. The earlier RF safeguard
  covered only newly attached hints. Existing hints now have the same fallback:
  retain the usable page if the optional hint cannot fit.

The audit independently recomputed file, range and visible-quote labels from
all 666 archived response pages without calling the original scoring helper.
Every stored label matches, the archive hash matches, and the G/M Mojo loss
and D Rails losses are confirmed. This checks stored-response arithmetic, not
the completeness or independence of the labels. It makes no new retrieval calls.

Plan adherence was incomplete. The archived candidate tests cover definition
vote isolation, hint weighting, morphology recovery/reopen, source changes and
fallback. They do not explicitly cover all promised overload, exclusion and
stem-collision cases. Rejection of these fixed prototypes is supported; a claim
that the general approaches cannot work is not. The broad run was incorrectly
launched against all 36 packs and remained incomplete. The original full-suite,
wheel and ranking-gate results describe their recorded source versions; they
are not fresh verification of the audit corrections. Instrumented search timings
include diagnostic capture and should not be described as uninstrumented latency.

For the audit corrections, **266 focused tests pass**, including a 24-case
budget/path/snippet matrix, real gateway delivery, remote continuations,
inspection, ranking, navigation and operation contracts. An exact-budget regression
also verifies that truncation metadata is counted before fitting. Ruff and whitespace
checks pass. Private reproducible evidence and source hashes are under
`.attocode/quality/runs/20261020-search-repair-audit/`. Frozen experiment archives
and decisions remain unchanged. These are additional uncommitted correctness
fixes, not a new ranking experiment, release or verified live MCP update.

## Bounded deeper continuation

After the audit, the user requested continued implementation. A full 24-result
retrieval pool previously ended the continuation once those rows fit, even
though a larger search could retrieve more candidates. Compact search now offers
`reason: "search_deeper"` when the current retrieval limit is reached. The
request increases depth, with automatic deeper suggestions capped at 50. It is
a new search, not proof that more matches exist. It retains query, scope, mode,
workspace and remote snapshot; the initial ranking mechanism is unchanged.
A newly introduced hint cannot displace the legacy fitted evidence. Underfilled
pools and requests already at the automatic depth ceiling do not trigger this
probe. Budget-only continuations still stop when they cannot make progress.

A diagnostic on the two consumed questions followed only the advertised requests:

| Request | Express accepts target | Mojo timeout target |
| --- | --- | --- |
| 5 results / 2,000 tokens | Absent | Absent |
| 24 results / 4,352 tokens | Absent | Rank 17, exact timeout assertion visible |
| 48 results / 8,704 tokens | File at rank 44; judged text outside its preview | Rank 18, exact assertion visible |
| 50 results / 17,408 tokens | File at rank 44; no further depth hint | Rank 18; no further depth hint |

Scoping the unchanged query to the returned Express path exposes the judged
test text. This final scope was selected by the diagnostic operator using the
known target, not by an autonomous agent. The target's broad preview is still
incomplete; first-page relevance is still unchanged. The initial five rows and
the complete 24-row response match the pre-change diagnostic exactly.

The four successful offline diagnostics total 12.737 seconds, with sampled
peak RSS 145.5 MiB and scratch 20.7 MiB; all workers exit and scratch is removed.
An initial supervisor invocation failed because its scratch directory had not
yet been created; its cleanup path stopped the worker before a recorded trial.
There were no downloads, model requests or cloud workers. These checks use
previously consumed questions and establish workflow behavior, not fresh
relevance gains. Private requests, responses, scripts and hash-bound verification
are in `.attocode/quality/runs/20261020-search-continuation/`.

The final check verifies pinned source hashes and literal label lines before
querying. The [continuation decision](2026-10-20-search-continuation-decision.json)
hash-binds the [response archive](2026-10-20-search-continuation-observations.json.gz),
which includes baseline/final responses, operators, resource records, the exact
product patch and regression tests. A fresh review caught a noncompact
compatibility regression: enabling the probe could suppress the existing
budget hint for full-profile requests. Gating the new behavior on compact mode
fixes it; both full-profile MCP and direct noncompact regressions failed before
the fix and passed afterwards. The reviewer verified the correction and found
no remaining issue. Tight-budget prefix tests also cover deeper hints with long
snippets. No host MCP was restarted and nothing was published.

Final verification after the compatibility fix: **4,072 passed, 14 skipped,
one expected failure**, in 146.17 seconds. This complete run covers the final
audit and continuation code together. All 52 delivery regression cases pass;
Ruff, whitespace checks and the strict documentation build pass. The full-suite
XML is `full-final.xml` in the private continuation run directory. The previous
4,064-pass run predates the compatibility fix and is retained separately.

## Subsequent first-page experiment: explicit clause balancing

**Rejected; product ranking is unchanged.** This separate authorized experiment
starts from the verified local delivery and continuation code, engine SHA-256
`b07d70d25d171405a6bc04af7ecec66c33b11f04022311b26b81113ca97877fd`.
The candidate is an isolated process wrapper, never a product edit or flag.

For short, unscoped lexical test queries containing exactly one explicit `and`,
C retrieves both clauses separately. It retains the combined query's first hit,
then alternates previously unseen files from the clause lists through position
five, followed by the original results and clause leftovers. Scoped, helper,
exact-symbol and single-behavior controls bypass this rule. No model, stemming,
new synonym rule or weight change is involved. Candidate parameters were frozen
before development and never tuned after observations.

Development uses the 13 consumed Express/Mojo questions. File matches remain
13 at five and 18 at 24, but visible evidence at five falls 5 → 4: Express
`usefulness-validation-1` loses label 0. The original two misses remain misses
at five. This already prevents retaining the candidate. The predeclared fresh
validation was completed unchanged to characterize benefits and losses.

[Fresh questions](../designs/2026-10-20-clause-balance-validation.json) were
prepared by three source-only authors blind to the candidate and its outputs,
then checked and frozen before validation: 24 questions across Requests,
Phoenix, OkHttp and Rails; 12 paired-behavior questions and 12 single-behavior,
helper or exact-symbol controls. These are purpose-built, non-exhaustive source
judgments from previously exposed repositories, not representative user traffic.
All 24 questions are now consumed.

Three alternating rounds (B/C, C/B, B/C) use fresh indexes, real compact MCP
responses at 2,000 tokens, pages of five and 24, scoped search, and inspection
of the first named result. Each warmed page has three timing samples. B is the
current local product, including the delivery and continuation fixes.

| Result, identical across three rounds | B | C |
| --- | ---: | ---: |
| Distinct judged query/file pairs at five | 25 | 28 |
| Distinct judged query/file pairs at 24 | 29 | 30 |
| Scoped query/file pairs | 24 | 24 |
| Visible evidence anchors at five | 10 | 11 |
| Visible evidence anchors at 24 | 1 | 1 |
| Scoped visible evidence anchors | 15 | 15 |
| Inspection evidence anchors | 4 | 4 |

The three newly present first-page files concern Requests URL percent handling,
OkHttp cache freshness limits, and Rails runner environment selection. The gain
threshold passes. Two questions have multiple anchors in one file; file totals
above deduplicate those anchors within each query. The underlying scorer's raw
`files_5` anchor totals are 27 → 30 and must not be described as distinct files.

Aggregate gains hide the decisive regression: Requests `clause-fresh-2` loses
its visible digest-authentication redirect test in **all three rounds**. B shows
`test_digestauth_401_count_reset_on_redirect`, lines 127–133. C shows the
same-file `digest_response_handler`, lines 152–157, and favors other files over
the relevant test chunk. Whole-file diversity is insufficient to preserve
behavior evidence within a shared test file. The frozen individual-no-loss rule
fails independently of the development failure. Controls, inspection, repeat
stability and resource gates pass; none overrides that failure.

Median round warm p95 rises **34.3 → 74.7 ms**, within the frozen
max(100 ms, 1.5 × B) bound. Per-pack median cold ratios are 0.957–1.009,
RSS ratios 0.983–1.002, and disk ratios 0.999–1.001. Preparation plus development
and validation take **124.5 seconds** under this experiment's 600-second cap.
All 28 supervised comparison workers pass and exit; peak RSS is **177.7 MiB**
and peak managed storage **69.9 MiB**. No model, cloud or download was used.

The [decision](2026-10-20-clause-balance-decision.json) binds the compressed
[archive](2026-10-20-clause-balance-observations.json.gz), containing frozen
candidate code, question inputs, operators, all 28 observations, runtime logs,
scorer, tests and review record. Replay checks frozen identities, query contents,
432 validation pages, 78 development pages and inspection evidence. A reviewer
independently checked all 36 fresh source anchors and reproduced the regression.
The review found missing identity checks in the initial replay script; those
checks were added, with five corruption cases that are rejected. The 13 candidate
checks and five replay checks pass. Product engine bytes still match the frozen
baseline; the earlier 4,072-test product verification remains applicable, and
no new full-suite run is claimed for this evaluation-only change.
The extracted archive reproduces the identical decision. Strict documentation
and whitespace checks pass; owned temporary sources, indexes and replay files
are removed. Historical trace and continuation artifacts retain their hashes.

Do not tune this rule against the consumed questions. A future retrieval design
would need to preserve relevant chunks within a file as well as coverage across
files, and face fresh evidence judgments. No such replacement has been tested
or enabled. The full 36-pack compatibility run remains incomplete.

## Chunk agreement follow-up — completed 2026-10-21

**Rejected on consumed development; fresh validation skipped.** The next
user-authorized experiment replaces whole-file diversification with agreement
between exact source chunks. It does not change production code. Full-query,
left-clause and right-clause lists contribute equal reciprocal-rank votes with
the existing chunk constant k=20. Identity includes file, kind, name and source
span; duplicates within a list contribute once. The combined first hit remains
anchored. Eligibility is unchanged from the prior conservative clause probe.
This tests a distinct fusion mechanism, with no tuning after observations.

The freeze requires at least two new judged query/file matches at five across
two repositories, no individual file/visible loss at five, 24 or scoped search,
no net inspection loss and unchanged controls. Any development failure skips
fresh validation. The diagnostic uses all **37 consumed questions** from the
13-question Express/Mojo pack and the prior 24-question clause pack. One B/C
round across six repositories uses fresh indexes and real compact MCP responses;
three warm samples per page check within-run stability. These are previously
exposed, non-exhaustive source judgments, not fresh relevance evidence.

| Consumed diagnostic result | B | C |
| --- | ---: | ---: |
| Distinct judged query/file pairs at five | 38 | 36 |
| Distinct judged query/file pairs at 24 | 47 | 48 |
| Scoped query/file pairs | 36 | 36 |
| Visible evidence anchors at five | 15 | 15 |
| Visible evidence anchors at 24 | 4 | 4 |
| Inspection evidence anchors | 6 | 6 |

Only Requests URL percent handling gains a new first-page file. Three
query/file pairs disappear: Express clearCookie, Express redirect, and Phoenix
HTML generation. The Express redirect excerpt also disappears. Aggregate
visibility of 15 → 15 hides that individual loss. All 21 ineligible queries and
all 37 scoped result lists remain unchanged. Both the gain and no-loss gates
fail; the candidate stays rejected regardless of timing or control preservation.

A separate passive trace records the three failed queries and verifies identical
archived delivery before, during and after instrumentation. Independent arithmetic
reconstructs all three fused pools:

- Express clearCookie falls from combined-list rank 2 to fused-pool rank 7;
  redirect falls from 2 to 16. Both receive two votes, while unrelated helper
  and configuration chunks receive three.
- Phoenix's combined HTML window, lines 365–396, receives two votes and lands
  at fused-pool rank 6. The right clause finds a different window, lines 421–452,
  containing the judged custom-primary-key assertion at 433. Its one vote puts
  it at fused-pool rank 17. These are pool positions, not delivered-page ranks.

These observed failures show two limits of this candidate: repeated lexical
matches across related queries are not independent relevance evidence, and
exact-window identity splits votes between complementary source windows.
Removing file uniqueness alone does not resolve either problem. The trace
supports those explanations for these queries, not a general retrieval claim.

Warm p95 is **38.5 ms B / 78.6 ms C**. Preparation, 12 comparison workers and
two trace workers total **56.5 seconds** under the new 600-second cap. Peak
process RSS is **173.7 MiB** and recorded managed storage **65.3 MiB**; all workers
exit with verified cleanup. No model, cloud or download occurs.

The [decision](2026-10-21-chunk-consensus-decision.json) hash-binds the
[compressed archive](2026-10-21-chunk-consensus-observations.json.gz). It contains
the freeze, consumed questions, candidate, operators, all observations, passive
traces, source checks, replay code, tests and review. Replay verifies **222 pages**,
74 inspection policies and hits, frozen identities and all comparison cells.
All **59 source anchors** were independently checked against pinned source.
An independent reviewer identified a missing inspection-request check in the
initial replay; a corruption test failed before the check and passed afterward.
Final **20 candidate/replay checks pass**, with no remaining material review
finding. The extracted archive reproduces the same rejection.

Product bytes retain the previous engine hash, and previous delivery tests,
trace archives and continuation artifacts retain their hashes. The earlier
4,072-test product run remains the latest full-suite verification; this
experiment does not claim a new full-suite run. Strict docs and whitespace
checks pass. Owned scratch is removed; all changes stay local and uncommitted.
First-page relevance and the incomplete 36-pack compatibility run remain open.

## Compatibility and restart recovery — 2026-10-21

The approved compatibility pass found and fixed a separate restart defect.
The first complete 36-pack run passed 35 packs; OCaml failed definition lookup,
source inspection and restart for the pinned `typing/typecore.ml` definition
`type_expression`. Its source hash matched, and the index reported ready.
A later instrumented run parsed the same source successfully. The initial
failure did not record grammar timing, so a timeout remains a hypothesis.

A deterministic regression reproduced the persistent failure: after a bounded
grammar failure produces a minimal AST, a healthy restart reparses the file but
loads its old empty navigation index. Source identity alone had been treated as
sufficient to reuse persisted definitions and references. Restart now reconciles
files whose missing or invalid AST summaries require parsing again. The regression
fails before the fix and verifies recovered definitions, call references and
persistence through a third startup afterward. Valid summaries retain the existing
fast path. Parser time limits and ranking defaults are unchanged.

The final candidate completes **all 36 packs in 374.1 seconds**, within the new
600-second matrix cap and 2 GiB process-memory/storage caps. It records **157
passed, 124 limited and seven unsupported checks**, with zero failed or incomplete
checks. Limited checks without positive relationship labels are not verified
relationships; unsupported grammar/discovery cases remain unsupported. All 144
consumed retrieval questions were observed: 98 have a labeled file at five and
127 at 24. These non-exhaustive development labels do not establish a new relevance
gain. This run supersedes the unfinished compatibility status above, while the
older failed and incomplete runs remain evidence of their respective candidates.

Correct recovery has a restart cost when summaries cannot be retained. In the
single before/after Cockroach observations, restart takes **5.84 → 11.76 seconds**;
the final whole pack takes **67.85 seconds**. These are individual observations,
not a stable performance comparison. Large or optional-parser ASTs omitted from
the bounded summary cache now require index repair when reparsed. The final
matrix does not establish that the original intermittent cold-parse trigger can
never recur.

The complete product suite passes **4,073 tests**, with 14 skipped and one expected
failure. Synthetic scale checks at 100, 1,000 and 10,000 files and all 20 edit/restart
lifecycle cycles pass. An earlier full-suite operator mistakenly put disposable
test projects under the real Git checkout, causing 15 isolation-test failures;
its logs and XML are retained. The corrected operator uses an external temporary
root. Independent review found no remaining product correctness issue and called
out the restart cost for measurement.

A small read-only feasibility check also examined five synthetic test forms.
Python named tests and Kotlin test methods already expose source units. The sampled
JavaScript `it` callback, Elixir `test` macro and Ruby `it` block do not expose an
individual test unit; Python's parameter decorator is outside its function span.
This is parser feasibility evidence only. No case-boundary extractor, ranking
candidate, model or fresh relevance experiment was implemented.

The existing ranking gate passes all five methods over 68 query variants. Its
thresholds and historical baseline are unchanged; this does not mean every
ranking matches that historical baseline. An offline development sdist/wheel
build also passes: all **271 Python files** match the current source and installed
wheel, standard MCP/CLI checks pass without the agent package, and the installed
compact search follows **5→24→48→50** and stops. Dependencies are reused read-only
from the existing standalone installation, so this is not a fresh dependency
install or a published release.

The [compatibility decision](2026-10-21-release-readiness-decision.json) binds the
[compressed evidence](2026-10-21-release-readiness-observations.json.gz), including
the final source, fixed-candidate workflow reports, source-bound phase reports,
operators, regressions, earlier failed attempts, review and restart timings.
Replaying the archived reports reproduces the aggregate. Product changes remain
local and uncommitted; the host MCP was not restarted. First-page relevance and
the separately tracked intermittent Rust readiness issue remain open.

## Cold-parse diagnostic — 2026-10-21

A subsequent bounded diagnostic reproduced the cold OCaml lookup failure in
one of three fresh-process, fresh-index observations. The pinned source was
unchanged. Under the existing 100 ms parser limit, grammar attempts returned no
tree, the fallback produced a minimal AST, and cold definition/source checks
failed. Reopening the gateway in the same worker process recovered the definition
at lines 7378–7392. The other two natural observations found the definition;
one used a generic fallback after a failed grammar attempt.

These natural failures are **consistent with timeout**. The instrumented wrapper
suppresses `ValueError`, so it did not capture the underlying native exception.
An explicit 1 µs timeout control reproduced the cold failure and recovery path.
The original matrix failure was not instrumented, and three natural observations
do not establish a failure frequency or an operating-system load cause. No
overlapping calls on the same parser instance were captured; this does not rule
out other parser concurrency. Gateway reopen preserves the worker process and
potentially warm parser state, so it is not an OS-process restart check.

A separate failed-parse injection verified an existing recovery operation:
after removing the injection, `notify_file_changed` for the unchanged
`typing/typecore.ml` changed inspection from `not_found` to `found` in the same
gateway. This was a disposable daily, non-watching gateway; it adds no automatic
recovery and does not establish tool availability in every host profile.

The four initial workers took **78.70 seconds** under a 120-second controller
limit. The separately designed refresh check took **23.84 seconds** under its
40-second limit. Both used 2 GiB disk/RSS caps and removed owned scratch. Worker
completion is distinct from lookup success: the first natural trial and forced
timeout control retain their failed cold checks. One refresh operator setup error
is retained alongside the corrected run.

The [diagnostic decision](2026-10-21-ocaml-cold-trace-decision.json) binds the
[replayable observations](2026-10-21-ocaml-cold-trace-observations.json.gz), frozen
worker, operators and review. Product source remains identical to the candidate
with 4,073 passing tests above. No parser-policy change, automatic retry, ranking
change, publication or host MCP restart occurred. The diagnostic narrows the
remaining cold-parse problem; it does not claim to fix it.
