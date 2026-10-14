# Intelligence breadth and depth workstream

Accepted scope: 36 language/format adapters, 36 pinned source packs, 144 unscoped
retrieval questions, six workflow families, and deeper cross-file navigation in
three successive groups. This is offline product evidence, not an agent study.

## Milestones

| Milestone | Status | Required evidence |
| --- | --- | --- |
| Coverage foundation | In progress | Frozen source-backed manifest; honest outcomes; bounded selection, shards and resume; complete baseline |
| Python, JS/TS, Go, Rust | Implemented; final gates pending | Module/alias/re-export and negative controls; real language-server checks |
| C/C++, Java, C# | Implemented; final gates pending | Include/package/namespace resolution, ambiguity and selected-definition identity |
| Ruby, PHP, Kotlin, Swift, Scala, Elixir, Lua, Bash, Zig | Implemented; final gates pending | Explicit module bindings, qualified references and dynamic-case limitations |
| Protocol and operation coverage | Implemented; final gates pending | Catalog-to-test inventory, real MCP/HTTP, profiles, isolation and failure cases |
| Release and final matrix | Implemented; final gates pending | Coherent candidate hashes, required CI, clean install/upgrade, verified cleanup |

The existing six source packs and frozen ranking baseline remain evidence inputs.
New labels must be frozen before evaluating product changes. Missing labels,
unsupported capabilities and incomplete execution are not successful assertions.
All mutations of source packs happen in disposable copies, never cached inputs.

## Execution bounds

Quick/local remain capped at 120/600 seconds. Managed disk is capped at 5 GiB,
process-tree RSS at 4 GiB, with a 2 GiB free-space floor. Broad worker tests have
60 minutes and the controller has 90 minutes. One worker at a time; $1 reservation
per batch, $10 per UTC month, at most six additional batches for this workstream.
Read the live ledger before admission. No budget increase or automatic paid runs.
Temporary tools and optional grammars belong on disposable workers or CI.

Preserve shared caches, evaluation artifacts and frozen studies. No model calls,
model downloads or Claude usage-page checks; R7's STOP remains in force.

## Progress evidence

Implementation starts from main `ecc2c3e19d37ed6e802e39eece30fdd5692faaa6`.
The existing symlink fix is merged but not in released 0.1.5. The first bounded local milestone passed; broader evidence remains explicitly partial. Record each completed milestone's report location, candidate
hash, corrected examples, limitations, runtime/storage and cleanup here.

### Implemented foundation and language work

- Frozen manifest SHA-256:
  `e254cb987f782483d241d93b929d24d2582d74c51627a223638a489d4ff4bc9a`.
  36 pinned repositories, 144 unscoped questions, 141 target files. Labels were
  frozen from native source before running the expanded candidate.
- Pack/shard selection, coherent resume/aggregation, five evidence outcomes,
  per-pack subprocess deadlines/checkpoints/cleanup, JUnit and runtime operation
  inventories are implemented. Cloud selection and bounded resume-report upload are supported; resume checks
  source hashes before rental and full environment identity on the worker.
- Module ownership, static aliases and selected references are implemented across
  all three language groups with negative controls. These remain partial static
  capabilities. See the quality guide for unsupported dynamic/build cases.
- Parser work covers 36 languages/formats, no implicit grammar acquisition,
  bounded slow grammars, C++/Objective-C headers and F# recursive type declarations.
  Bulk persistence avoids scanning all references once per file.
- Real TypeScript cold and installed Rust warmed identity/edit/shutdown checks
  passed. Python/Go worker checks, explicit optional-grammar acquisition and
  Linux/macOS 3.12/3.13 upgrade checks are implemented in CI; remote results pending.
- Full standalone diagnostic: 525 passed, four skipped, 52.8 seconds, 746.6 MiB
  sampled RSS, 95.5 MiB managed disk, cleanup verified. Seven earlier test-location
  failures remain recorded; study fixtures require external scratch paths.
- Immutable stage A: all 36 attempted, 32 completed without failed assertions,
  two failed and two timed out. 136 retrieval observations: 95 labeled hits at 5,
  124 at 24. Limited/unsupported checks are not positive assertions. The ranking
  gate passed; raw reports remain under `.attocode/quality/runs/`.
- Immutable stage B local: `20261014T203352-572ed8e3`, 469 passed/four skipped,
  scale and lifecycle passed in about 40 seconds. Broader stage B results are
  being collected. Later fixes require a fresh final candidate.
- The first isolated 0.1.5-to-0.1.6 wheel upgrade check passed all seven phases;
  all three project-local client configurations and persisted index/edit freshness
  were verified. Its temporary environment/cache were removed. This was a local
  candidate build, not publication and not proof of later edits.

### Remaining delivery gates

Finalize coherent matrix/results, required CI and clean final wheel. Publish the
reviewed implementation, run bounded remote validation within the unchanged ledger,
verify deletion, then publish 0.1.6 after its release gates. Keep failures, unsupported
cases, missing relationship labels and untested advanced operations visible. No
model benefit, ranking improvement or universal reference resolution is claimed.
