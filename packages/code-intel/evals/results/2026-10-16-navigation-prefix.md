# Navigation phrases: one rejected search candidate

**Decision: keep current search behavior.** Removing a leading navigation phrase
failed the development gate and produced no labeled coverage gain on twelve fresh
questions. The candidate remains evaluation-only; no product query normalization,
ranking weights, model default or release changed.

## Diagnosis and frozen candidate

The two consumed cross-file sets from [the audit](2026-10-16-cross-file-audit.md)
and [the deeper-page fix](2026-10-16-deep-page-diversity.md) contain twelve
questions and 25 labeled file-question pairs. On merged main `85b41da`, twelve
labels were outside the first five. **Eleven of those twelve were already in the
fused candidate pool**; only one was absent from that request's retained pool.
This identifies ranking as the predominant limitation for these examples, not
proof of a general indexing or retrieval failure.

A visible distraction was `Trace.scala` ranking first for questions starting
“Trace how…” about sleeping or random identifiers. The fixed candidate removes
one leading `trace how`, `explain how` or `show how` phrase, optionally preceded
by `please`. It preserves interior tracing terms, exclusions, symbol queries,
scoped queries and explicit test queries, and refuses an empty lexical remainder.
It is intended only for unscoped, provider-free lexical search. It does not strip
arbitrary verbs or globally remove the word `trace`.

The [development design](../designs/2026-10-16-navigation-prefix.json) froze this
rule and its gate before measurement. Adoption required at least two net extra
labeled pairs at five, improvement on two questions across two repositories,
no individual any-label Hit@5 loss, no individual label loss at 24, nondecreasing
mean labeled recall, and p95 latency below the larger of 1.5 times baseline or
50 ms. Both stages use twelve questions. No tuning or replacement candidate
followed either measurement.

## Results

| Measurement | Development baseline | Development candidate | Fresh baseline | Fresh candidate |
| --- | ---: | ---: | ---: | ---: |
| Any labeled file in first five | 11/12 | 10/12 | 11/12 | 11/12 |
| All labeled files in first five | 2/12 | 2/12 | 8/12 | 8/12 |
| Labeled file-question pairs in first five | 13/25 | 12/25 | 19/24 | 19/24 |
| All labeled files at 24 | 10/12 | 10/12 | 11/12 | 11/12 |
| Labeled file-question pairs at 24 | 22/25 | 22/25 | 23/24 | 23/24 |
| p95 of per-question median search time | 28.69 ms | 28.81 ms | 31.49 ms | 30.88 ms |

The development gate failed even though its aggregate depth-24 count stayed
constant. Removing the prefix moved ripgrep's multiline entry point from fifth
to sixth, losing an any-label Hit@5. Cats Effect's execution-context question
lost `IOFiber.scala` from the retained pool after having delivered it at 13.
The secure-identifier question gained `UUIDGen.scala` at five, previously six.
These outcomes do not support enabling the candidate.

As specified before development measurement, a failed candidate could receive
one fresh diagnostic, without eligibility for adoption. The [fresh manifest](../designs/2026-10-16-navigation-prefix-validation.json)
contains twelve new source-reviewed questions, eight with eligible phrases and
four unprefixed controls, each with two labeled files. They cover pattern input,
JIT options, statistics, ignore rules, cache completion, connection health,
interceptor contracts, URL normalization, actual trace rendering, fiber locals,
keyed locks and racing effects. The four controls retained identical file and
stage orders. The real tracing question kept its interior `trace` terms and
both labels at ranks one and three. No fresh question gained labeled coverage
at five; the improvement gate failed independently of the earlier rejection.

This was not a successful held-out validation or a rescue of a failed candidate.
The original diagnostic request and its source labels are fixed; the candidate
cannot be adopted from these results. All 24 questions are now consumed evidence.

## Method, provenance and resource limits

The [evaluation-only operator](../../../../eval/quality/navigation_prefix_trial.py)
uses a single warmed index per pack. It evaluates both queries three times in
alternating order and requires stable file order across repeats. Normalization
changes query terms and therefore candidate generation: this is a comparison on
the same index, **not identical candidate pools**. The [raw JSON](2026-10-16-navigation-prefix.json)
retains every query, label, expanded query, keyword/body/fused file order, timing
sample, gate result, revision and source hash. Twenty-two contract checks cover
phrase scope and reject missing pairs, duplicate IDs, lost labels, excessive
latency and gains confined to one repository.

- Development design SHA-256: `a371606cc2d324e50a464442506f5d3f57a470bb016e665b67118e47ad2920ec`.
- Fresh questions SHA-256: `b71b616b1c3ecb36d83f89956a67e19ac80c564964c6b238780730f7239872f5`.
- Product/evaluation source fingerprint: `5f5943dc4cd26a536725df8b3db4590ced56277d8a8dd930d0ef69829c10c1a2`.

Six sequential pack runs took **15.509 seconds**, peaking at **38.2 MiB managed
disk** and **106.4 MiB sampled RSS**. Each had a 180-second deadline, 512-MiB disk
and 1.5-GiB RSS limit; materialized source was capped at 64 MiB. All scratch was
removed. Cached pinned ripgrep, OkHttp and Cats Effect inputs were read-only;
there were no downloads, models, cloud workers or agent trials.

Labels are non-exhaustive source judgments by the implementing agent. Repositories
and some files were exposed before, even though the fresh questions were frozen
before retrieval. The fresh set is easier for this baseline than the development
set; comparing those baseline percentages does not measure product improvement.
These small offline observations do not estimate general usefulness or agent
completion. Rust intermittency and Cockroach headroom remain separate open work.

## Implementation checks

The bounded local gate passed **741 tests**, with nine explicit environment
skips, plus Ruff, scale and lifecycle checks. It took 43.210 seconds and peaked
at 127.2 MiB managed storage. Run `20261016T122915-1d0beeca`; test fixture hash:
`bfd74deb68c514da535ed84e3fa2ff80a77c1d58aa148a4fa01a0060194fdfa2`.
The 22 new acceptance checks are included in that gate. Product source is
byte-for-byte unchanged from `85b41da`. Upstream ranking, PostgreSQL and the
remaining required checks must pass before merging this evidence and harness.
