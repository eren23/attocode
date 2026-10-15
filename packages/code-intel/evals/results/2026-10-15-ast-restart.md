# Bounded AST-summary reuse for structural restart

Structural restart previously parsed every supported source file before restoring
saved references. The candidate retains full JSON AST summaries in a bounded,
versioned SQLite metadata entry, checks their identity, and reparses only misses.
This preserves existing AST consumers without introducing lazy placeholder objects.
The [raw component and validation record](2026-10-15-ast-restart.json) accompanies
this report. **The CockroachDB target and 0.1.6 release remain blocked** by the
[previous incomplete target](2026-10-15-discovery-validation.md); no cloud rental
was performed for this local change.

## Cache contract

- At most **32 MiB of serialized payload per workspace**, **1 MiB per file**.
  Entries are selected deterministically; excluded files are still parsed. These
  limits exclude SQLite/WAL and transient memory overhead. There is one replaceable
  metadata entry, not a growing directory of per-generation artifacts.
- Bind the payload to the structural completion record and retain the existing
  count, inventory and before/after filesystem-identity checks. Reuse requires
  exact decoded-source SHA-256, matching absolute path, typed dataclass fields,
  and matching parser/extractor code and direct grammar binary identities.
- Only direct installed tree-sitter grammars are cached. Optional language-pack,
  regex and ctags paths keep normal parsing. No grammar or model is downloaded.
- Missing, invalid, stale or oversized summaries fall back to parsing. An old
  structural index receives summaries on its first successful restore. Partial
  bounded caches are not rewritten on every omitted-file miss.
- Publish summaries before the structural completion marker. Cancellation or
  failure while writing a fresh summary cannot bless an incomplete index. Clear
  both records on index reset; keep the existing database schema version.
- Same-size/restored-mtime edits, adds, renames, deletes and ignore changes still
  use the existing structural repair path. Ranking weights and the 180/90-second
  workflow/search limits are unchanged.

**Correction:** the parse counter below covered the structural restore entry
point, but omitted parsing during discovery before restoration. The claim that
the entire restart avoided parsing was incorrect. See the [follow-up audit and
repair](2026-10-15-restart-discovery-repair.md), which counts both entry points.
The recorded historical timings and raw data are preserved.

## Measured tradeoff

`packages/code-intel/evals/ast_restart_probe.py` generates 160 Go files with 5,120
functions. It compares the prior `_save_snapshot` and `_restore_snapshot` methods
from `b3501b9` with the candidate in alternating order. Each workload has two
observations per mode, with fresh source/index directories; OS and parser caches
are uncontrolled. Values below are medians, not a statistical performance claim.

| Generated workload | Version | Cold start | Restart | Cold + restart |
| --- | --- | ---: | ---: | ---: |
| Short bodies, 663,040 source bytes | Baseline | 0.241 s | 0.163 s | 0.404 s |
| Short bodies | Candidate | 0.296 s | 0.125 s | 0.421 s |
| Longer bodies, 2,352,640 source bytes | Baseline | 0.703 s | 0.424 s | 1.127 s |
| Longer bodies | Candidate | 0.768 s | 0.254 s | 1.022 s |

Both candidates made **zero restart parse calls**, versus **160** in each baseline.
Complete AST fields, definitions, dependency edges and store counts matched by
hash within each workload. Cache payload was approximately 2 MB. The generated
experiment used 26,382,336 bytes across all eight disposable cases and removed
its owned directories afterward.

Saving summaries adds cold-write work: the short-body combined time regressed
slightly, while the longer-body combined time improved. The first exploratory
counter did not intercept the frozen method's globals; it is excluded. The final
probe asserts the expected call count in both arms. No generated measurement
establishes that the full CockroachDB workflow now fits its deadline, and no
fixed speedup or agent-quality gain is claimed.

## Verification

- Final bounded local run `20261015T162142-f5d484a0`: **602 passed, 8 skipped**;
  lint, scale and lifecycle passed in **41.932 seconds**. Source and fixture hashes
  were unchanged throughout; owned scratch cleanup passed.
- Peak managed check disk **127,596,046 bytes**, sampled process-tree RSS
  **806,879,232 bytes**, below the existing 5 GiB/4 GiB caps.
- **19 new controls** cover Python/Go/TypeScript exact-summary and symbol parity,
  source digest rejection, parser changes, malformed data, path binding, byte
  bounds, partial retention, unsupported tiers, old-cache upgrade, real process
  restart, edit-during-restore, cancellation, failed-write retry and clearing.
  Existing edit/index/process controls also pass.
- A negative control using the old restore method fails the assertion that a
  valid unchanged summary must avoid reparsing. This checks that the new control
  distinguishes the old behavior.

No new rental, model request, release, global-tool upgrade, host MCP restart or
protected-cache cleanup occurred. The spare rental from the previous sequence
remains blocked by its failed target prerequisite. A future cloud confirmation
must measure the whole unchanged workflow, including the added cold-write cost.
