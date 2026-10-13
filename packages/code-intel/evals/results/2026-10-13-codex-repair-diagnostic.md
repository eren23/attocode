# Codex repair diagnostic: wiring works, both arms resolve both tasks

Completed the authorized six model attempts: two excluded wiring checks and
four exploratory repairs. Native and optional lean each resolved both prepared
development tasks. Neither optional repair called MCP. These results demonstrate
working Codex execution and grading; they do not demonstrate an intelligence
benefit, a tool-list advantage, or a difference between models.

Study: `~/Documents/AI/attocode-evals/matrix/studies/codex-repair-smoke`.
Frozen id: `af58925e1df670347a6d7a10244517acbb116c223709a9a4309e14f1fd4359b5`.
Protocol: [bounded diagnostic design](../designs/2026-10-13-codex-repair-diagnostic.md).
Private `summary.json` contains the machine-readable reviewed results; each
attempt retains its raw events, patch, quota observations, grade and review.

## Repair results

| Task | Arm | Required checks | Model seconds | Setup seconds | Total seconds | MCP calls |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Astropy 6938 | Native | 13/13 passed | 183.70 | 1.27 | 197.35 | 0 |
| Astropy 6938 | Optional lean | 13/13 passed | 105.11 | 21.08 | 138.27 | 0 |
| Seaborn 3010 | Optional lean | 3/3 passed | 146.80 | 5.56 | 160.23 | 0 |
| Seaborn 3010 | Native | 3/3 passed | 183.33 | 1.24 | 192.77 | 0 |

All four completed normally without timeout or quota error. Independent grading
restored official test paths, applied immutable official tests, and observed
every required F2P/P2P case passing with a zero test-command exit. All command
and completed file-change traces plus full patches received operator review;
no access to private inputs or infrastructure edits was found. Host trace
review is not OS isolation from private data.

Model seconds cover CLI execution. Setup includes Docker startup, instruction
and quota probes, and lean indexing; total includes setup, execution, grading,
post-run quota observation and cleanup. Lean warm-up took 19.78 seconds on
Astropy and 4.38 seconds on Seaborn. Both arms used fresh source copies; OS
caches and provider caching were uncontrolled. One attempt per task/arm and
zero optional MCP calls prevent attributing timing differences to intelligence.

The agents also tried broader tests. Astropy/native reported full-disk warning
failures, and both Seaborn attempts encountered plotting/environment failures.
Those broader attempts are retained in raw traces and are not claimed as full
suite passes. Benchmark acceptance is limited to the required lists above.

## Wiring and usage

Native wiring passed in 23.40 model seconds; lean wiring passed in 33.90 seconds.
Both changed a disposable fixture and passed its Docker assertion. Lean also
received a real `inspect_symbol` answer. A model-free transport check verified
the exact seven advertised lean tools. Both wiring traces were reviewed before
repairs began. The required wiring call is excluded from natural adoption.

| Repair arm | Input tokens | Cached input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| Astropy/native | 517,452 | 474,240 | 3,346 |
| Astropy/lean | 236,539 | 202,240 | 2,488 |
| Seaborn/lean | 300,768 | 235,776 | 2,481 |
| Seaborn/native | 395,837 | 353,920 | 3,163 |
| Repair total | 1,450,596 | 1,266,176 | 11,478 |

These are CLI-reported counters, not a dollar estimate. Cached input is not
added to input again. Including excluded wiring, the six requests reported
1,586,955 input, 1,355,392 cached input and 12,221 output tokens. No USD estimate
was supplied by Codex.

ChatGPT Pro authentication and included quota were verified through the
[official Codex account API](https://learn.chatgpt.com/docs/app-server).
The signed-in UI showed automatic reload off, with existing credits available.
Every before/after observation and the final fresh account check showed the
same credit balance; the weekly usage meter remained 3% used. This is observed
account state, not a provider-enforced guarantee against credit spending.
No credits were purchased or reset used; no billing setting was changed.

## Reproducibility and limits

Codex CLI 0.162.1 requested the configured `gpt-6.1-sol` at high reasoning and
default service tier. No API-key fallback or model replacement was used. The
first two already-prepared R7 tasks were selected before results, with fixed
native/lean then lean/native order. All eight image/mounted-source base/gold
controls passed with exact-input cache identities validated by the strict
frozen worker. There were no retries, replacement tasks or additional runs.

Project guidance suppression alone still loaded the global AGENTS file.
A private disposable client home reused the existing login and produced an
empty instruction-source list in model-free probes. Personal instructions were
unchanged; the temporary login symlink was removed after completion. Personal
skills, plugins, apps, hooks, memory, goals and delegation were disabled per
invocation. Optional lean instructions were injected explicitly, so this is an
adapted Codex diagnostic rather than an identical R7 treatment.

Local quota/configuration/wiring guards and strict repair tests passed: 33 tests.
Scoped Ruff and whitespace checks passed. The working driver has an import-only
Ruff cleanup after freeze; reproduction uses the archived frozen harness.

Claude R7's engine, harness, manifest, private pack and source hashes were
revalidated unchanged. It remains at 0/32 scored attempts, waiting for the
authorized post-reset launch. No ranking/tool default, release, commit or PR
was made. This diagnostic is complete and does not authorize expansion.
