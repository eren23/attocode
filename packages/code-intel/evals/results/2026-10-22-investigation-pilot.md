# Investigation pilot: incomplete, expansion stopped

The conditional investigation pilot stopped after its first task pair because
structured-output/tool calls failed the frozen protocol. Two scored attempts
were admitted; fourteen were never launched. Neither scored attempt completed
the study gates. No quality, cost or time benefit is established, and beta
positioning remains unchanged. The earlier R7 stop decision remains closed.

The [machine decision](2026-10-22-investigation-pilot-decision.json) and
[sanitized evidence archive](2026-10-22-investigation-pilot.tar.gz) retain the
incomplete outcomes. Archive SHA-256:
`3ddbd267583d793ef3153e88760ae5aaebe751501e2cde7f1d7ba9530324dd24`.

## Frozen design

After verified publication of 0.1.14 at
`08319af02eeee95b88978dd126e392fec67719de`, eight composite investigation tasks
were frozen across pinned FastAPI, GitHub CLI, Requests and Phoenix sources.
Each requested an implementation, a cross-file caller, an existing regression
test and a justified negative control. Independent source review bound 73
anchors in 22 files before client outcomes. The I07 primary investigation was
new, but one supporting caller/function anchor had been consumed previously;
that overlap was disclosed before launch. Supporting spans are not all fresh.

Both arms used Claude Code 2.1.287 and the observed model identity
`claude-sonnet-5-5`, with native Read/Grep/Glob and structured serialization.
The optional Attocode arm additionally advertised the 16 daily MCP tools from
the released source; using them was not compulsory. Inputs, client, dependencies,
operators and source snapshots were frozen. Prompts and labels for unlaunched
tasks are not exported.

Limits were two workers, 180 seconds end to end per attempt, a shared 50-minute
window, 2 GiB managed disk and aggregate RSS, at most 16 scored requests and two
excluded wiring requests. Admission reserved $0.45 per request within the $10
pilot allowance. Retries and replacements after an outcome were forbidden.
Expansion required at least two additional independently fully correct answers
and aggregate reported-cost and end-to-end time ratios each at most 1.25.

## Observed execution

Both excluded wiring checks passed. Each observed the expected client/tool
inventory, denied the owned outside-root Read canary without returning its
contents, and produced a valid synthetic answer. These checks are excluded from
quality and paired cost/time comparisons.

The first scored pair was I07, a Phoenix cache-policy investigation:

| Attempt | Observed outcome | End-to-end observation | Reported cost |
| --- | --- | --- | --- |
| Attocode available | Incomplete: first structured-output call malformed; corrected final answer does not override protocol failure | 35.517 s | $0.081174 |
| Native | Incomplete: malformed output and four unavailable pseudo-tool calls; interrupted when the other worker failed | 35.745 s to cancellation | Unknown |

The Attocode-available client made six native read/search calls and **zero MCP
calls**. Its first serialization call supplied unexpected root properties and
string values where nested role objects were required. The client rejected it,
then accepted a corrected serialization. The final answer passed schema and
exact-source-quote checks. The frozen auditor nevertheless validates every
`StructuredOutput` call and rejects the earlier malformed arguments, so the
worker returned incomplete. Final schema/quote validity is not
a semantic correctness grade.

The native trace also contains a malformed serialization call. It then invoked
unavailable tools named `caller`, `regression_test`, `negative_control` and
`uncertainties`; the client explicitly rejected all four. The controller stopped
the active pair after the first worker failure. Native has no terminal result
or reported total cost. A low-level supervision status does not establish study
completion. No additional client call, retry or replacement followed.

These traces establish a client/model serialization and study-protocol failure
boundary. They do not establish its underlying cause or a server defect. In
particular, the Attocode-available run did not exercise an MCP operation.

## Decision, accounting and evidence limits

The frozen summary is incomplete. Quality delta and both paired ratios remain
null. No semantic grades were assigned: one mechanically valid final answer
cannot satisfy an eight-pair study. Only I07 was exposed to scored clients; the
other seven tasks were not run and are not replacement attempts for this study.

Known reported costs, including both excluded wiring checks, subtotal
**$0.1823414**. This is partial accounting; the interrupted native cost is unknown,
so total cost is unknown. Subscription extra usage was off at preflight.
API-equivalent reported cost is not an invoice. No further pilot spending is
authorized by unused reservations. Remote performance allocation earlier in the
plan started no worker; its estimated compute cost remains $0, invoices unchecked.

The scored controller sampled peak aggregate RSS of approximately 731 MiB and
managed storage of 86.8 MiB. Owned temporary repositories were removed; the
independent audit found no owned pilot process. Frozen source/input/operator and
client identities match. Both scored failures occurred before the final
temporary-source hash checks, so their unchanged temporary-copy identity is not
claimed. Read-only post-run audit imports accidentally created two bytecode files;
those additions were preserved separately, and original frozen identities were
restored and verified. Operator source and raw attempts were unchanged.

Raw events, failed attempts, initial preparation/export errors, subscription
evidence and private answer mappings remain local. The archive exposes structural
tool-call summaries, accounting, resource observations and immutable evidence
hashes; it excludes raw answers, private paths and unlaunched prompts/labels.
After extracting it, `python replay.py` verifies archive member hashes and
recomputes the incomplete accounting/protocol observations. This is not a replay
of semantic grading or a new model run.

The approved local-first batch closes with 0.1.14 published, the restart shortcut
withheld without a matched measurement, the callback-span candidate rejected on
consumed development, and this pilot incomplete. Native cold-parse and Rust
readiness causes, restart cost and first-page relevance remain open. No default
ranking, profile, embedding or model policy changes follow from this pilot.
