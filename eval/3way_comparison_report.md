# 3-Way Code Intelligence Comparison

Generated: 2026-03-23 12:15
Tools: grep, ast-grep, code-intel
Repos: attocode, fastapi, pandas, deno, aspnetcore, laravel, swiftformat, okhttp, gh-cli, faker, redis, spdlog, cats-effect, luarocks, phoenix, postgrest, acme-sh, terraform-eks, zls

## attocode

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 52ms | 324ms | 11620ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 45ms | 396ms | 2ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 25ms | 10ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 103ms | 108ms | 3/5 | 0/5 | 5/5 |
| Code Navigation | 28ms | 99ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 32ms | 294ms | 17363ms | 5/5 | 3/5 | 5/5 |

## fastapi

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 85ms | 262ms | 1322ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 90ms | 253ms | 1ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 44ms | 16ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 57ms | 15ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 45ms | 53ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 45ms | 181ms | 18910ms | 3/5 | 3/5 | 5/5 |

## pandas

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 73ms | 1014ms | 9619ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 76ms | 1188ms | 5ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 42ms | 32ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 281ms | 37ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 51ms | 416ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 56ms | 906ms | 8940ms | 5/5 | 5/5 | 5/5 |

## deno

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 262ms | 456ms | 19578ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 252ms | 775ms | 4ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 138ms | 19ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 3ms | 222ms | 10ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 137ms | 208ms | 2ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 152ms | 565ms | 45472ms | 5/5 | 3/5 | 5/5 |

## aspnetcore

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 333ms | 2111ms | 37486ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 402ms | 4673ms | 8ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 203ms | 16ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 5ms | 1064ms | 6ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 194ms | 1215ms | 0ms | 5/5 | 0/5 | 5/5 |
| Semantic Search | 257ms | 2879ms | 25923ms | 5/5 | 1/5 | 5/5 |

## laravel

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 80ms | 470ms | 6992ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 81ms | 594ms | 4ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 48ms | 16ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 216ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 52ms | 167ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 42ms | 569ms | 3039ms | 5/5 | 3/5 | 5/5 |

## swiftformat

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 37ms | 320ms | 1148ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 39ms | 573ms | 6ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 27ms | 16ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 0ms | 146ms | 0ms | 3/5 | 2/5 | 2/5 |
| Code Navigation | 31ms | 144ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 21ms | 369ms | 1701ms | 3/5 | 3/5 | 5/5 |

## okhttp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 54ms | 167ms | 897ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 48ms | 231ms | 1ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 32ms | 16ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 87ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 34ms | 78ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 26ms | 230ms | 1842ms | 3/5 | 3/5 | 5/5 |

## gh-cli

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 49ms | 244ms | 1842ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 46ms | 368ms | 1ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 32ms | 17ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 104ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 37ms | 98ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 32ms | 277ms | 3248ms | 3/5 | 3/5 | 5/5 |

## faker

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 46ms | 105ms | 1601ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 46ms | 98ms | 1ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 33ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 46ms | 0ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 33ms | 32ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 33ms | 98ms | 3875ms | 5/5 | 3/5 | 5/5 |

## redis

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 55ms | 544ms | 4752ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 53ms | 688ms | 2ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 39ms | 25ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 251ms | 9ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 37ms | 241ms | 0ms | 5/5 | 2/5 | 5/5 |
| Semantic Search | 37ms | 699ms | 6783ms | 5/5 | 5/5 | 5/5 |

## spdlog

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 31ms | 53ms | 1555ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 30ms | 86ms | 0ms | 4/5 | 5/5 | 4/5 |
| Dependency Tracing | 23ms | 23ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 23ms | 4ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 28ms | 21ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 17ms | 64ms | 987ms | 3/5 | 2/5 | 5/5 |

## cats-effect

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 45ms | 180ms | 666ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 49ms | 624ms | 1ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 29ms | 37ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 105ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 35ms | 111ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 23ms | 286ms | 1324ms | 5/5 | 3/5 | 5/5 |

## luarocks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 36ms | 46ms | 158ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 34ms | 70ms | 0ms | 5/5 | 4/5 | 4/5 |
| Dependency Tracing | 27ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 49ms | 0ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 31ms | 33ms | 0ms | 4/5 | 3/5 | 5/5 |
| Semantic Search | 22ms | 100ms | 3699ms | 3/5 | 3/5 | 5/5 |

## phoenix

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 34ms | 17ms | 570ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 33ms | 74ms | 0ms | 3/5 | 5/5 | 5/5 |
| Dependency Tracing | 26ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 11ms | 0ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 30ms | 52ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 20ms | 162ms | 1835ms | 5/5 | 3/5 | 5/5 |

## postgrest

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 37ms | 46ms | 1627ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 36ms | 72ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 30ms | 13ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 41ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 37ms | 36ms | 0ms | 4/5 | 3/5 | 1/5 |
| Semantic Search | 21ms | 105ms | 3815ms | 5/5 | 3/5 | 5/5 |

## acme-sh

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 34ms | 19ms | 195ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 29ms | 58ms | 0ms | 3/5 | 0/5 | 4/5 |
| Dependency Tracing | 26ms | 0ms | 0ms | 5/5 | 2/5 | 5/5 |
| Architecture | 0ms | 12ms | 0ms | 3/5 | 0/5 | 2/5 |
| Code Navigation | 27ms | 48ms | 0ms | 4/5 | 2/5 | 5/5 |
| Semantic Search | 15ms | 136ms | 172ms | 3/5 | 1/5 | 5/5 |

## terraform-eks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 30ms | 36ms | 143ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 30ms | 64ms | 0ms | 3/5 | 5/5 | 4/5 |
| Dependency Tracing | 25ms | 0ms | 0ms | 5/5 | 2/5 | 5/5 |
| Architecture | 0ms | 36ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 27ms | 35ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 17ms | 94ms | 860ms | 3/5 | 3/5 | 5/5 |

## zls

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 28ms | 0ms | 643ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 29ms | 0ms | 0ms | 4/5 | 1/5 | 4/5 |
| Dependency Tracing | 24ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 3/5 | 1/5 | 2/5 |
| Code Navigation | 27ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Semantic Search | 16ms | 0ms | 229ms | 3/5 | 1/5 | 5/5 |

## Summary Averages

| Metric | grep | ast-grep | code-intel |
|--------|------|----------|------------|
| Avg Time | 49ms | 277ms | 2216ms |
| Avg Quality | 4.0/5 | 2.7/5 | 4.5/5 |
| Total Output | 59,113,282 chars | 7,812,918 chars | 326,616 chars |
