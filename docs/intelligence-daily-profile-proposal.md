# Experimental seven-tool local profile

Drafted 2026-10-13 at checkout `73826f0`, after R6. Implemented locally as opt-in `lean`; it has not been released.
The default remains `daily`. Remote profiles remain `daily` and `full`.

## Decision

The watched local `lean` profile advertises seven tools: `bootstrap`, `search_symbols`,
`inspect_symbol`, `semantic_search`, `impact_analysis`, `suggest_tests`,
and `capabilities`. Keep the current `daily` and `full` profiles available
while the experimental profile is evaluated. A smaller schema is a context
budget change; improved task outcomes need separate evidence.

The evidence does not identify a statistically optimal tool list.
In the R2 natural-use arm, agents called the server in 4/58 runs, with
one `bootstrap` call in each. R3 forced search and found no localization
gain. R4 Stage 1 and R6 each had 87 server-assisted review runs; all made
only the required `suggest_tests` call. Those review studies cannot tell
us what agents would choose without a forced call, and non-use does not
prove a tool has no value on edits or deeper investigations.

Sources: [R2](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-10-agent-pilot.md),
[R3](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-10-agent-r3.md),
[R4 Stage 1](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-12-r4-stage1-review-agents.md),
and [R6](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-13-r6-review-test-note.md).
The R2 natural-call counts were also checked against the external
`studies/r2-pilot/runs.jsonl` artifact.

## Keep seven

| Tool | Reason to keep it in the experiment |
|---|---|
| `bootstrap` | One entry point for an unfamiliar behavior; the only tool naturally chosen in R2. |
| `search_symbols` | Find a definition when the name is known approximately. |
| `inspect_symbol` | Inspect a known definition with source, references, imports and candidate tests. |
| `semantic_search` | Find candidates when a task gives behavior rather than an identifier. |
| `impact_analysis` | Check possible dependencies before an edit. Its value on completed fixes is unproven. |
| `suggest_tests` | Offer optional test candidates with explicit evidence and completeness limits. R5 supports the helper against a filename baseline; R6 does not show an agent-review benefit. |
| `capabilities` | Report the active profile, coverage, limits and the explicit route to advanced tools. |

These are distinct entry points for finding, inspecting and changing
code. `impact_analysis` and the two lookup entry points are retained
because the proposed experiment includes edits; their retention is a
design judgment, not a result from the review studies.

## Leave nine in the full profile

| Tool | Tradeoff |
|---|---|
| `project_summary` | `bootstrap` already includes a summary. A dedicated summary remains useful in full. |
| `explore_codebase` | Start with `bootstrap` and native directory reads; deeper structured exploration stays in full. |
| `relevant_context` | Overlaps the behavior and symbol entry points; context bundling stays in full. |
| `symbols` | Exact file symbol listings stay in full; name discovery remains in `search_symbols`. |
| `fast_search` | Native Grep and Glob cover literal searches; advanced server search stays in full. |
| `cross_references` | `inspect_symbol` gives a bounded initial reference set. Exhaustive pagination and specialized reference queries stay in full. |
| `dependencies` | `inspect_symbol` gives some imports, but does not replace a file dependency graph. The dedicated graph stays in full. |
| `call_graph` | Deeper call tracing stays in full; inspection and impact candidates are not equivalent substitutes. |
| `review_change` | This composite workflow has no demonstrated incremental agent benefit in the recorded studies. Keep it available in full. |

This is an advertisement change, not deletion of analysis operations.
The implementation must make the advanced route explicit. Clients must
not be promised that ToolSearch can reveal a tool absent from `tools/list`.
For the initial experiment, advanced tools require an explicit full-profile
session; the harness does not switch profiles during a scored attempt.

## Measured schema budget

Measured without a model request, using the actual watched local MCP
surface, `OperationGateway(profile='daily').catalog(mcp=True)`.
`tool_catalog('daily')` alone returns 19 entries before gateway filtering;
it is not the agent-facing count. The gateway hides `hydration_status`,
`cross_repo_search`, and, when watching, `notify_file_changed`.

| Surface | Advertised tools | Serialized tool-definition characters |
|---|---:|---:|
| Current watched local daily | 16 | 10,576 |
| Implemented watched local lean | 7 | 4,737 |
| Reduction | 9 | 5,839 (55.2%) |

Serialization is one compact JSON array of
`tool.model_dump(mode='json', exclude_none=True)`, with
`ensure_ascii=False` and separators `(',', ':')`. These character counts
include tool schemas, descriptions and annotations, but exclude server
instructions, client wrappers and provider prompt formatting. They are
not Claude token counts. Instruction edits could change the final budget.

Reproduce from the repository environment:

```python
import json
from attocode_intel.gateway import OperationGateway

tools = OperationGateway(profile='daily').catalog(mcp=True)
def size(items):
    return len(json.dumps(
        [tool.model_dump(mode='json', exclude_none=True) for tool in items],
        ensure_ascii=False, separators=(',', ':'),
    ))
print(len(tools), size(tools))
lean = OperationGateway(profile='lean').catalog(mcp=True)
print(len(lean), size(lean))
```

## Implementation contract

- Add an explicit experimental profile; preserve current defaults,
  remote tools, ranking and candidate selection. Update CLI/installer
  profile validation and generated documentation consistently.
- Make its instructions conditional: if the agent chooses the server,
  route a known name to inspection and unfamiliar behavior to bootstrap
  or search. Do not require a first server call or duplicate instructions
  in a Claude guidance file. Keep provenance and incomplete-coverage caveats.
- Keep the default 2,000-token response budget and the evidence/note
  fields of test suggestions. The note must not imply that suggestions
  are sufficient to validate a patch.
- Make `capabilities` distinguish advertised tools from advanced tools.
  In lean it uses the actual MCP list and gives advanced tools separately,
  with an explicit full-profile restart requirement.
- Reconcile follow-ups with the advertised list. In particular,
  `inspect_symbol` puts deeper reference/import queries in `advanced_follow_up`
  with the full-profile restart requirement. Inspection pagination stays available.
- With watching disabled, advertise `notify_file_changed` as an eighth
  tool and retain the manual freshness instructions. The seven-tool
  budget applies to watched local sessions only. Verify edits become
  visible in both modes.
- Verify actual `tools/list`, callable operations, instructions,
  capabilities, follow-ups and freshness agree before freezing a pilot.
  Existing focused checks include `test_compact_inspection.py`,
  `test_daily_workflows.py`, `test_doctor.py`, and `scripts/check_wheel.py`;
  add meaningful coverage for the new profile when implementing it.

## Evaluation and default decision

The [R7 pilot draft](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/designs/2026-10-13-r7-task-completion-pilot.md)
compares native tools with this optional seven-tool package on completed
bug fixes. It deliberately does not isolate the effect of tool count
from conditional instructions, or compare seven tools against sixteen.

A positive pilot permits planning a fresh held-out study; it does not
justify a default change or performance claim. If the question later
becomes whether seven tools outperform sixteen, preregister that direct
comparison separately. The user retains the daily-list decision.

Use this checkout with `attocode-code-intel init --client claude --profile lean`,
then restart the client. `doctor` probes an advertised tool in each profile.
Legacy SSE and remote lean are rejected because they cannot offer this surface.
The [R7 design](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/designs/2026-10-13-r7-task-completion-pilot.md)
uses adoption descriptively; there is no minimum adoption gate.
