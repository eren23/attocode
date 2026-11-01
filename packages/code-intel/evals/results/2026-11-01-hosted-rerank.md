# Hosted rerank trial (2026-11-01)

**Result: PASS on all 15 frozen gates.** The hosted Jev `choice` rerank found more of the labeled files on the first page of short agent-style questions. The rerank stays **off by default**. The docs now recommend the opt-in for users who approve sending source to OpenRouter.

- Design: [`designs/2026-11-hosted-rerank.json`](../designs/2026-11-hosted-rerank.json), SHA-256 `7105e4ff836c206066b2060e62c82fff26d5981de17125426fb3aa7178b9419d`, frozen before any hosted call.
- Run: [Hosted rerank trial 41280380677](https://github.com/eren23/attocode/actions/runs/41280380677), attempt 1, head `8081aab00db21dc7bfa1cf4dc84cc28958e97d23`. One dispatch, no tuning, no retry.
- Raw data: [`2026-11-01-hosted-rerank.tar.gz`](2026-11-01-hosted-rerank.tar.gz) (SHA-256 `75286931693aaab36845a5a62225c529ad782e0d8c6d49eeed73fd570b789362`). It holds the per-pack observations of both arms, the key usage before and after, and `decision.json`. The compact record is [`2026-11-01-hosted-rerank.json`](2026-11-01-hosted-rerank.json).

## Setup

- 24 new short questions, 6 each on four public pinned repositories: FastAPI (Python), Prisma (TypeScript), GitHub CLI (Go) and Starship (Rust). Each question has 1 or 2 source-checked file labels (26 labels).
- Baseline arm: `ATTOCODE_LOCAL_ONLY=1`, default deterministic ranking, one delivery per page.
- Candidate arm: provider `systemone`, endpoint `https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.13`, timeout 1500 ms, remote opt-in for the pinned source only. Three samples per page. A label counts only if **all three** samples deliver it (worst of three).
- Both arms used the same engine (`4dd8fac0…`) and the same evaluator (`5b63a40d…`) through real MCP delivery at a 2,000-token budget.

## Results

| Metric (labels found) | Baseline | Candidate |
|---|---|---|
| Judged files, first 5 | 20 / 26 | **24 / 26** |
| Judged files, first 24 | 23 / 26 | **24 / 26** |
| Labeled ranges, first 5 | 10 | 12 |
| Visible quotes, first 5 | 8 | 9 |
| Labeled ranges, first 24 | 11 | 12 |
| Visible quotes, first 24 | 5 | 6 |
| Inspection: visible quotes | 8 | 10 |
| Scoped search: files / ranges / visible | 24 / 20 / 14 | 24 / 20 / 14 |

Net first-five file gain by repository: FastAPI +2, Prisma +1, GitHub CLI +1, Starship 0. No individual file label was lost on any page.

| Question | Page | File gained |
|---|---|---|
| fastapi:rerank-4 | 5 | `fastapi/exception_handlers.py` |
| fastapi:rerank-5 | 5 | `fastapi/routing.py` |
| prisma:rerank-2 | 5 | `packages/migrate/src/commands/DbSeed.ts` |
| gh-cli:rerank-2 | 5 and 24 | `pkg/cmd/repo/sync/sync.go` |

Three questions lost a visible quote on the first-24 page: gh-cli:rerank-3, prisma:rerank-2 and starship:rerank-4. The file stayed on the page in each case. The frozen rule allows individual visible-quote losses when the visible total does not fall; the total rose from 5 to 6.

## Hosted gates

| Gate | Frozen limit | Measured |
|---|---|---|
| Ranker | every ranking from `systemone` / `typesafe/jev-1.13`, remote | 216 of 216 |
| Fallbacks | ≤ 5% of attempts, no configuration fallback | 1 of 144 (one timeout, 1,502 ms) |
| Rerank p95 | ≤ 1,500 ms | 377 ms |
| Search p95 (every page-5 and page-24 sample) | ≤ 2.0 s | 0.568 s (baseline p95 0.219 s) |
| Baseline remote calls | 0 | 0 |
| Refused calls | 0 | 0 |
| Spend | estimate and measured ≤ $5 | 165 calls, $0.064 measured (estimate $0.124) |

The measured cost is about $0.0004 per call, which is lower than the design estimate of $0.00075. The key usage was read before the candidate arm and again 60 seconds after it.

## Independent check

A separate standard-library script recomputed the decision from the raw rows in the archive. It gives the same file totals (20 to 24 at five, 23 to 24 at 24), the same per-repository net, zero file-label losses, 1 timeout fallback in 144 attempts and a rerank p95 of 376.82 ms.

## Limits

- 24 authored questions with non-exhaustive labels. They are not independent users or agent outcomes.
- The four repositories were seen in earlier workflow packs. The questions are new, but some label files also label different questions in earlier sets (listed in the design).
- One run. Jev is not deterministic; worst of three samples reduces, but does not remove, this variance. The baseline is deterministic and had one delivery per page.
- The 24 questions are now consumed. Do not use them again as fresh validation.
- Latency is from GitHub-hosted runners to OpenRouter. Other networks can be slower.
- Each search sends the redacted query and up to 24 source excerpts to OpenRouter. Enable it only for source that you approve sending.
