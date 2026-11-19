# Attocode Intelligence 0.1.37

Version 0.1.37 preserves existing file-level path matches after a content-trigram
index is built. For example, `pyproject` can match `pyproject.toml` even when the
word never appears in the file contents. The correction applies to local keyword
search and the default local search route; no remote server or model is needed.

## Upgrade

```sh
uv tool install --python 3.12 'attocode-code-intel==0.1.37'
attocode-code-intel --version
```

Restart your host's MCP connection after upgrading so a new process uses the
installed package. The CLI version alone does not identify an existing session.

## File-path keyword candidates

The content-trigram index describes raw source bytes. Keyword file documents
also contain path metadata. A definitive content candidate set can therefore
exclude a valid filename or directory token that does not occur in the contents.

For one normalized keyword token of at least three characters, search now also
scores existing file-level documents whose path contains that token. The normal
`file_filter` still applies. Symbol/body candidates, multi-token and short-token
policies, scores, file caps and fallback behavior keep their existing rules.

The derived path map is reconstructed from both cached and newly parsed file
documents. Its values share existing term-key strings, and construction checks
for closure during the pass and before publication. There is no new persisted
cache format or migration, and no per-query path tokenization or source read.

## Verification and limits

Twelve maintained regressions cover a real `fast_search` index, default/keyword
modes, plain/compact output, file scoping, directory tokens, warm-cache reload,
rename/delete, excluded query forms, fallback and shutdown. Qualified failing
controls preceded both the path correction and the shutdown correction.

A frozen warm synthetic comparison used 20,000 documents and four seed files.
All three query medians met the bound of the old ready-index median times 1.2
plus 5 ms; unaffected ordered results, scores and tokenizer inputs were equal.
The four instrumented Python open/stat entry points recorded no calls, and the
four-file path map/tuples used 408 shallow bytes. These are fixture observations,
not cold-start, real-repository latency or general search-quality guarantees.
Two source-exposed development cases established the causal miss; they were
consumed once and were not replayed as blind validation.

Maintained release gates cover Python 3.12/3.13, PostgreSQL, engine/product suites,
native grammars, real language servers, macOS wheels and clean installs/upgrades
from published 0.1.36. Actual public artifacts are verified against tagged source.

The bounded class-source display correction from [0.1.36](intelligence-0.1.36.md)
and optional HTTP features from [0.1.34](intelligence-0.1.34.md) and
[0.1.35](intelligence-0.1.35.md) retain their existing policies and limits.
This release adds no host UI, disconnect, restart-delivery or total-request
latency guarantee. Defaults remain unchanged.
