# Attocode Intelligence 0.1.32

Version 0.1.32 adds explicit Perl module roots and preserves valid TOML data
when remote connection settings are saved.

## Perl module roots

Set roots in the existing `.attocode/config.toml`:

```toml
[perl]
module_roots = ["lib", "dist/Carp/lib"]
```

An explicit list replaces the root/lib defaults; `[]` disables static module
lookup. Only discovered physical workspace files can resolve. Unsafe entries
are skipped, competing modules remain unresolved, and root order does not pick
a winner. File-discovery exclusions remain separate; see the
[configuration guide](intelligence-perl-roots.md) for scoped inclusion.

Config-only edits update dependency policy on the next tool operation and after
reopening, including after a public source notification. Controlled partial
hydration checks require correct dependencies on the first response. Unchanged
source does not queue vector work. Incomplete snapshots remain invalid and are
rebuilt when necessary.

Saving remote settings retains existing valid TOML values, including quoted
keys, lists, nested data, escaped characters and Unicode. Comments and formatting
may change. This release does not add atomic-write or concurrent-filesystem
guarantees to remote-settings persistence.

## Verification and limits

The maintained native suite requires 100 passing cases, retaining its prior 95.
The added cases use the same three immutable Carp source files at repository
scope, through config-only live/closed changes, notification, controlled partial
hydration and reopen. Distribution-root navigation remains covered separately.
These are conservative static and literal-call contracts; Perl is not executed
and dynamic `@INC`, `use lib` and `BEGIN` are not evaluated.

Candidate and actual-PyPI verification upgrade the published 0.1.31 baseline,
check clean installations, compare wheel/sdist/installed Python source identity,
and verify owned cleanup. Python 3.12/3.13, Linux/macOS installation, PostgreSQL,
combined suites and the existing ranking/image/server gates remain in place.

A separate bounded Rust diagnosis found no production correction warranted by
its controlled recovery and real-server checks. Slow real reloads can still
return partial evidence under the unchanged five-second Rust deadline; other
languages retain two seconds.

A [single source-exposed search pilot](https://github.com/eren23/attocode/actions/runs/42722732495)
on six new questions across three pinned repositories retained incomplete
first-page guard/effect evidence in all six cases. Deeper/scoped pages recovered
both p-limit proofs. This did not establish a distinct, previously untested
shared mechanism meeting the experiment gate, so no retrieval candidate was
run. The six questions are consumed; the 24 reserved holdouts remain unissued.
These strict evidence contracts are not general answer-quality judgments.

Ranking defaults, tokenization and response budgets remain unchanged. There is
no new first-page relevance, latency or agent-speed claim. Embeddings remain
optional; hosted features remain opt-in and off by default.

## Install or upgrade

Use `uv tool install attocode-code-intel==0.1.32` to install this version or
replace an older exact pin. Restart the MCP server after upgrading. The
[release guide](intelligence-release.md) describes publication verification;
the [roadmap](code-intel-roadmap.md) records the next bounded checks.
