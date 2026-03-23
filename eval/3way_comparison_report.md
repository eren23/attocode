# 3-Way Code Intelligence Comparison

Generated: 2026-03-23 00:48
Tools: grep, ast-grep, code-intel
Repos: attocode, fastapi, pandas, deno, aspnetcore, laravel, swiftformat, okhttp, gh-cli, faker, redis, spdlog, cats-effect, luarocks, phoenix, postgrest, acme-sh, terraform-eks, zls

## attocode

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 47ms | 313ms | 11604ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 44ms | 90ms | 2ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 24ms | 11ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 102ms | 90ms | 2/5 | 0/5 | 5/5 |
| Code Navigation | 26ms | 94ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 32ms | 296ms | 17249ms | 5/5 | 3/5 | 5/5 |

## fastapi

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 78ms | 168ms | 1293ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 91ms | 57ms | 0ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 43ms | 18ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 56ms | 14ms | 2/5 | 0/5 | 4/5 |
| Code Navigation | 46ms | 55ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 46ms | 159ms | 16396ms | 3/5 | 3/5 | 5/5 |

## pandas

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 65ms | 932ms | 9738ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 75ms | 314ms | 5ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 41ms | 33ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 271ms | 34ms | 2/5 | 0/5 | 4/5 |
| Code Navigation | 50ms | 320ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 49ms | 819ms | 8437ms | 5/5 | 5/5 | 5/5 |

## deno

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 268ms | 431ms | 18708ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 251ms | 189ms | 3ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 136ms | 19ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 3ms | 217ms | 10ms | 2/5 | 3/5 | 4/5 |
| Code Navigation | 138ms | 159ms | 1ms | 4/5 | 3/5 | 5/5 |
| Semantic Search | 151ms | 580ms | 40891ms | 5/5 | 3/5 | 5/5 |

## aspnetcore

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 329ms | 1988ms | 35192ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 376ms | 966ms | 7ms | 5/5 | 0/5 | 5/5 |
| Dependency Tracing | 196ms | 16ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 5ms | 1333ms | 6ms | 2/5 | 2/5 | 4/5 |
| Code Navigation | 190ms | 974ms | 0ms | 5/5 | 0/5 | 5/5 |
| Semantic Search | 234ms | 2795ms | 24693ms | 5/5 | 1/5 | 5/5 |

## laravel

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 78ms | 437ms | 6846ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 80ms | 169ms | 4ms | 3/5 | 3/5 | 5/5 |
| Dependency Tracing | 47ms | 17ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 202ms | 0ms | 2/5 | 2/5 | 3/5 |
| Code Navigation | 52ms | 166ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 43ms | 510ms | 3112ms | 5/5 | 3/5 | 5/5 |

## swiftformat

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 42ms | 331ms | 1090ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 40ms | 105ms | 2ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 29ms | 16ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 0ms | 110ms | 0ms | 2/5 | 1/5 | 3/5 |
| Code Navigation | 30ms | 108ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 22ms | 367ms | 1640ms | 3/5 | 3/5 | 5/5 |

## okhttp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 52ms | 173ms | 879ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 52ms | 78ms | 1ms | 3/5 | 3/5 | 5/5 |
| Dependency Tracing | 33ms | 19ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 84ms | 0ms | 2/5 | 2/5 | 3/5 |
| Code Navigation | 37ms | 74ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 28ms | 238ms | 1884ms | 3/5 | 3/5 | 5/5 |

## gh-cli

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 51ms | 246ms | 1693ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 47ms | 86ms | 1ms | 4/5 | 4/5 | 4/5 |
| Dependency Tracing | 34ms | 16ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 94ms | 1ms | 2/5 | 2/5 | 4/5 |
| Code Navigation | 39ms | 93ms | 0ms | 5/5 | 4/5 | 1/5 |
| Semantic Search | 32ms | 266ms | 3028ms | 3/5 | 3/5 | 5/5 |

## faker

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 47ms | 104ms | 1519ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 47ms | 31ms | 1ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 30ms | 16ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 45ms | 0ms | 2/5 | 2/5 | 4/5 |
| Code Navigation | 35ms | 32ms | 0ms | 3/5 | 5/5 | 5/5 |
| Semantic Search | 35ms | 91ms | 3882ms | 5/5 | 3/5 | 5/5 |

## redis

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 60ms | 563ms | 4433ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 55ms | 226ms | 2ms | 4/5 | 0/5 | 5/5 |
| Dependency Tracing | 40ms | 25ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 255ms | 8ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 36ms | 228ms | 0ms | 5/5 | 2/5 | 5/5 |
| Semantic Search | 38ms | 707ms | 6793ms | 5/5 | 5/5 | 5/5 |

## spdlog

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 31ms | 51ms | 1521ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 32ms | 22ms | 0ms | 4/5 | 3/5 | 4/5 |
| Dependency Tracing | 25ms | 22ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 22ms | 4ms | 2/5 | 0/5 | 4/5 |
| Code Navigation | 29ms | 23ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 16ms | 63ms | 928ms | 3/5 | 2/5 | 5/5 |

## cats-effect

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 46ms | 179ms | 601ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 53ms | 84ms | 1ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 33ms | 30ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 91ms | 0ms | 2/5 | 2/5 | 3/5 |
| Code Navigation | 32ms | 90ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 26ms | 256ms | 1303ms | 5/5 | 3/5 | 5/5 |

## luarocks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 37ms | 45ms | 154ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 37ms | 30ms | 0ms | 5/5 | 4/5 | 4/5 |
| Dependency Tracing | 27ms | 16ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 42ms | 0ms | 2/5 | 3/5 | 4/5 |
| Code Navigation | 28ms | 32ms | 0ms | 4/5 | 3/5 | 5/5 |
| Semantic Search | 21ms | 96ms | 3768ms | 3/5 | 3/5 | 5/5 |

## phoenix

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 38ms | 18ms | 563ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 37ms | 53ms | 0ms | 3/5 | 3/5 | 5/5 |
| Dependency Tracing | 30ms | 18ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 12ms | 0ms | 2/5 | 0/5 | 4/5 |
| Code Navigation | 30ms | 54ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 21ms | 165ms | 1751ms | 5/5 | 3/5 | 5/5 |

## postgrest

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 37ms | 47ms | 1650ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 37ms | 34ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 25ms | 12ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 37ms | 0ms | 2/5 | 2/5 | 3/5 |
| Code Navigation | 29ms | 34ms | 0ms | 4/5 | 3/5 | 1/5 |
| Semantic Search | 21ms | 104ms | 3907ms | 5/5 | 3/5 | 5/5 |

## acme-sh

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 30ms | 15ms | 195ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 31ms | 48ms | 0ms | 3/5 | 0/5 | 4/5 |
| Dependency Tracing | 27ms | 0ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 13ms | 0ms | 2/5 | 0/5 | 3/5 |
| Code Navigation | 28ms | 48ms | 0ms | 4/5 | 2/5 | 5/5 |
| Semantic Search | 16ms | 145ms | 177ms | 3/5 | 1/5 | 5/5 |

## terraform-eks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 32ms | 41ms | 526ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 31ms | 32ms | 0ms | 3/5 | 3/5 | 4/5 |
| Dependency Tracing | 24ms | 0ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 35ms | 0ms | 3/5 | 3/5 | 3/5 |
| Code Navigation | 28ms | 33ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 17ms | 98ms | 892ms | 3/5 | 3/5 | 5/5 |

## zls

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 33ms | 28ms | 264ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 30ms | 11ms | 0ms | 4/5 | 0/5 | 4/5 |
| Dependency Tracing | 26ms | 11ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 11ms | 0ms | 2/5 | 0/5 | 3/5 |
| Code Navigation | 25ms | 12ms | 0ms | 5/5 | 0/5 | 5/5 |
| Semantic Search | 17ms | 33ms | 226ms | 3/5 | 1/5 | 5/5 |

## Summary Averages

| Metric | grep | ast-grep | code-intel |
|--------|------|----------|------------|
| Avg Time | 48ms | 197ms | 2102ms |
| Avg Quality | 3.8/5 | 2.4/5 | 4.5/5 |
| Total Output | 59,113,282 chars | 5,284,326 chars | 323,529 chars |
