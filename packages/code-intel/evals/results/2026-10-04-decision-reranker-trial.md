# Jev-style and local code-search reranking trial

**Status: exploratory, uncommitted, not wired into code intel.** The strongest
result was a single Jev `choice` decision over twelve candidate files. It
improved the known-target first-five ranking across the fixed public-repository
packs. The local models tested here did not generalize as well on this CPU.

## What was compared

The [trial harness](../../../../eval/model_rerank_trial.py) reuses the frozen
candidate orders and source-bound judgments from `eval.ranking_pair` (removed
after commit `5b67651`). It checks
each repository's HEAD and tracked-file cleanliness, reads source without
reindexing or writing to the benchmark repositories, and gives every arm the
same query-focused, 1,350-character excerpt per candidate. Up to twelve distinct
files are available to each arm; a reranker cannot retrieve a missing file.
The baseline is the first-occurrence file order before the experimental broad
lexical promotion, equivalent to the current default file order at this level.

The evaluated packs are the 20-case final lexical holdout (Faker, Starship,
spdlog, Protobuf, Prisma), the separate 20-case external pack (Express,
Requests, Vapor, Phoenix, ripgrep), and sixteen cases from the earlier pack
(FastAPI, pandas, Redis, gh-cli). The current attocode working repository was excluded
from all remote calls. All source repositories had matching revisions and no
tracked edits. These are pre-existing, narrow target-file labels—not exhaustive
relevance judgments or real developer-task outcomes. We had looked at three
cases in the first pack before settling on `choice`, so the pooled result is
not a fresh blind model-selection holdout.

| Pack | Baseline MRR@5 | Jev choice MRR@5 | Wins / losses | Median API inference |
|---|---:|---:|---:|---:|
| Final lexical pack, 20 | 0.423 | 0.667 | 8 / 0 | 368 ms |
| External pack, 20 | 0.596 | 0.825 | 9 / 1 | 366 ms |
| Additional public pack, 16 | 0.391 | 0.750 | 7 / 0 | 363 ms |
| **Pooled, 56 queries / 14 repositories** | **0.475** | **0.747** | **24 / 1** | **368 ms** |

Pooled labeled-file recall@5 was 0.554 → 0.661; labeled-file recall in the
twelve-file candidate pool was 0.670 and is unchanged by reranking. There
were zero failed Jev calls. A 20,000-draw repository-cluster bootstrap put the
observed MRR@5 difference at +0.188 to +0.356 (95% percentile interval).
That interval describes these sampled repositories; it is not a guarantee
for private codebases or newly authored queries.

Jev used the code's existing OpenRouter decision endpoint and default
`typesafe/jev-1.13` model, with one typed `choice` call per query. The only
measured labeled loss was Requests “cookie merging”: Jev ranked
`src/requests/sessions.py` ahead of the labeled `src/requests/cookies.py`.
The sessions file really calls `merge_cookies` while preparing requests, so
this is also a clear example of incomplete target labels. We did not alter
the judgment after observing the result. API billing/token usage was not
captured; inference timing excludes candidate retrieval.

## Local models on the same task

| Model and scoring form | 20-case final MRR@5 | 20-case external MRR@5 | Median inference in final pack | Judgment |
|---|---:|---:|---:|---|
| Baseline order | 0.423 | 0.596 | — | Reference |
| MiniLM cross-encoder, independent pairs | 0.527 | 0.408 | 212 ms | Fast, but external regression |
| GTE ModernBERT 149M cross-encoder, independent pairs | 0.481 | 0.425 | 3.14 s | External regression, slow here |
| Decision 2.0 Kai 0.6B, one `choice` | 0.435 | not run | 10.64 s | Little gain on this CPU |
| Qwen3-Reranker 0.6B, independent pairs | 0.400 on three cases | not run | 21.38 s for six files | One win, two losses; CPU nonstarter |

The full 20-case Kai trial had five MRR wins and two losses; the three-case
Qwen trial had one win and two losses. They are not equivalent sample sizes.
MiniLM and GTE both demoted Starship's correct `src/config.rs` for “config
loading”; Jev's `choice` preserved it. Local timing is on this session's CPU
(`torch.backends.mps.is_available() == False`), after model load, without
concurrent local inference. Qwen's 384-token pair cap can truncate the shared
excerpt. All model weights were downloaded or read locally; only the Jev arm
sent bounded excerpts to an external endpoint, with an explicit CLI switch.

Model revisions used: MiniLM `c5ee24cb`, Qwen3 `e61197ed`, Decision Kai
`cd49ea38`, GTE ModernBERT `f7481e60`. The Decision package's verified
manifest SHA-256 was
`ca7bf2cff1494a5bfc51f4271f52557da0f3ce3b6f0f6e7a2b4118cb4965e92e`.
The newer Decision runtime dependencies were installed only under
`/private/tmp/attocode-decision-deps`, not into the project environment.

## Model-family fit

The [Decision 2.0 collection](https://huggingface.co/collections/vllm-sr/decision-20)
contains Kai 0.6B, Eos 0.8B, Sol 2B, Nox 4B, Lux 9B, and Vega 27B. They
offer typed yes/no, choice, and score decisions; their published general
decision results do not establish source-code ranking quality. We ran Kai,
the smallest member. [Clef-Flash](https://huggingface.co/Cloudflare/clef-flash)
is 9B and [Clef](https://huggingface.co/Cloudflare/clef) is 27B; both add
image/video evidence, which could help visual repository tasks but is
overkill for text-only file ranking on this CPU. The
[Bosun v3.1 family](https://huggingface.co/blog/Hanno-Labs/decisionbench-bosun-v3-1)
has 0.6B/1.7B Jev-compatible local options worth testing on a GPU.
Code-specific [CodeRankEmbed](https://huggingface.co/nomic-ai/CodeRankEmbed)
is a bi-encoder for candidate retrieval rather than this shortlist decision;
it may address the 33% labeled-file recall gap before reranking.

## Decision

Do not switch on a reranker by default from this trial. Jev `choice` has a
substantial and cross-repository target-ranking signal, but a product path
needs explicit consent before code leaves the machine, bounded payloads,
billing and failure telemetry, fresh broad-query judgments, and an index/AST
retrieval evaluation. The local models tested here are not an adequate
privacy-preserving substitute on this CPU. A GPU-backed Bosun or Eos trial
and a code-specific candidate retriever are better next local experiments.

Raw result files (temporary, may be purged):

- `/private/tmp/attocode-jev-choice-holdout20-twelve.json`
- `/private/tmp/attocode-jev-choice-external20-twelve.json`
- `/private/tmp/attocode-jev-choice-publicdev16-twelve.json`
- `/private/tmp/attocode-minilm-holdout20-twelve.json`
- `/private/tmp/attocode-minilm-external20-twelve.json`
- `/private/tmp/attocode-gte-holdout20-twelve.json`
- `/private/tmp/attocode-gte-external20-twelve.json`
- `/private/tmp/attocode-decision2-choice-holdout20-twelve.json`
- `/private/tmp/attocode-qwen3-threecase-six.json`
