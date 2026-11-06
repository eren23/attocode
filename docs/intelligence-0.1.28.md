# Attocode Intelligence 0.1.28

Version 0.1.28 removes duplicated lexical-index diagnostics from compact search
responses while preserving the complete result payload and source excerpts.

## Compact search diagnostics

Compact search previously serialized the full lexical-index diagnostics in both
`metadata.ranking.index` and `data.ranking.index`. When these ranking records are
identical, the metadata index now contains readiness, coverage and discovery
truncation hints, plus `details_in: "data.ranking.index"`. The full diagnostic
record remains available at that path.

The summary runs after the existing response fitting and snippet restoration.
It is accepted only when the complete serialized response stays within the
requested budget and does not grow. Missing, different or nonbeneficial metadata
copies keep their original response. Results, scores, counts, workspace routes,
source excerpts and continuations remain unchanged. Noncompact output retains its
full metadata record.

Eleven regression cases cover a real gateway comparison, complete data
preservation, token budgets, fallback behavior and input immutability. This is an
output correction; retrieval and ranking are unchanged.

## Install or upgrade

Install with `uv tool install attocode-code-intel==0.1.28`, or upgrade an existing
installation with `uv tool upgrade attocode-code-intel`. Restart the MCP server
after upgrading so the running process loads the new version.
