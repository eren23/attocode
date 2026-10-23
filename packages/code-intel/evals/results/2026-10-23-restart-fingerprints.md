# Restart fingerprints: incomplete, optimization omitted

The new trial stopped on baseline evidence before any candidate benchmark phase.
The optional structural-fingerprint optimization is omitted; the existing
conservative snapshot repair remains. There is no performance verdict, median
comparison, scored relaunch, posthoc waiting or result sorting.

A fresh baseline cold/restart self-pair returned identical ten-operation evidence.
The first cold phase in the next baseline workspace then differed in
`inspect_symbol.reference_candidates`: two of the five displayed same-name
syntax candidates changed. The selected definition and primary source stayed
equal; the other nine legacy canonical operation captures matched. The raw
`total_reference_candidates` also changed 70→56. At source inspection, reference
coverage was 1.0 in the self-pair and 0.869 in the later cold workspace, whose
coverage phase was `hydrating`. Those records reported no parse failures. The
observed Go grammar, native-module and navigation identities matched in all
three processes. The difference is consistent with incomplete reference
hydration; a specific causal fix has not been established.

The controller stopped before the next phase and removed the owned workspace.
The payload took 229.77s, with sampled aggregate RSS 987,869,184B, managed
disk 1,483,452,724B and evidence 3,801,088B, within 1,800s/2GiB/2GiB/64MiB.
Outer cleanup was verified. Independent data-only replay checked 118 raw replies,
30 completed navigation captures and 9,758 pinned fixture entries against their
Git blobs, then confirmed the null verdict and absence of candidate phases.

Before dispatch, 151 online controls passed, including 13 synthetic candidate
regressions, and fresh static review found no material issue. A subsequent audit
found that the legacy canonical whitelist omitted some visible count/ranking
fields. The maintained operator was corrected with online RED→GREEN
controls. All 141 active controls pass after the correction, including three
new count/ranking retention regressions. The archived trial retains its original
operator and raw responses.
This correction does not rerun or upgrade the incomplete observation.

Both preview and restart trials are closed. Their manual design wrappers are
removed, so new dispatches fail closed until a new approved design is committed.
The frozen [restart design](../designs/2026-10-23-restart-fingerprints.json),
[decision](2026-10-23-restart-fingerprints.json) and
[responses/candidate/baseline source archive](2026-10-23-restart-fingerprints.tar.gz)
retain the staged candidate and its synthetic tests. Existing Cockroach questions
were operational repeats, without a fresh relevance or agent-benefit claim.

Baseline `cc0b52dee916d94359473f3bd3b082ab73ed87f0`, staged source
`498599b429d60f45bfc189457901227ddce313fc`, Actions run
[39893315367](https://github.com/eren23/attocode/actions/runs/39893315367).
