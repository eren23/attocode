# Contiguous preview windows: rejected

The single frozen 24-question pandas/ripgrep trial rejected the archived
strict-positive-term-superset window. No product preview or ranking behavior
changes. The 24 questions are now consumed; no tuning or scored relaunch ran.

Three alternating rounds produced 720 pages (360 paired requests), with depths
5/24, token budgets 2,000/8,000 and exact-file scopes. There were no distinct
judged excerpt gains at five in either split. The ripgrep `parse_comma` question
lost its judged alternate-branch excerpt in all three rounds: 12 individual
request losses across shallow/deep/scoped settings. The candidate moved the
window toward the function header and omitted the required alternate branch,
even though its positive query-term coverage increased. One exact-query control
(`bytes_to_escaped_literal`) also changed at depth 24 in both budgets each round
(six pairs). Delivered identities, scores and order stayed equal.

Warm p95 was 409.61ms baseline and 412.41ms candidate, within the frozen 1.5×
threshold. Timings include passive source fingerprinting; they exclude response
retention/replay, which remain inside the full 167.31-second payload. Peak
aggregate RSS 317,378,560B, managed disk 183,787,520B and evidence 16,662,528B
stayed within 2 GiB/2GiB/64MiB; owned scratch cleanup was verified.

Before scoring, 124 online controls passed. Fresh review identified missing raw
capture admission and incomplete fixture stability checks. Thirteen new controls
failed before their fixes and passed afterward. Each worker now admits all raw
references, binds the exact request sequence, and recomputes identities/data
hashes/source judgments before another worker starts. Complete source inventories
match pinned Git blobs before and after retrieval, excluding only generated root
`.attocode` state. Independent data-only replay verified all 720 pages, 360 pairs,
2,170 fixture entries, losses, controls and timing arithmetic.

The [frozen design](../designs/2026-10-23-preview-windows.json) records source
exposure and the limited freshness audit. Labels are non-exhaustive source
judgments, without a relevance or agent-completion benefit claim. The prior
12-question attempt remains closed/incomplete and was not reused.

Evidence: [decision](2026-10-23-preview-windows.json),
[content-addressed responses and committed source](2026-10-23-preview-windows.tar.gz).
Scored head `f34661699db7bcf515cb05115d5255941bbcdad8`, Actions run
[39888662258](https://github.com/eren23/attocode/actions/runs/39888662258).
