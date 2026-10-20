# Test cases before recognized support paths (2026-10-20)

**Rejected on development.** The fixed candidate changed two first pages but
recovered no judged test file. Across 13 consumed questions, judged files stayed
at 13 at five and 17 at 24, with no individual file or visible-quote losses.
The approved early-stop rule applies: no fresh validation questions were sampled
or run, and no product ranking change is retained.

## Candidate and boundary

Baseline is `6e91a82cc7e4d39c0e0ea5ef7d9d21d56056d945` (0.1.12).
For short queries containing `test` or `tests`, the candidate stably grouped
ordinary test hits, recognized support hits, then source hits. It retained every
candidate and score. `is_test_path` and test-evidence eligibility were unchanged.

Support recognition used exact `helper`, `helpers`, `fixture`, `fixtures` and
`support` directory components; `conftest`, `test_helper` and `spec_helper`
basenames; and Perl `.pm`/`.pl` files below `t/.../lib/`. Explicit test filenames
were protected using existing filename and affix conventions, except those
three conventional helper basenames. Thus Faker's
`test/helpers/test_faker_deprecator.rb` remained a test case, covered by an
isolated regression test. Ambiguous paths stayed in their old group.

Explicit helper, fixture, support, mock, stub or conftest queries bypassed the
new order. Source searches, long descriptions, `tested` and `testing` retained
their previous behavior. Classification was once per distinct path per request,
without source scans or persistent caches.

## Evidence

The [freeze](../designs/2026-10-20-test-support-freeze.json) pins the baseline,
candidate patch, operator, question bytes, repository commits, source trees and
resource bounds. The [development manifest](../designs/2026-10-20-test-support-development.json)
reuses nine Express and four Mojo questions with their original line, quote and
source hashes. These are consumed development labels, not fresh or exhaustive
relevance judgments.

Each arm ran from a separate source snapshot using the same Python environment.
Four sequential fresh-process runs indexed cold, then used the existing
`eval.quality.mcp_search` operator: real daily-profile compact MCP delivery,
2,000-token budgets, pages at five and 24, a file-scoped page and fixed
first-named-result inspection. Each page had three stable warm samples.
Captured candidate-generation results were identical between arms on every page.

| Measure | Baseline | Candidate |
| --- | ---: | ---: |
| Judged files at five | 13 | 13 |
| Judged files at 24 | 17 | 17 |
| Visible quotes at five | 5 | 5 |
| Visible quotes at 24 | 2 | 2 |
| Scoped judged files | 12 | 12 |
| Scoped visible quotes | 6 | 6 |
| Fixed-inspection visible evidence | 2 | 2 |

The two changed first pages explain the rejection:

- **Express, accepting content types and choosing a response format:**
  `test/support/utils.js` left the first five and `test/app.router.js` entered.
  The judged `test/res.format.js` stayed first. The other judged test,
  `test/req.accepts.js`, was present at position 64 in the captured body-search
  generation list, but neither delivered page at five or 24 contained it in
  either arm.
- **Mojo, a client request reaching its overall time limit:**
  `t/mojo/lib/Mojo/LoaderException2.pm` left the first five and
  `t/mojo/ioloop_tls.t` entered. The judged
  `t/mojolicious/longpolling_lite_app.t` was present at position 37 in body-search
  generation, but absent from both delivered page sizes in both arms.

These are generation-list positions, not ranks in the final fused pool.
Demoting a recognizable helper did not resolve either relevance miss.
No per-question file or visible-quote loss occurred on any of the three pages.
Single-round warm p95 was 56.2 ms baseline and 32.7 ms candidate; this is
descriptive only, not a performance claim or the conditional three-round
validation gate.

## Bounds and verification

The four runs and source preparation took 23.06 seconds, below the 600-second
cumulative experiment limit. Each run passed the 180-second, 512-MiB scratch
and 1.5-GiB RSS bounds. Maximum observed RSS was 167.0 MiB; peak managed storage
was 91.2 MiB, below the 1-GiB total limit. All supervised process cleanup checks
passed. No downloads, models, cloud workers, repository tests from the source
packs or host MCP restart were used.

An initial sandbox admission check could not inspect processes and launched no
child. Its failure is retained privately. The same bounded experiment was then
admitted with process-inspection permission; no observation was retried.

The isolated candidate's behavioral tests first failed on the baseline
(10 failed, 11 passed), then passed with the existing intent and path tests
(140 passed). Candidate implementation and tests are archived as evidence,
not installed in the product.

The [compressed evidence](2026-10-20-test-support-observations.json.gz) contains
all four observations, resource supervision, the frozen operator, candidate
patch and behavioral tests. The [decision](2026-10-20-test-support-decision.json)
binds their hashes. The decision-replay regression recomputes label hits from
delivered results, compares every page and verifies unchanged candidate
generation. To reproduce, materialize the pinned source packs from existing
caches, create baseline and candidate source snapshots, rebase the archived
patch's two absolute header paths to those snapshots, and run the archived
operator with fresh output directories and the same bounds. No source-pack
dependency installation is needed.

The conditional 24-question Requests/Phoenix/OkHttp/Rails validation remains
unused. This result does not establish that support recognition is universally
unhelpful; it shows that this fixed ordering did not solve its development
examples. Do not spend those fresh questions on the unchanged candidate.

Final checkout verification passed 190 focused ranking, test-path, evidence and
MCP-evaluation tests, Ruff, the strict MkDocs build and the unchanged cached
ranking gate. The latter took 40.40 seconds under supervision (241.2 MiB scratch,
242.0 MiB RSS, process cleanup verified), bringing experiment plus ranking-gate
execution to 63.46 seconds. Peak total managed storage including that verification
was 320.8 MiB. The checkout's product engine hash equals the baseline observation
hash; only documentation, evaluation artifacts and the replay regression remain.
