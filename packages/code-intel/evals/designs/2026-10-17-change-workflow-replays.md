# Real-change workflow replays

Exercise published 0.1.7 against three already known fixes in this repository:
workspace trigram ownership (#228), behavioral exclusion terms (#225), and
overload-specific source hydration (#224). This is an operational replay with
source-audited examples, not a fresh task-completion or agent productivity study.

The adjacent JSON pins each original commit/parent, selected patch files, target
definition, eight known caller sites and four known relevant test files. Caller
labels identify enclosing definitions; Python's standard-library AST finds exact
call lines independently of the intelligence parser. An initial source audit
corrected the hydration caller from `execute` to `_execute_sync` before any
product report was collected. Labels are not exhaustive relevance judgments.

For each task, reconstruct the complete actual parent tree, initialize disposable
Git history, and write only the selected real production/regression files from
the fixing commit. Other changes in the original PR are excluded. The input
project is never executed. Contained tracked symlinks are preserved and recorded;
escapes and other non-regular archive members are rejected. Input archive limits
are 3,000 entries, 2 MiB per file and 48 MiB total regular-file content.

Measure these in order:

1. Installed CLI `changes`, with a new index directory, then its saved-report check.
2. Installed CLI `trace`, with disk caches from the first command.
3. Five trace calls in a new full-profile gateway. The first may load disk caches;
   the following four describe reuse in that process. Report samples and their
   median/range, without treating this small sample as a stable tail estimate.
4. A real full-profile stdio MCP trace, including process startup, using existing
   disk caches. Grade the delivered structured data and check its portability.
5. For each independent source-edit, staging and branch-name mutation: an old
   report must exit 1/stale; refresh must produce a report that exits 0/current;
   restoring the original state must make the original report current again.

Record changed-target presence, known direct caller-site coverage, known-test
delivery and ranks, graph sizes/omissions, unresolved references, report bytes,
latency, peak sampled process-tree RSS and managed scratch. Check scorer rejection
of missing edges and wrong call-site/definition identities using copies of actual
reports. A missed label is recorded rather than removed or retuned.

The outer supervisor enforces 600 seconds, 1 GiB managed storage and 2 GiB sampled
process-tree RSS. Runtime also retains the product's source/output/traversal
bounds. Only the disposable snapshots/caches are removed; compressed observations
and a hash-bound summary remain. No acquisition of corpora, models, infrastructure
or input dependencies is needed. Daily/lean profiles and ranking defaults remain
unchanged.

The first preparation attempt rejected the repository's contained documentation
symlink before collecting any product report. Its failure is preserved privately.
The corrected runner supports contained symlinks; the task labels stayed fixed.

Reproduction uses `eval/quality/change_workflow_trial.py`, an installed 0.1.7 Python
environment and its matching executable. Run it under `eval.quality.runner` with
the limits above. Scratch and output paths must be new. The result artifact pins
the manifest hash; the result summary additionally pins the runner and artifact.

These tasks were selected by the implementer from familiar fixes in one Python
repository. No before/after product comparison, native timing arm, independent
reviewer, repair execution or user outcome is measured. Recall on selected call
sites and test files does not establish complete impact, test sufficiency,
general relevance, agent speed or benefit in another repository/language.
