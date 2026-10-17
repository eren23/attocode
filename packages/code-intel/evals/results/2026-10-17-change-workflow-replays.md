# Published 0.1.7 on three real changes

The installed release found all **eight preselected caller sites**, all **three
changed target definitions**, and all **four known relevant test files** in these
historical replays. Test-file suggestion ranks were 3, 5, 5 and 3. All nine
saved-report mutation/refresh sequences passed. Seven caller labels are production
sites; one is a newly added regression-test call. Three of the four test files
are themselves changed patch inputs. Only the unchanged remote-fallback test
(rank 3) is a preexisting-test discovery example. This establishes evidence on
these examples; it does not measure broad test discovery, repair success or an
agent benefit.

## Inputs and measurements

The [design](../designs/2026-10-17-change-workflow-replays.md) and
[frozen task manifest](../designs/2026-10-17-change-workflow-replays.json) describe
the selected production/regression files replayed on each complete actual parent
tree. These are familiar fixes from this Python repository, not fresh unseen
tasks. Input project code/tests were never executed. No models, cloud workers,
new corpora or input dependency installs were used.

| Real fix | Known caller sites | Known test files | CLI changes, new index | CLI trace, disk cache | In-process trace median | MCP trace with startup |
|---|---:|---:|---:|---:|---:|---:|
| Workspace cache isolation, #228 | 3/3 | 2/2 | 6.553 s | 1.076 s | 0.264 s | 1.020 s |
| Behavioral negation, #225 | 3/3 | 1/1 | 4.636 s | 3.162 s | 0.612 s | 0.982 s |
| Overload source recovery, #224 | 2/2 | 1/1 | 5.168 s | 3.204 s | 0.524 s | 1.080 s |

The first CLI command has a new project index directory; this is not an OS
cache-cold benchmark. The subsequent CLI trace reuses disk caches. Each new
gateway made five sequential traces; medians above use the last four, excluding
the initial cache load. Warm ranges were 0.241–0.301, 0.260–0.654 and 0.300–0.922
seconds respectively. These small samples do not establish stable tail latency
or a performance improvement. The stdio measurement includes startup, protocol
initialization and tool discovery, with previously populated disk caches; it
ends when the result arrives, before connection shutdown.

The combined change reports, all five gateway traces per task and all three
actual full-profile stdio MCP traces retained the labeled caller sites. The delivered MCP structured reports
passed the CLI-compatible integrity/freshness check. This trial leaves the host's
daily profile unchanged; the new operations were exercised in disposable full
sessions.

For each task, separately editing a caller file, staging the patch, or changing
only the branch name made the saved report stale (exit 1). Refresh generated a
current report (exit 0); restoring the initial state made the original current
again. That is nine independent sequences, including actual CLI exits.

Twelve post-collection scorer controls rejected empty edges, wrong call-site
lines, wrong callee files and wrong caller identities in copies of actual
reports. Labels were not changed after seeing results. This tests selected-site
scoring, not the precision of every returned edge.

## The practical limit

The combined change reports were **101,671**, **257,930** and **406,951 bytes**.
No changed files or definitions were omitted, but **1, 4 and 8 individual caller
flows** hit their caps. Broad changed-class flows in particular produced many
unresolved candidates: omitted-unresolved counts summed across changed flows
were 0, 611 and 1,175. These sums may count the same candidate in several flows;
they are not unique missing references.

Standalone traces of the selected definitions used the larger 32-node bound and
did not omit nodes or edges in these examples: graphs had 26/26, 18/38 and 5/6
nodes/edges, with 24, 0 and 0 unresolved rows. Missing edges still do not establish
absence. Two CLI snapshots reported phase `hydrating` despite parsed-file counts
equaling their totals; neither is described here as proof of complete indexing.

For a broad patch, use the combined report to select a definition, then use a
focused trace. A useful next implementation would make individual-symbol focus
and changed-class summaries easier to request and read. This trial does not
change traversal defaults, class behavior or ranking.

## Cost, storage and evidence

The successful outer supervised run took **70.712 seconds**, with peak sampled
process-tree RSS **448.938 MiB** and peak managed storage **197.363 MiB**, below
the fixed 600-second / 2-GiB-RSS / 1-GiB-storage limits. Disposable snapshots and
caches were removed; the managed root retains only its marker/empty directories.
Shared studies, caches, model storage and Docker were untouched.

The first attempt stopped during preparation on the repository's contained
documentation symlink, before collecting any product report. Its failure is
preserved privately. Preparation was corrected to preserve bounded contained
symlinks, with unchanged task labels. This was a harness correction, not a product
failure. Scoped Ruff and whitespace checks passed.

The [machine-readable summary](2026-10-17-change-workflow-summary.json) pins the
manifest, exact runner and compressed/raw observation hashes. The
[compressed observations](2026-10-17-change-workflow-observations.json.gz) contain
complete reports, source hashes, all timed samples, labels and freshness results
(70,711 compressed bytes; 1,159,956 raw bytes). Private supervision logs and the
initial preparation failure remain under the ignored local quality directory.

Reproduce under an installed 0.1.7 environment, using new scratch/output paths,
with the outer limits from the design:

```sh
/path/to/0.1.7/bin/python eval/quality/change_workflow_trial.py \
  --repo "$PWD" \
  --manifest packages/code-intel/evals/designs/2026-10-17-change-workflow-replays.json \
  --scratch /private/tmp/new-workflow-replay \
  --output /private/tmp/new-workflow-observations.json.gz \
  --cli /path/to/0.1.7/bin/attocode-code-intel
```

There is no native timing arm, independent reviewer, general relevance judgment,
cross-language sample or executed repair in this trial. Known-test delivery is
not proof of test sufficiency. No product source, default, version or live MCP
configuration changed.
