# Attocode Intelligence 0.1.33

Version 0.1.33 distributes the remote-settings persistence correction in
[PR #346](https://github.com/eren23/attocode/pull/346).

## Remote settings

Saving `.attocode/config.toml` writes a complete private temporary file,
flushes its data and atomically replaces the live file. A failed data write
or replacement keeps the previous valid bytes. Successful saves use mode
`0600`, giving the file owner read/write permission.

The `.attocode` directory and `config.toml` entry must be real entries, rather
than symlinks, including links to another location within the project. Writes
are anchored to the opened project directory so later path symlinks cannot
redirect the covered operations outside it. Project-directory aliases and
new nested project directories remain supported.

Existing config must be a readable regular file containing valid UTF-8 TOML,
at most 1,000,000 bytes. Serialized output must fit the same byte limit before
a temporary file is created. A refused update preserves the original file;
repair invalid data or a linked config layout before retrying. Valid TOML
values, explicit Perl module roots, connection fields and environment overrides
retain their behavior. Comments and formatting may change.

This is a single-writer contract for Linux/macOS POSIX filesystems. Concurrent
updates are not merged, continuously hostile filesystem mutation is outside
the contract, and no power-loss or directory-fsync guarantee is added. Handled
failures clean owned temporary files; an uncatchable process kill can leave a
private temporary file. A returned path can still be changed by an external
filesystem edit. ACL/xattr/ownership preservation and adjacent loader/bootstrap
persistence are not part of this correction.

## Verification

The [initial causal proof](https://github.com/eren23/attocode/actions/runs/42787566977)
qualifies nine failures and ten controls before correction, including a real
OS file-size failure that truncated the old file and three outward symlink
writes. The [size-bound proof](https://github.com/eren23/attocode/actions/runs/42789340270)
adds three qualified failures and two controls for serialization expansion,
ordinary remote-field growth and a new oversized token. All inputs and tokens
in these proofs are authored fixtures.

The maintained suite adds 26 product cases while retaining every previous case
and skip. Both macOS wheel jobs exercise 32 focused cases against the installed
package: filesystem, size-bound and prior TOML controls. Python 3.12/3.13,
PostgreSQL, combined suites, native 100-case navigation and the existing ranking,
image and real-server gates remain in place.

Candidate and actual-PyPI verification upgrade the published 0.1.32 baseline,
check clean installations, compare installed/wheel/sdist Python source and
verify owned cleanup. Ranking, tokenization, output budgets and native deadlines
are unchanged. Embeddings remain optional and hosted features off by default.
There is no new relevance, latency, agent-speed or broad compatibility claim.

## Install or upgrade

Use `uv tool install attocode-code-intel==0.1.33` to install this version or
replace an older exact pin. Restart the MCP server after upgrading. The
[release guide](intelligence-release.md) describes the publication checks;
the [roadmap](code-intel-roadmap.md) retains separately scoped future work.
