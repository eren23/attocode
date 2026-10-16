# Attocode Intelligence 0.1.6 candidate

This candidate extends static navigation across more language/module layouts and
adds a bounded, inspectable quality matrix. The implementation is merged and its
required CI passed, but publication is blocked: the latest full cold cloud run
passed 35 of 36 source packs and CockroachDB search indexing timed out. Repairs
through PR #192 did not resolve that blocker. The controller finished in 26.1
minutes, within its 90-minute limit. All four additionally authorized repair
batches are used and all workers deleted. See the
[repair-cycle evidence](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-15-cold-repair-cycle.md).
The local candidate upgrade check is not a PyPI publication check.

A subsequent [structural persistence fix](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-15-structural-write-contention.md)
reduces SQL statement count and passed local regression checks. Its small contention
probe does not replace the failed full cloud gate or authorize publication.

## Changes

- Shared discovery/parser language identities; explicit static module ownership for
  Go, Rust, JS/TS, C/C++, Java, C#, PHP, Kotlin, Scala and Swift; literal imports for
  Ruby, Bash, Lua, Elixir and Zig. Import aliases and type/namespace-qualified calls
  have controls against unrelated receivers and unbound bare names.
- Selected-definition identity survives persisted language-server references and
  old precise links are invalidated on workspace edits. Real Rust declaration
  references work when no redundant definition result is returned.
- C++ export annotations in headers, Objective-C forward declarations, F# recursive
  types, OCaml bindings, Julia signatures and HTML resources have focused fixes.
  Grammar parsing is bounded, and reference persistence is batched.
- Discovery and refresh agree on ignored folders and explicit `.gitignore`
  negations. External/broken source symlinks stay excluded. Exact identifier
  recovery is restricted to explicitly selected eligible source files.
- 36 pinned public source packs, 144 unscoped questions, deterministic shards,
  compatible resume/aggregation and outcome counts. Optional grammar acquisition
  is an explicit CI/worker step. Product navigation does not download grammars.

No model or ranking-weight default changes. Daily remains the default profile;
lean remains opt-in. Static relationships remain partial. Dynamic dispatch,
unexecuted build configuration and missing grammars may leave unresolved evidence.

## Upgrade after publication

```sh
uv tool install --force attocode-code-intel==0.1.6
cd /path/to/project
attocode-code-intel doctor --client codex
```

Use `--client claude` or `--client cursor` for those configurations. Restart the MCP
connection after upgrade. Existing project configurations are preserved. Derived
structural/search caches rebuild once for the new schema; user source and knowledge
are not migrated or deleted.

## Evidence

See the [development matrix](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-14-breadth-development.md)
and [quality guide](intelligence-quality.md) for hashes, limitations, reproducible
commands and resource bounds. Successful execution does not turn unsupported or
unlabeled cases into passed assertions. The R7 STOP remains: these product checks
provide no new evidence of better agent outcomes.
