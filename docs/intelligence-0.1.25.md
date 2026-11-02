# Attocode Intelligence 0.1.25

Version 0.1.25 stops an API key in the environment from sending source text to
OpenAI, and makes Rust references more reliable. Search ranking defaults are
unchanged.

## OpenAI embeddings need an explicit setting

Before this version, the embedding auto-detection selected the OpenAI provider
when no local embedding model loaded and `OPENAI_API_KEY` was set. An explicit
index call then sent code chunks to the OpenAI API.

Auto-detection now selects local providers only: nomic, then BGE, then MiniLM.
If none of them loads, semantic search uses keyword search. The base installation
has no local embedding model, so it uses keyword search.

To use OpenAI embeddings, set `ATTOCODE_EMBEDDING_MODEL=openai`. With
`ATTOCODE_LOCAL_ONLY` (or `--local-only`), the OpenAI provider is refused also when
you select it.

If you indexed a project with OpenAI through auto-detection, set
`ATTOCODE_EMBEDDING_MODEL=openai` to keep that index. Without the setting, semantic
search uses keyword search for that project.

## Rust references

rust-analyzer replies null to definition and reference requests while it loads
its file system after a workspace change. The client now asks for its
`experimental/serverStatus` notification. After a null or failed reply, the
precision check waits until the server is ready, for at most half of the remaining
2-second deadline. After an answer, also an empty one, it does not wait.

A null reference reply is no longer read as "0 references". A symbol with no
static callers now gets the status `no_references` when the server is not ready,
not `verified`.

rust-analyzer can reload for longer than the deadline. Then the check still
returns a partial result.

Dependencies, discovery limits and the 100 ms native parse budget are unchanged.

Install with `uv tool install attocode-code-intel==0.1.25`, or upgrade an
existing installation with `uv tool upgrade attocode-code-intel`. Restart the
MCP server after you upgrade.
