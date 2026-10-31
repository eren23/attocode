# Attocode Intelligence 0.1.21

Version 0.1.21 packages the merged search-discovery, OCaml-interface and Go/Rust
fallback corrections. Publication remains conditional on current-source qualification.

Search now preserves the configured discovery scope across fresh/reopened indexes
and reports a supplied context limit with its completed generation. OCaml `.mli`
files use the interface grammar. Go/Rust fallback excludes comment/literal decoys,
retains ordinary multiline spans and accurately labels heuristic definitions/calls.
The 500-line fallback window and 100 ms native parse budget are unchanged.

The existing discovery safety ceiling is 50,000 files. A ready index can cover its
selected inventory while leaving a larger repository partially unexamined. The
new GHA capacity ladder records exact corpus/selected paths, source-bound search,
cold/new-PID persisted restart, SQLite integrity and resource limits. It is separate
from the closed paid campaign and supplies no comparative performance or relevance
claim. The release verification asset records admitted qualification results and evidence hashes.

The previous corrections and their causal evidence remain in the
[scale qualification follow-up](intelligence-scale-qualification.md).
Dependencies and ranking are unchanged. Optional grammars must be acquired explicitly;
navigation does not download them. No tool upgrade or MCP host restart is included.

After the publication gates pass, install with `uv tool install attocode-code-intel==0.1.21`
or upgrade an existing installation with `uv tool upgrade attocode-code-intel`.
