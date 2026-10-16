# Search evidence correctness through MCP

The final selected change preserves distinct code chunks and requires whole
construct words for query expansion. The evaluator measures actual compact MCP
delivery. The broader behavioral-negation rewrite is **rejected**: it corrected
term parsing but lost judged retrieval evidence. That bug remains open. No model,
ranking provider or package version changed; no release was cut.

## Implementation and regressions

Keyword documents carry definition spans and span-qualified IDs. Keyword cache v3
invalidates old rows once instead of inventing missing overload identities. Body
retrieval deduplicates exact source windows; first-hit owner coverage gets capacity
before additional windows. Fusion matches a metadata definition to its best-ranked
body window inside the same definition span, once per retrieval list. Named-owner
navigation scores remain separate from window identity: first-hit owners retain
their established order and additional windows follow. Different windows never
become extra owner votes. Keyword tie order remains stable despite new IDs.

Metadata definition spans stay separate from source-backed ranges. Hydration uses
them to distinguish overloaded definitions. A Java parser with `parse(String)` at
lines 2–4 and `parse(byte[])` at 5–7 previously returned only the first method. Both
now survive body retrieval, fusion, hydration and cache reopen. Anonymous
JavaScript callbacks, Rust macro windows, long Python methods, true duplicates,
old cache invalidation, edit/rename/delete recovery and named-owner navigation
have coverage. Eight of the original nine identity fixtures failed before the
fix; all ten final fixtures pass.

Expansion matches whole tokenized construct words and plurals. `latest`, `contest`,
`testimony`, `configuration`, `capital` and `author` no longer trigger hints for
`test`, `config`, `api` or `auth`. Explicit `tests`, `config` and `auth` still expand.
Broader expansion suppression and behavioral parsing are not enabled.

## Consumer evaluator

`eval.quality.mcp_search` calls a fresh daily-profile `OperationGateway.execute_mcp`
with auto search and a 2,000-token budget. It separately requests 5, 24 and scoped
results, recording the exact delivered envelope, candidate pool and pre-hydration
diagnostics. File presence, enclosing ranges and literal visible quotes are
separate measures. A visible quote must occur in the same file and its actual
snippet line range. A fixed policy inspects the first delivered named result;
answer labels never select that hit. A requested-24 page can deliver fewer than
24 results. Five-hit metrics never substitute unique files from a deeper page.

Each arm has private corpus caches and a frozen engine snapshot. Three warmed
repeats supply each median; process setup is separate. Arm order is sequential,
not randomized, so timing differences are descriptive. Later measurements reuse
only their own arm cache. The recorded observations include engine, question and
operator hashes. Exact responses compress to keep evidence small.

## Initial candidates and rejections

[Development](../designs/2026-10-16-search-correctness-development.json) and
[initial validation](../designs/2026-10-16-search-correctness-validation.json) each
contain eight new questions across Express, Requests, ripgrep and Gson, with two
distinct source-file judgments per question. Commits, hashes, quotes, line anchors
and acceptance rules were frozen before inspecting outputs. These repositories
were exposed previously; labels are implementer-authored and non-exhaustive, not
independent user research or agent completion outcomes. The previous 24-question
trial was not reused as fresh evidence.

The broad negation candidate kept requirements such as “without leaking
credentials” positive and recognized conservative explicit scopes. Its isolated
development arm changed requested-24 judged files 12 → 11 and scoped visible
quotes 5 → 4. Its combined arm gained a first-five file but retained those losses.
Both are rejected. Parser-assisted expansion preserved judgments but failed the
predeclared latency bound (115.312 ms versus a 103.017 ms limit); one observation
does not establish that its parser caused that timing difference. Rejected query
arms were not run on initial validation.

The first identity-plus-token-boundary candidate passed authored development and
initial validation: first-five file pairs totaled 20/32 → 21/32, and visible quotes
4 → 6. However, the unchanged older ranking gate failed: product MRR@5 fell
0.537 → 0.459, with two accuracy losses versus one gain and four recall losses
versus two gains. That candidate is also **rejected**. Its small authored relevance
gain did not justify deployment. Initial validation is now consumed.

An initial development identity probe revealed repeated owner windows crowding a
scoped method; capacity handling was corrected before the recorded comparisons.
A cache-mixed probe was discarded; all recorded comparisons have private arm
caches. Those initial diagnostics remain private and are not selection evidence.

## Final revision and fresh confirmation

The old gate isolated a navigation regression in fusion. The revision preserves
established named-owner ranks separately from source-window identities. It passed
the unchanged old gate before a
[second freeze](../designs/2026-10-16-search-correctness-confirmation-freeze.json).
Eight [further fresh questions](../designs/2026-10-16-search-correctness-confirmation.json)
were then evaluated once. No product tuning followed this confirmation.

| Final confirmation, eight further questions | Baseline → final |
|---|---:|
| Judged files in delivered first five | 14/16 → 14/16 |
| Judged files in delivered requested-24 page | 15/16 → 15/16 |
| Literal visible quotes, first five | 5 → 5 |
| Literal visible quotes, requested 24 | 1 → 1 |
| Literal visible quotes, scoped page | 3 → 3 |
| Literal visible quotes after fixed inspection | 1 → 1 |
| Warm query p95, milliseconds | 51.517 → 56.024 |

The owner-order identity fix alone and its combination with token boundaries pass
confirmation without individual judged-file or visible-quote losses. This
supports the correctness fix without a measured general relevance or speed gain.
The token-boundary-only arm passed earlier independent validation and the old gate.
The older gate's thresholds and baseline artifact were not changed. A same-environment
baseline-engine control also reports product MRR@5 0.530 (versus the historical
artifact's 0.537), with the same one accuracy/recall loss as the final revision.
The final revision changes 16 first-five orders versus that artifact; the baseline
control already changes 15. No extra gold-metric loss is introduced by the final
revision in this local comparison; the cause of the baseline drift is not assigned.

## Evidence and resource bounds

The [initial freeze](../designs/2026-10-16-search-correctness-freeze.json) records
initial selection; it did not override the later ranking rejection. The
[candidate patches and manifest](../designs/2026-10-16-search-correctness-candidates/manifest.json)
reconstruct every arm from baseline `54f0e80` (decompress the named `.patch.gz`
file before applying it; the manifest binds both compressed and patch bytes).
Rejected patches are evaluation
inputs, not product defaults. The [decision](2026-10-16-search-correctness-decision.json)
replays from [compressed exact observations](2026-10-16-search-correctness-observations.json.gz).
The 2,904,541 raw JSON bytes compress to 328,198 bytes.

All 56 recorded MCP processes passed their resource supervisor: 128.022 seconds
total, 405.066 MiB peak managed storage and 166.953 MiB peak sampled RSS, below
512 MiB, 1.5 GiB and 180 seconds per process. Only cached source packs were read;
no upstream code, model request, download or cloud worker was executed. Local
quality and ranking checks have separate bounded scratch roots and retained
reports; these MCP figures do not include those checks.

Final bounded local checks pass 864 tests (9 environment skips), the 100/1,000/10,000-file
scale checks and 20 lifecycle cycles in about 55 seconds. The unchanged 68-query,
five-method ranking gate passes. Upstream validation is recorded with the PR. The host client's existing MCP process was not restarted or verified by this
work; all runtime measurements used fresh subprocesses and gateways.
