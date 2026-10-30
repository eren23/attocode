# Request search discovery coverage correction — 2026-10-30

The source-backed10k omission is reproduced and corrected in bounded online controls. Search now uses the existing request-scoped discovery setting for its own contexts and reports observed discovery selection/capping. This is an unreleased fix against0.1.20; no new package or tag was published.

## Problem and correction

The original paid capacity run40896522768 discovered and structurally indexed10,001 eligible paths (10,000 Python modules and pyproject.toml), but lexical keyword/body indexes kept10,000. Ready scoped search for operation_9999 in module_9999.py returned no candidate. Request AST discovery used ATTOCODE_INTEL_MAX_FILES(default100000), while the independently constructed search context used2000; its composition rule selected10,000 at this size.

The service now passes that existing request setting to SemanticSearchManager. Its nine internally created contexts honor the setting, including fresh lexical discovery, validated snapshot fallback, importance, body indexing, and optional vector inventory. Search-first does not initialize AST. Direct standalone construction retains2000, and caller-supplied contexts retain their own policy.

The cap algorithm, ignore/size/symlink rules, enumeration safety ceiling, parsers, ranking/scoring, exact-scope eligibility, dependencies, and version are unchanged. max_files is the existing configured floor for composition policy, not a new strict cardinality ceiling. Two product files changed; the other347 product files are byte-identical to baseline.

Read-only candidate diagnostics expose discovery_max_files, discovery_discovered_files, discovery_selected_files, and discovery_truncated. Observed counts at the existing50k enumeration boundary are lower bounds and conservatively flagged as capped. Body-index coverage remains relative to the selected keyword corpus. A generation check prevents invalidation during SQLite reads from combining old readiness with new counts. Invalidation clears the completed discovery summary; cancelled/incomplete builds cannot publish a completed summary.

## Original online evidence

| Attempt | Source | Cases | Outcome |
| --- | --- | ---: | --- |
| [41095260263](https://github.com/eren23/attocode/actions/runs/41095260263) | a682213 |470| Incomplete: three real10k omissions and two expected metadata gaps reproduced; smaller fixture assumption was wrong |
| [41095848944](https://github.com/eren23/attocode/actions/runs/41095848944) | b737b37 |470| Admitted RED:9 exact expected assertions,461 positive controls,0errors/skips |
| [41096359459](https://github.com/eren23/attocode/actions/runs/41096359459) |8252c4c| Admitted boundary RED:13 exact expected assertions,461 positives,0errors/skips |
| [41097175876](https://github.com/eren23/attocode/actions/runs/41097175876) |24df8b8| GREEN:474/474,0errors/skips |

The first small fixture used Markdown as non-source filler, but Markdown is a recognized language. All2,102 paths counted as source, so four intended cap controls passed and the standalone-cap assertion failed. Only filler suffixes changed to unrecognized .notes for the corrected RED. The failed original workflow, all raw responses/XML/source and ZIP bytes remain preserved; its verdict remains incomplete.

The expanded controls add unavailable/stale discovery handoff, explicit lower request policy, and invalidation during a diagnostics SQL read. Product source remained baseline-exact until the complete boundary RED was independently admitted. GREEN changes only the two product files and the controller's expected all-pass verdict; test source is unchanged.

All three real10k modes—search-first, AST-first, and reopening an old capped cache—initially kept10,000 keyword/body rows and omitted module_9999.py. GREEN keeps the exact10,001-path set in both indexes and returns source-backed scoped results within the2,500-token complete MCP wire budget. The original target bytes are identical across modes: SHA2561334832d1fdaac110887e2a43ca9e8ee0f49269078a4a353adc7188f2c36fd9a. AST-first also verifies10,001 parsed paths. Source routes, origins, original archive digests, limits and owned-scratch cleanup are independently checked.

GREEN completed in74.027s under600s aggregate,2GiB RSS,2GiB scratch and64MiB evidence limits. No cap was waived. These durations include instrumentation/setup effects and support no speed comparison. All actual tests/fixtures ran on GitHub Actions; local work used static/Git/stdlib retained-data verification only. No paid worker or old campaign rerun occurred.

## Retained coverage and limits

Sixteen regression cases remain:13 focused cases in the maintained397-case preflight, and3 real10k gateway cases in normal CI's required413-regression inventory. Temporary coverage controller/design/dispatch choice were retired after qualification; ordinary manual experiment choices are restored. Normal CI, ranking, optional grammars, install, real-language-server and image gates remain required separately.

This fixes the demonstrated discovery-policy mismatch and diagnostics race. The original paid campaign remains incomplete. Its50k/100k stages remain unissued, and no throughput-saturation, search-relevance, performance, historical-native-cause, or new release claim is made. Cockroach/Deno/OCaml parser failures remain a separate next investigation.

## Reproducible archive

[Original evidence and source archive](2026-10-30-search-coverage-evidence.tar.gz): SHA256`57969c585bbb3fdb48ebd8cdfeb6ec40b2c0424e774615191652535cdae77e66`, 2,948,873bytes, 698members, four original ZIPs and six source snapshots. Content-addressed source blobs bind all349 product files and the committed harness/tests/configuration at each source revision; the qualified branch Git bundle preserves the five commits after the baseline. Manifest hashes and every TAR member were reopened and verified. Private ledgers/credentials are excluded. Evidence stays tracked and directly downloadable; Git source exports omit retained evidence archives.

[Machine-readable report](2026-10-30-search-coverage.json).
