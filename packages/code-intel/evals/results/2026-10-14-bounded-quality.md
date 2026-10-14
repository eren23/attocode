# Bounded local quality results

The local product changes passed the broad offline gate on macOS using the
existing Python 3.12 environment. No agent/model runs, live cloud provisioning,
dependency downloads or shared-cache deletion were performed. The input baseline
is `67b9afbb7e5bc8e5939db182edc9b2973dd32523` plus the local patch. Measurements
below preceded the delivery commit; no release was made.

## Outcomes

| Check | Result |
| --- | --- |
| Broad contracts | 229 passed |
| Final quick contracts | 75 passed; changed-surface Ruff passed |
| Pinned workflows | 6/6 repositories, 48 workflow checks passed |
| Frozen ranking | 53 cases / 21 repositories; 68 distinct query variants in each of 5 methods; no top-five changes |
| Lifecycle | 20 watched/unwatched edit, rename, deletion and restart cycles; six descriptors after every close; no newly owned worker threads left |
| Returning focused lookup p95 | 20.8 ms on the one-file lifecycle workload |
| Warm search p95 | 11.8 ms on the same workload |
| 10,000-file synthetic cold bootstrap | 9.03 s; full 10,001-file coverage including project config and 9,999 expected dependency edges |
| Broad elapsed time | 194.04 s, under the requested 600-second local limit |
| Sampled managed storage peak | 339.64 MiB, below 5 GiB |
| Sampled process-tree RSS peak | 327.59 MiB |
| Retained managed reports after broad | 1.35 MiB; scratch cleanup verified |

The final quick run took about eight seconds. It followed small controller-only
changes to storage admission, report ownership/retention and fixture-integrity
checking; the product engine used by the broad ranking check did not change.
The [manifest](2026-10-14-bounded-quality/manifest.json) binds the engine and raw
artifacts; [broad](2026-10-14-bounded-quality/broad-report.json) and
[quick](2026-10-14-bounded-quality/quick-report.json) reports retain their distinct
input hashes. End-of-run source hashes matched in both runs; the final quick
runner also checks fixture hashes.

## Defects and workflow handling

The selected-source enrichment preserves candidate identity, score and order,
and reports actual snippet coordinates. Unknown receiver calls no longer bind to
a same-file method solely through a unique name.

Repeated lifecycle testing exposed intermittent SQLite initialization failures.
Schema initialization now shares the cache-write lock. A transient operational
error remains retryable rather than permanently marking FTS5 unavailable, and
failed keyword-cache opens close their connection. Separate regression tests
cover a locked database, genuinely unavailable FTS5, failed setup, and optional
reindex-worker shutdown. These fixes do not establish that every cause of the
historical broad root-suite descriptor exhaustion has been resolved.

Workflow checks use definition disambiguation and reference pagination. They
accept impact evidence in depth layers when a flattened list is trimmed. Gson
and the frontend explicitly mark missing dependency/test anchors as limited.
Reference syntax checks are not precise caller-resolution claims. The fixtures
are development inputs, not a fresh held-out relevance evaluation.

## Storage and operational limits

Read-only inventory found 55.30 GiB in historical evaluations, 43.91 GiB in the
shared uv cache, 22.89 GiB in the shared model cache, and 202.67 GiB allocated to
Docker's sparse disk. These remain protected. The exact owned-report cleanup
preview was empty: no expired reports qualified. Full inventory scans of the
existing trees took several minutes; routine test runs do not scan those trees.

The DigitalOcean controller passed mocked provisioning, interruption, collection,
deletion, reconciliation, price/monthly-budget and TTL ownership checks. Live
validation remains blocked by absent controller API credentials and an
unpublished/unverified independent reaper. MCP OAuth was subsequently verified
with a successful empty droplet listing, but does not configure those credentials.
The account's size listing also omitted the selected `c-8`; its live capacity
check must pass before launch. No worker was rented. Estimated admission budgets and TTL
cleanup do not constitute a provider-enforced spending cap.

GitHub workflow YAML was parsed locally. Updated hosted PostgreSQL/wheel/image/
dashboard jobs have not run on GitHub for this patch. Repository-wide Ruff found
pre-existing violations; only the declared changed surface and harness are lint
gates here. The historical root suite is not reported as passing.

R7's reviewed STOP remains unchanged. The next eight-task / sixteen-run workflow
pilot is a separate design requiring frozen prompts/rubrics and explicit
authorization before any model use. See the [operating guide](../../../../docs/intelligence-quality.md).
