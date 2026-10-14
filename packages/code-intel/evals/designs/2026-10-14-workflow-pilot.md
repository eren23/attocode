# Optional workflow pilot preparation

Status: design only; no agent run, quota check, browser session or model call is
authorized by this document. R7's reviewed STOP remains unchanged. A later user
decision is required before this pilot can be frozen and executed.

The question is whether optional local intelligence improves a useful bounded
workflow after the source-preview, reference-binding and lifecycle repairs.
Passing offline contracts alone does not answer it.

## Scope and selection

Use eight development tasks and exactly sixteen runs: one native and one optional
intelligence arm per task, alternating arm order. Reuse the six public revisions
in `eval/quality/workflows.yaml`; do not create a second corpus. Proposed task mix:

| Task | Repository | Workflow |
| --- | --- | --- |
| 1 | FastAPI | Locate response serialization and explain its validation path with source citations |
| 2 | FastAPI | Plan checks for a response-serialization change, distinguishing evidence strengths |
| 3 | Express | Trace a JSON response from a caller to its implementation |
| 4 | Express | Inspect a controlled source rename across an edit and server restart |
| 5 | TypeScript frontend | Locate class-name composition and its direct consumers |
| 6 | GitHub CLI | Identify version-command registration and candidate tests |
| 7 | ripgrep | Disambiguate the walk-builder declaration from its implementations |
| 8 | Gson | Find long serialization policy and identify source-supported callers |

These tasks are drawn from development fixtures and are not held out. They test
navigation and change planning, not completed bug-fix superiority. Before freezing,
prepare exact prompts and independent answer rubrics from each pinned source,
including more than one valid answer where appropriate. Keep labels out of agent
workspaces. The controlled rename task needs a deterministic patch and checker.
Do not select tasks from observed pilot outcomes or replace failures.

## Freeze and run conditions

Require the local and broad offline gates, the real hosted CI checks, verified
cleanup, and an explicit approved model/client and usage cap. Pin the exact client,
model, engine, tool schema, instructions, source trees, prompts, rubrics and run
order in a signed-by-hash manifest. An unfilled field blocks execution.

Use the same client, model, task prompt, time/token limit and repository copy in
both arms. Native gets native search/read tools; treatment additionally gets the
same optional intelligence profile throughout. Never require a server call to
pass a task. Record natural adoption separately from correctness. No cloud GPU,
model download, API fallback, parallel agent fleet, browser quota automation or
repository test-environment install is needed for these workflows.

Run one pair at a time, delete only its owned scratch after collecting bounded
logs, and stop after the sixteen planned attempts. A failed or incomplete attempt
stays in the report. Infrastructure failure is an incomplete pilot; do not quietly
retry until a favorable sample appears. Preserve original traces and grades.

## Decision rule

Score source-supported task completion blind to arm; report all eight paired
outcomes, elapsed time including setup, tokens/client usage, tool calls and peak
storage. The pilot can justify only another explicitly approved study, not a
release claim. A proposed continuation requires at least two more completed tasks
in treatment, no correctness loss on the others, and treatment/native total-time
and measured-usage ratios no greater than 1.25. Missing usage or invalid grading
makes that decision inconclusive. Zero adoption is reported directly and is not
rewritten as proof of either benefit or harm.
