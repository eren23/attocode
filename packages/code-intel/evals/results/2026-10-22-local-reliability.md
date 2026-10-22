# Local navigation reliability milestone

Final development-source verification binds commit `c3a5a392a7acbf55063c0d48b8905352d399682a`.
The [machine summary](2026-10-22-local-reliability.json) records source, fixture,
harness and operator hashes, per-pack outcomes and report hashes. These are local
candidate results; CI and published-package verification remain separate gates.

## Changes retained

Native parsing records bounded failures without identifying every parser error
as a timeout. An explicitly selected file with a missing definition can recover
once per source/parser generation. Recovery publishes definitions and references
only after checking the workspace generation, including after snapshot writes;
aborted repairs keep staged reference diagnostics isolated from live state.
Failed reference parses cannot become reusable summaries. Changed extractor
identity forces conservative navigation repair.

The native-source workflow checks exposed guarded Elixir definitions that were
missing from navigation. Guarded declaration heads now recover their definitions,
and declaration names do not become fabricated calls. Ruby import extraction no
longer treats ordinary calls or dynamic relative imports as literal paths.
Doctor identifies its configured executable and the server version returned by
its new connection. The maintained release verifier checks artifact, source and
installed identities in isolated clean and upgrade environments.

## Final validation

| Check | Outcome |
| --- | --- |
| Complete local product suite | 4,140 passed, 14 skipped, one expected failure |
| Scale and lifecycle | 100/1,000/10,000-file checks and 20 lifecycle cycles pass |
| Historical ranking gate | Pass; historical questions remain consumed |
| [Native-source workflows](2026-10-22-local-workflows.md) | 12 positive cases and four negative controls pass; two dynamic/macro controls remain limited |
| 36 pinned compatibility packs | 157 passed, 124 limited, seven unsupported; zero failed or incomplete checks |
| Compatibility retrieval observations | 98/144 labeled hits at five, 127/144 at 24; consumed development evidence |
| Development wheel installation | 17 phases pass; both clean and 0.1.12-upgraded installations match all 272 Python files and wheel metadata |
| Installed continuation | Both installations deliver 5→24→48→50 and stop |

The compatibility run took 299.069 seconds; its largest sampled process-tree RSS
was 980.7 MiB and managed storage 1,225.7 MiB, within the 2 GiB limits. Cockroach's
single 54.087-second observation is not a matched performance comparison.
All final phases preserve source identity and verify owned scratch cleanup.

Earlier source-changing attempts, an unbound test-context failure and two
sleep-interrupted validation runs are retained privately as incomplete or invalid
for final-source claims. Final bounded runs used child-scoped idle-sleep
prevention without extending deadlines. No system sleep setting changed.

## Deliberate limits

The native intermittent cold-parse trigger and Rust readiness cause remain
unproven. The original 100 ms parser limit and production readiness deadlines
remain unchanged. The structural-fingerprint restart shortcut is omitted:
remote allocation requests failed before any benchmark trial or source upload.
There is no performance result for that shortcut; compute cost is estimated at
$0, with invoices unchecked.

The single [callback-span candidate](2026-10-21-test-case-spans.md) is rejected on
consumed development evidence after correcting an invalid operator. No ranking
change, retuning or fresh validation follows. The subsequent
[investigation pilot](2026-10-22-investigation-pilot.md) stopped incomplete after
its first pair on structured-output/tool-call protocol failures. These product
checks establish behavior, not agent gains; the pilot adds no benefit claim.
