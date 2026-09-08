# Local evaluation

`daily.py` checks bootstrap latency, readable output budgets, hydration and import edges on generated Python repositories of 100, 1,000 and 10,000 files. It needs no model or network connection.

`workflows.py` runs eight evidence checks each on local FastAPI, Express, ripgrep and dashboard snapshots: definitions, callers, imports, potential impact, test candidates, context, knowledge persistence and edit freshness. It archives committed files into disposable directories and preserves the originals. Reports record repository revisions and the engine source hash. Supply `--revisions` with a JSON mapping of repository names to commits to repeat specific snapshots.

```sh
uv run python packages/code-intel/evals/workflows.py \
  --repos /path/to/local/clones --precision off --output /tmp/workflows-base.json
```

The checks look for known evidence, not exhaustive reference recall or complete test coverage. Readable and structured response tokens are reported separately; `max_tokens` bounds the readable response.

`client_comparison.py` is an opt-in, metered Claude CLI experiment. It requires an authenticated client and an explicit model. Each lane gets the same prompt, native read tools and fresh repository snapshot; the intelligence source is copied once so concurrent development cannot change it between lanes. The lanes are native tools, native tools plus base intelligence, native tools plus optional precision, and an optional Serena server supplied as a revision-pinned launcher JSON. Tools that edit code, run commands or write memory are excluded.

```sh
uv run python packages/code-intel/evals/client_comparison.py \
  --repo-dir /path/to/local/clones --repos express \
  --model YOUR_MODEL --intel /path/to/attocode-code-intel \
  --output /tmp/client-comparison
```

Reports include cost, latency, token usage, actual tool calls, permission failures and known-file anchor hits. An anchor miss can be a different valid caller or test; it is not automatically a wrong answer. Inspect the private traces before interpreting results. These navigation questions do not measure successful coding changes, and single runs do not establish a competitive ranking.

By default the client chooses whether to use connected tools. Add `--require-navigation-tools` to require symbol and reference lookups through each connected server before native verification; reports record whether MCP tools were actually used.
