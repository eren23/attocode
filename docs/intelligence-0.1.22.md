# Attocode Intelligence 0.1.22

Version 0.1.22 adds an opt-in discovery budget and makes the LLM scorers work
from a PyPI install.

## Opt-in discovery budget

Discovery still collects at most 50,000 eligible files by default. To index a
larger repository, set `ATTOCODE_INTEL_DISCOVERY_MAX_FILES` to an integer from 1
through 100,000 and start a new server process. See
[Discovery file budget](intelligence-discovery.md) for the limits and how
truncation is reported.

One [online capacity run](https://github.com/eren23/attocode/actions/runs/41205748610)
checked three cases:

- A 100,000-file workspace indexed with the default selects 50,000 files and
  reports a limited result. A new process with the higher setting expands the
  same persisted index to all 100,000 files. A further restart keeps them.
- Exactly 50,000 files with the setting at 50,000 give full coverage, on a cold
  start and on a restart.
- 100,001 files with the setting at 100,000 index 100,000 files and report the
  one omitted file.

The [36-pack compatibility run](https://github.com/eren23/attocode/actions/runs/41207354353)
on the same source had no failed or incomplete check. These runs make no speed or
relevance claim.

## LLM confidence and rule synthesis

`ATTOCODE_FLAG_CONFIDENCE=llm` and LLM rule synthesis imported a client from the
development-only `eval` package, which the wheel does not contain. From a PyPI
install, both therefore failed. The client is now part of `attocode_intel`. Set
`OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` in the server environment. A test now
fails if the shipped code imports `eval` or an archived agent package.

## Packaging

The source distribution no longer includes the `evals/` study designs and
results. They remain in the tagged Git repository. The wheel contents are
unchanged apart from the two fixes above and the removal of unused internal code.

Dependencies, ranking and the 100 ms native parse budget are unchanged.

Install with `uv tool install attocode-code-intel==0.1.22`, or upgrade an
existing installation with `uv tool upgrade attocode-code-intel`. Restart the
MCP server after you upgrade.
