# 3-Way Code Intelligence Comparison

Generated: 2026-03-22 23:38
Tools: grep, ast-grep, code-intel
Repos: 19 (attocode, fastapi, pandas, deno, aspnetcore, laravel, swiftformat, okhttp, gh-cli, faker, redis, spdlog, cats-effect, luarocks, phoenix, postgrest, acme-sh, terraform-eks, zls)
Languages: Python, Go, C, C++, C#, Rust, Kotlin, Swift, Ruby, PHP, Scala, Elixir, Lua, Zig, Bash, HCL, Haskell

![3-Way Comparison Chart](../scripts/3way_comparison.png)

## attocode

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 59ms | 331ms | 11885ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 46ms | 96ms | 0ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 24ms | 11ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 107ms | 128ms | 2/5 | 0/5 | 5/5 |
| Code Navigation | 26ms | 98ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 32ms | 303ms | 15965ms | 5/5 | 3/5 | 5/5 |

## fastapi

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 81ms | 187ms | 1298ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 94ms | 62ms | 0ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 47ms | 16ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 63ms | 15ms | 2/5 | 0/5 | 4/5 |
| Code Navigation | 46ms | 61ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 46ms | 180ms | 18007ms | 3/5 | 3/5 | 5/5 |

## pandas

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 74ms | 1042ms | 9539ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 94ms | 326ms | 0ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 41ms | 35ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 348ms | 39ms | 2/5 | 0/5 | 4/5 |
| Code Navigation | 53ms | 309ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 48ms | 892ms | 9686ms | 5/5 | 5/5 | 5/5 |

## deno

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 349ms | 457ms | 18960ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 252ms | 171ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 133ms | 18ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 3ms | 240ms | 10ms | 2/5 | 3/5 | 4/5 |
| Code Navigation | 135ms | 198ms | 2ms | 4/5 | 3/5 | 5/5 |
| Semantic Search | 149ms | 535ms | 48104ms | 5/5 | 3/5 | 5/5 |

## aspnetcore

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 413ms | 2786ms | 40059ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 362ms | 1326ms | 0ms | 5/5 | 0/5 | 5/5 |
| Dependency Tracing | 184ms | 17ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 5ms | 1355ms | 6ms | 2/5 | 2/5 | 4/5 |
| Code Navigation | 346ms | 1225ms | 0ms | 5/5 | 0/5 | 5/5 |
| Semantic Search | 250ms | 4119ms | 24755ms | 5/5 | 1/5 | 5/5 |

## laravel

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 83ms | 459ms | 6343ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 77ms | 166ms | 0ms | 3/5 | 3/5 | 5/5 |
| Dependency Tracing | 45ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 201ms | 0ms | 2/5 | 2/5 | 3/5 |
| Code Navigation | 50ms | 173ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 43ms | 508ms | 3040ms | 5/5 | 3/5 | 5/5 |

## swiftformat

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 40ms | 311ms | 1331ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 38ms | 121ms | 0ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 27ms | 15ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 0ms | 115ms | 0ms | 2/5 | 1/5 | 3/5 |
| Code Navigation | 30ms | 113ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 22ms | 345ms | 1326ms | 3/5 | 3/5 | 5/5 |

## okhttp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 50ms | 167ms | 883ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 49ms | 76ms | 0ms | 3/5 | 3/5 | 5/5 |
| Dependency Tracing | 31ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 77ms | 0ms | 2/5 | 2/5 | 3/5 |
| Code Navigation | 35ms | 78ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 28ms | 236ms | 2024ms | 3/5 | 3/5 | 5/5 |

## gh-cli

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 53ms | 272ms | 1705ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 46ms | 85ms | 0ms | 4/5 | 4/5 | 1/5 |
| Dependency Tracing | 31ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 95ms | 1ms | 2/5 | 2/5 | 4/5 |
| Code Navigation | 34ms | 89ms | 0ms | 5/5 | 4/5 | 1/5 |
| Semantic Search | 33ms | 272ms | 2997ms | 3/5 | 3/5 | 5/5 |

## faker

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 44ms | 104ms | 1488ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 46ms | 31ms | 0ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 31ms | 14ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 43ms | 0ms | 2/5 | 2/5 | 4/5 |
| Code Navigation | 31ms | 31ms | 0ms | 3/5 | 5/5 | 5/5 |
| Semantic Search | 33ms | 90ms | 3770ms | 5/5 | 3/5 | 5/5 |

## redis

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 57ms | 549ms | 4634ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 49ms | 219ms | 0ms | 4/5 | 0/5 | 5/5 |
| Dependency Tracing | 35ms | 24ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 256ms | 8ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 37ms | 302ms | 0ms | 5/5 | 2/5 | 5/5 |
| Semantic Search | 37ms | 723ms | 7263ms | 5/5 | 5/5 | 5/5 |

## spdlog

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 31ms | 59ms | 1191ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 29ms | 23ms | 0ms | 4/5 | 3/5 | 1/5 |
| Dependency Tracing | 27ms | 24ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 22ms | 4ms | 2/5 | 0/5 | 4/5 |
| Code Navigation | 29ms | 21ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 32ms | 65ms | 941ms | 3/5 | 2/5 | 5/5 |

## cats-effect

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 43ms | 183ms | 609ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 50ms | 94ms | 0ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 32ms | 29ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 90ms | 0ms | 2/5 | 2/5 | 3/5 |
| Code Navigation | 33ms | 91ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 24ms | 255ms | 1353ms | 5/5 | 3/5 | 5/5 |

## luarocks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 41ms | 44ms | 218ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 37ms | 32ms | 0ms | 5/5 | 4/5 | 1/5 |
| Dependency Tracing | 30ms | 14ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 85ms | 0ms | 2/5 | 3/5 | 4/5 |
| Code Navigation | 30ms | 50ms | 0ms | 4/5 | 3/5 | 5/5 |
| Semantic Search | 21ms | 134ms | 4211ms | 3/5 | 3/5 | 5/5 |

## phoenix

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 46ms | 18ms | 950ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 40ms | 60ms | 0ms | 3/5 | 3/5 | 5/5 |
| Dependency Tracing | 31ms | 18ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 13ms | 0ms | 2/5 | 0/5 | 4/5 |
| Code Navigation | 33ms | 61ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 23ms | 189ms | 1884ms | 5/5 | 3/5 | 5/5 |

## postgrest

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 36ms | 47ms | 1713ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 34ms | 35ms | 0ms | 4/5 | 3/5 | 1/5 |
| Dependency Tracing | 28ms | 12ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 38ms | 0ms | 2/5 | 2/5 | 3/5 |
| Code Navigation | 29ms | 34ms | 0ms | 4/5 | 3/5 | 1/5 |
| Semantic Search | 19ms | 125ms | 4079ms | 5/5 | 3/5 | 5/5 |

## acme-sh

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 33ms | 18ms | 193ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 32ms | 46ms | 0ms | 3/5 | 0/5 | 1/5 |
| Dependency Tracing | 27ms | 0ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 12ms | 0ms | 2/5 | 0/5 | 3/5 |
| Code Navigation | 28ms | 48ms | 0ms | 4/5 | 2/5 | 5/5 |
| Semantic Search | 15ms | 137ms | 213ms | 3/5 | 1/5 | 5/5 |

## terraform-eks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 31ms | 37ms | 133ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 30ms | 33ms | 0ms | 3/5 | 3/5 | 1/5 |
| Dependency Tracing | 27ms | 0ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 36ms | 0ms | 3/5 | 3/5 | 3/5 |
| Code Navigation | 27ms | 33ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 17ms | 99ms | 866ms | 3/5 | 3/5 | 5/5 |

## zls

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 31ms | 27ms | 285ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 29ms | 11ms | 0ms | 4/5 | 0/5 | 1/5 |
| Dependency Tracing | 25ms | 12ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 13ms | 0ms | 2/5 | 0/5 | 3/5 |
| Code Navigation | 26ms | 14ms | 0ms | 5/5 | 0/5 | 5/5 |
| Semantic Search | 13ms | 39ms | 238ms | 3/5 | 1/5 | 5/5 |

## Summary Averages

| Metric | grep | ast-grep | code-intel |
|--------|------|----------|------------|
| Avg Time | 51ms | 227ms | 2231ms |
| Avg Quality | 3.8/5 | 2.4/5 | 4.4/5 |
| Total Output | 59,110,828 chars | 5,283,367 chars | 288,037 chars |
