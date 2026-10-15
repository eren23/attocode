# Body-file fusion follow-up

The preceding 48 questions are consumed development evidence. Three of their
four top-24 misses had labeled files in retained keyword/body pools, including
one body-rank-two file displaced to final rank 32. This motivates a file-level
fusion trial; it does not justify promoting a known answer directly.

Before scoring, fix exactly one candidate: unique-file RRF over the saved
expanded-query keyword and body lists, keyword weight 1, body weight 2, k=60.
Break score ties by path, retain existing original-query test-intent demotion,
and return at most 24 files. No new retrieval or source access in this stage.
This differs from the earlier 1:1.15 file-fusion trial; it remains a hypothesis,
not a product policy. No weight sweep or post-result alternative candidate.

Development gate, all 48 consumed questions: at least four net additional
labeled Hit@5, gains in at least two repositories, at most two individual Hit@5
losses, no individual Hit@24 loss, and no mean labeled Recall@5 decrease.
If any condition fails, stop this candidate and leave product ranking unchanged.
Do not spend fresh validation questions on a failed development candidate.

If it passes, freeze 24 new source-backed questions before retrieval at the same
six pinned repositories (four per repository, distinct from all consumed
behavior families). Use the existing intent/cross-file/configuration/ambiguous
categories and record non-exhaustive labels plus source hashes. Freeze the
candidate/manifest identity, then evaluate once: at least three net Hit@5 gains
across two repositories, at most one individual Hit@5 loss, zero Hit@24 losses,
no mean labeled Recall@5 decrease, p95 <= max(1.5 baseline, 50ms). All required.
Any passing product option must remain default off. A failed or incomplete gate
cannot enable it. Source packs must remain local-only, at most two/invocation,
64 MiB source each, 180 seconds, 512 MiB managed disk and 1.5 GiB RSS; clean up.

No model requests, cloud rentals, release or default ranking changes in this
follow-up. Initial Rust diagnostics and the bounded Cockroach component profile
are separate from ranking evidence.
