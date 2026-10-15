# Local expansion and fusion comparison

Frozen before development execution. Development: 14 previously observed
FastAPI/Laravel questions, retaining prior labels and adding the source-verified
HTTPBearer alternative. Validation: 12 new questions in Requests and GitHub CLI,
with multiple relevant file labels where source supports them. The repositories
have prior study exposure; this is not an independent repository holdout.

Three retrieval inputs: current substring expansion, whole-token expansion,
and original query without expansion. Each uses the same warmed index, top_k=24
and unchanged scoring. Retain ordered keyword/body/fused candidate file lists.
For each arm, also compare one offline file RRF with fixed k=60, weights 1/1.15,
and the existing test-demotion policy. This fusion never fetches more candidates.
No hyperparameter search. Expansion comparisons necessarily change candidates;
fusion comparisons use the exact retained lists from their associated arm.

Choose at most one candidate after development: require at least two additional
hit@5 questions over current expansion and no aggregate hit@24 loss. Order
eligible candidates by hit@5, then hit@24, then mean labeled recall@5; ties
prefer existing fusion, then token expansion, then literal input. Record the
choice and development report hash before opening validation results.

Validation accepts the selected candidate only with at least one additional
hit@5 question, at most one individual hit@5 loss, no individual hit@24 loss,
and p95 retrieval latency no greater than max(1.5× baseline, 50 ms). No tuning
after validation. Failure keeps current defaults. Success supports only an
opt-in candidate until broader frozen ranking/release checks support a default
change. Keep uncommitted implementation local.

Bound each invocation to two sequential packs, 64 MiB of source each, 180 seconds,
512 MiB managed disk, 1.5 GiB RSS, no downloads/models, and delete scratch. Retain
only reports. Profile navigation separately on a generated Go workload; preserve
the 180/90-minute cloud deadlines and do not claim Cockroach timing from it.
