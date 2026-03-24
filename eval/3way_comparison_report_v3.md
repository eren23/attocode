# 3-Way Code Intelligence Comparison

Generated: 2026-03-24 12:56
Tools: grep, ast-grep, code-intel
Repos: fastapi, gh-cli, redis, metabase, ggplot2, otp, perl5, express, laravel

## fastapi

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 70ms | 178ms | 826ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 82ms | 237ms | 1ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 31ms | 10ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 56ms | 137ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 37ms | 56ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 40ms | 155ms | 22749ms | 3/5 | 3/5 | 5/5 |

## gh-cli

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 47ms | 247ms | 1035ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 42ms | 356ms | 1ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 28ms | 13ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 102ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 32ms | 94ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 30ms | 256ms | 2673ms | 3/5 | 3/5 | 5/5 |

## redis

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 55ms | 551ms | 2253ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 50ms | 654ms | 2ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 31ms | 23ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 261ms | 8ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 33ms | 225ms | 0ms | 5/5 | 2/5 | 5/5 |
| Semantic Search | 34ms | 669ms | 6237ms | 5/5 | 5/5 | 5/5 |

## metabase

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 376ms | 0ms | 9787ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 422ms | 0ms | 1ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 219ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 4ms | 0ms | 122ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 222ms | 0ms | 1ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 283ms | 0ms | 27740ms | 5/5 | 1/5 | 5/5 |

## ggplot2

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 45ms | 0ms | 30ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 44ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 33ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 0ms | 3/5 | 1/5 | 3/5 |
| Code Navigation | 34ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 27ms | 0ms | 8637ms | 3/5 | 1/5 | 5/5 |

## otp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 251ms | 0ms | 7041ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 223ms | 0ms | 3ms | 4/5 | 1/5 | 5/5 |
| Dependency Tracing | 117ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 3ms | 0ms | 15ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 159ms | 0ms | 2ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 148ms | 0ms | 19320ms | 3/5 | 1/5 | 5/5 |

## perl5

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 152ms | 0ms | 2794ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 151ms | 0ms | 1ms | 3/5 | 1/5 | 5/5 |
| Dependency Tracing | 79ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 4ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 78ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Semantic Search | 72ms | 0ms | 65705ms | 5/5 | 1/5 | 5/5 |

## express

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 33ms | 66ms | 204ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 31ms | 75ms | 0ms | 3/5 | 3/5 | 1/5 |
| Dependency Tracing | 24ms | 14ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 23ms | 0ms | 3/5 | 0/5 | 3/5 |
| Code Navigation | 25ms | 25ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 16ms | 74ms | 861ms | 3/5 | 3/5 | 5/5 |

## laravel

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 80ms | 436ms | 832ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 74ms | 519ms | 4ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 45ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 212ms | 0ms | 3/5 | 3/5 | 3/5 |
| Code Navigation | 49ms | 166ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 42ms | 497ms | 3132ms | 5/5 | 3/5 | 5/5 |

## Summary Averages

| Metric | grep | ast-grep | code-intel |
|--------|------|----------|------------|
| Avg Time | 78ms | 116ms | 3373ms |
| Avg Quality | 3.9/5 | 2.0/5 | 4.2/5 |
| Total Output | 24,204,550 chars | 1,337,164 chars | 136,117 chars |
