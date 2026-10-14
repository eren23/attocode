# R7 completion pilot: no demonstrated benefit; stop expansion

All 32 predeclared scored attempts completed after the verified quota reset,
without retries, replacement tasks, timeouts or infrastructure failures.
After host-command scope review, native resolved **14/16 (87.5%)** and optional
lean resolved **13/16 (81.25%)**. The paired mean resolution difference was
**−0.0625**, below the predeclared +0.125 continuation threshold. The
failure-penalized time ratio was **1.330**, exceeding the 1.25 bound. The
reviewed continuation decision is **stop**.

None of the 16 treatment runs called MCP, although all 16 CLI initialization
events reported the server connected. This study does not demonstrate an
intelligence benefit or establish that the smaller tool list is optimal.
Eight development tasks and two trials per arm do not establish a general
quality difference between the setups.

Study: `~/Documents/AI/attocode-evals/matrix/studies/r7-pilot-v2`.
Frozen identity: `bbdc42518d1b103bf77be381726cc1ebb417c1c2a888579c5f5ba11acec5d163`.
Protocol: [R7 design](../designs/2026-10-13-r7-task-completion-pilot.md).
Model: `claude-sonnet-5-5`, Claude Code 2.1.287, existing signed-in subscription.

## Reviewed outcomes

Each task has two attempts per arm. Scores require every recorded F2P and P2P
case to pass in the independent pinned evaluator, with no missing or skipped
required case and a successful test-command exit.

| Prepared task | Required checks per attempt | Native resolved | Lean resolved |
| --- | ---: | ---: | ---: |
| Astropy 6938 | 13 | 2/2 | 2/2 |
| Seaborn 3010 | 3 | 2/2 | 2/2 |
| Xarray 4248 | 19 | 0/2 | 0/2 |
| SymPy 21627 | 27 | 2/2 | 1/2 |
| Matplotlib 25433 | 56 | 2/2 | 2/2 |
| Django 14787 | 21 | 2/2 | 2/2 |
| Flask 5063 | 56 | 2/2 | 2/2 |
| Scikit-learn 13779 | 20 | 2/2 | 2/2 |
| Total | | 14/16 | 13/16 |

Of 16 trial pairs, 13 passed in both arms, two failed in both arms, and one
passed only in native. Seven task-level differences were zero; SymPy's was
−0.5, producing the overall −0.0625 difference. These are descriptive
development results, not proof of a general native advantage.

The four Xarray submissions failed the required
`test_inline_variable_array_repr_custom_repr` case. The public request asks
for units in the overview; the official acceptance test checks a custom-array
`_repr_inline_` hook. The submitted patches implemented attribute-based units
display instead. These failures describe that specific benchmark criterion,
not an exhaustive judgment of every implementation of the feature request.
One SymPy lean attempt also failed the existing `test_Abs` regression case.
All five failures remain failures; no submission was repaired or rerun.

## Scope review and the frozen automatic summary

The frozen runner conservatively flagged **23/32** traces as `needs_review`,
including multi-command Docker wrappers, output-filtering pipelines, and
Python/sed scripts that edited public source as text. Its raw result records
withhold resolution credit for these flags, even when independent tests pass.
Consequently the unchanged frozen `summary.json` reports an **inconclusive**
automatic gate. It must not be presented as the reviewed outcome table above.

Every run's tool paths, complete shell commands and submitted patch received
operator scope review under the same rules in both arms. The flagged host
scripts performed public workspace reads/edits; repository imports and test
execution used the unchanged Docker helper. No access to private benchmark
inputs, direct Docker-resource inspection, online solution retrieval,
delegation, infrastructure edits or grader weakening was found. Official test
paths were restored by the independent evaluator before trusted tests ran.
This is host trace review, not OS isolation from private inputs.

Separate `operator-review.json` annotations bind each decision to hashes of
the original result, event stream, patch and independent acceptance. The
`operator-analysis.json` report and `operator-reviewed-runs.jsonl` apply
those scope decisions and preserve actual test/execution failures. No original
flag, grade, submitted patch, frozen input or automatic summary was rewritten.
The same predeclared gate applied to these reviewed rows says **stop**; the
automatic gate remains inconclusive. Neither supports expansion.

The archived `operator-analysis.py` makes this separate calculation
reproducible; its SHA-256 is
`f51fe364639bb7c7505940c1efccfd56a8d1f006da315938c28d636ec9469885`.
It validates all 32 scheduled identities, review hashes and pinned patch/image
acceptance identities before calculating scores.

## Time, usage and gate

| Metric | Native | Optional lean |
| --- | ---: | ---: |
| Mean model phase | 30.73 s | 33.75 s |
| Mean setup/index time | 0.15 s | 24.99 s |
| Mean end-to-end time | 49.15 s | 76.75 s |
| Mean failure-penalized model time | 102.53 s | 136.35 s |
| Recorded subscription-usage estimate | $1.130952 | $1.315107 |
| Naturally chosen MCP calls | 0 | 0 |

Scored usage estimates total **$2.446059**, or **$2.5406314** including the
previously completed excluded wiring checks. These are client estimates for
subscription usage, not a claim of actual API billing or paid-credit spending.
No cost was missing or imputed. The scored cost ratio was **1.163**, below the
1.25 bound; resolution and failure-penalized time failed their bounds.
Setup/index time is separate from the model-phase gate. End-to-end includes
setup, execution, independent grading and cleanup.

| Continuation condition | Observed | Met? |
| --- | --- | --- |
| Resolution difference ≥ +0.125 | −0.0625 | No |
| Mean cost ratio ≤ 1.25 | 1.163 | Yes |
| Failure-penalized time ratio ≤ 1.25 | 1.330 | No |
| Complete reviewed inputs/grades | 32/32, all review hashes validated | Yes |

Adoption is descriptive and was not added as a continuation requirement.
Successful forced MCP use in excluded wiring is not natural-adoption evidence.
All 16 treatment sessions connected successfully, so zero calls is not a
missing-server observation. It does not establish why agents chose native
tools, that the unused tools are useless, or a causal explanation of the
one discordant outcome.

## Execution and preserved state

At launch, the fresh signed-in account view showed weekly 0% used, session 2%
used and usage credits off. The real post-reset observation was recorded
once; all launches stayed inside its one-hour freshness window. The user
subsequently requested no further browser quota checks, which were stopped.
No post-run account observation is claimed. No billing setting was changed.

The guarded launcher used two workers with 600-second model limits and a
50-minute scheduling window. It finished all attempts in one session, well
below the $20 cumulative estimate cap. The original manifest, engine,
harness, private pack and public source hashes revalidated unchanged. R7
uses recorded Homebrew Cargo 1.94.0; R6's different Cargo path is not applicable.

Artifacts remain private beside the frozen study: launch log, all original
results/events/patches/acceptances, original `summary.json`/`runs.jsonl`, 32
operator review annotations and separate reviewed analysis. No further R7
runs, wording retries, task substitutions or larger study were started.
Daily/full defaults and the optional lean profile are unchanged. The next
decision is not an automatic expansion: this pilot failed its screening gate.
