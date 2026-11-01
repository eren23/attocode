# Attocode Intelligence 0.1.24

Version 0.1.24 adds a preset for the opt-in hosted rerank. Search ranking
defaults are unchanged.

## Hosted rerank preset

`ATTOCODE_INTEL_RANKING_PROVIDER=openrouter` sets the rerank to the settings of
the hosted trial:

- the endpoint `https://openrouter.ai/api/alpha/decisions`
- the model `typesafe/jev-1.13`
- the key from `OPENROUTER_API_KEY`
- a 1500 ms timeout

An explicit `ATTOCODE_INTEL_RANKING_ENDPOINT`, `_MODEL`, `_AUTH_ENV` or
`_TIMEOUT_MS` setting overrides the preset value. The preset does not enable
remote ranking by itself. You must also set `ATTOCODE_INTEL_RANKING_ALLOW_REMOTE=1`
and `ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE` to the one repository that is allowed
to send source:

```sh
ATTOCODE_INTEL_RANKING_PROVIDER=openrouter
ATTOCODE_INTEL_RANKING_ALLOW_REMOTE=1
ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE=/absolute/path/to/repository
OPENROUTER_API_KEY=...
```

`ATTOCODE_LOCAL_ONLY=1` and service mode still block remote ranking.

## Trial result

A [frozen trial](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-11-01-hosted-rerank.md)
used 24 new short questions on FastAPI, Prisma, GitHub CLI and Starship. With the
rerank, 24 of 26 labeled files were in the first five results, against 20 with the
deterministic order. No file label was lost. Rerank p95 was 377 ms, 1 of 144
calls timed out, and 165 calls cost $0.064. The labels are authored, not agent
outcomes. The [search guide](intelligence-search.md#hosted-rerank-experimental)
now recommends the opt-in when you approve sending source excerpts to OpenRouter.

Dependencies, discovery limits and the 100 ms native parse budget are unchanged.

Install with `uv tool install attocode-code-intel==0.1.24`, or upgrade an
existing installation with `uv tool upgrade attocode-code-intel`. Restart the
MCP server after you upgrade.
