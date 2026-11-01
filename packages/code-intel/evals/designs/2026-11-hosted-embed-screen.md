# Hosted embedding screen (stage 1 of 2)

The miss census of the test-recall trial found 7 of 12 judged test misses outside
the candidate pool. In these misses, the question words do not occur in the code.
A rerank only reorders the pool, so it cannot fix them. A dense embedding of code
can match meaning without shared words. The 2026-10-18 re-measure showed this
offline: CodeRankEmbed on function units gave Acc@5 .739 against .566 for the
product on Loc-Bench. That model needs a GPU, and the CPU cost test failed
(2026-10-19). This screen asks if a hosted code embedding gives a similar gain.

## Stage 1: this screen

- Tasks: 50 Loc-Bench V1 tasks, a seeded sample (seed 20261101) of the 560 that
  the 2026-10-18 re-measure used. The JSON design freezes the dataset revision,
  the population hash, each task (repository, commit, tree, gold files, query
  hash) and the product and fn-dense file lists of the retained private run.
- Units: `eval.matrix.function_dense.ours`, the function and method units of the
  re-measure. The first 3,584 characters of each unit and query.
- Models, through OpenRouter: `voyageai/voyage-code-4` and
  `mistralai/codestral-embed-2505`. Each model has a spend limit in the design;
  the harness stops its requests at that limit. The request asks providers not
  to keep the data, if the provider accepts that field.
- Score: cosine rank of the units, then files in first-occurrence order. The
  fused list is `eval.matrix.arms.rrf([product, model])`, the rule of the
  re-measure. Acc@5 is `eval.matrix.function_dense.acc`.
- Gates (all required for one model): at most 2 incomplete tasks (an incomplete
  task counts as a miss); fused Acc@5 hits minus product hits >= 5 (+0.10); a
  one-sided exact sign test on the discordant tasks, p <= 0.05. Among passing
  models, the winner has the most fused hits, then the most model-alone hits,
  then the lower spend.
- One dispatch of `.github/workflows/embed-screen.yml`. A fix and a new
  dispatch are allowed only if the run stops before the first scored request.
  No tuning after the run. The Loc-Bench queries are public, and the model can
  know these public repositories; the screen is development evidence only.

## Stage 2: only for a passing model

Build a product opt-in (off by default, consent like the hosted rerank) with
the winner frozen. Then run a development screen and one fresh validation on
new source-checked questions, with gates frozen before any call. If no model
passes stage 1, stop and publish the rejection.
