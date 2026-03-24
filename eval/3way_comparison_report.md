# 3-Way Code Intelligence Comparison

Generated: 2026-03-24 01:29
Tools: grep, ast-grep, code-intel
Repos: attocode, fastapi, pandas, deno, aspnetcore, laravel, swiftformat, okhttp, gh-cli, faker, redis, spdlog, cats-effect, luarocks, phoenix, postgrest, acme-sh, terraform-eks, zls, cockroach, express, prisma, rails, requests, cosmopolitan, ripgrep, starship, spring-boot, spark, vapor, wordpress, protobuf, crystal-lang, dart-sdk, elixir-lang, emqx, fsharp, ggplot2, iterm2, julia, kemal, metabase, mojo-perl, nickel, nim, ocaml, otp, perl5, ring

## attocode

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 64ms | 483ms | 24670ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 74ms | 739ms | 3ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 33ms | 12ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 171ms | 135ms | 3/5 | 0/5 | 5/5 |
| Code Navigation | 30ms | 165ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 38ms | 549ms | 20995ms | 5/5 | 3/5 | 5/5 |

## fastapi

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 82ms | 231ms | 793ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 94ms | 302ms | 1ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 44ms | 20ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 69ms | 30ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 52ms | 68ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 47ms | 186ms | 21860ms | 3/5 | 3/5 | 5/5 |

## pandas

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 77ms | 1200ms | 36066ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 78ms | 1583ms | 10ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 43ms | 38ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 339ms | 61ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 54ms | 358ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 50ms | 1029ms | 13053ms | 5/5 | 5/5 | 5/5 |

## deno

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 422ms | 893ms | 87131ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 392ms | 1322ms | 5ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 177ms | 23ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 5ms | 281ms | 11ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 293ms | 236ms | 1ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 224ms | 872ms | 46227ms | 5/5 | 3/5 | 5/5 |

## aspnetcore

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 438ms | 3060ms | 115428ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 374ms | 5373ms | 7ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 252ms | 17ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 6ms | 1339ms | 6ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 199ms | 1221ms | 0ms | 5/5 | 0/5 | 5/5 |
| Semantic Search | 275ms | 3623ms | 22647ms | 5/5 | 1/5 | 5/5 |

## laravel

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 83ms | 430ms | 14091ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 78ms | 497ms | 4ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 46ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 189ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 48ms | 173ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 42ms | 515ms | 3181ms | 5/5 | 3/5 | 5/5 |

## swiftformat

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 43ms | 365ms | 1613ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 39ms | 512ms | 2ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 25ms | 15ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 0ms | 120ms | 0ms | 3/5 | 2/5 | 2/5 |
| Code Navigation | 29ms | 112ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 22ms | 384ms | 1299ms | 3/5 | 3/5 | 5/5 |

## okhttp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 51ms | 168ms | 1483ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 50ms | 233ms | 1ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 32ms | 17ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 83ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 36ms | 74ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 28ms | 245ms | 2091ms | 3/5 | 3/5 | 5/5 |

## gh-cli

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 53ms | 329ms | 2794ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 50ms | 384ms | 1ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 35ms | 16ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 99ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 40ms | 118ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 33ms | 406ms | 3122ms | 3/5 | 3/5 | 5/5 |

## faker

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 43ms | 107ms | 2071ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 43ms | 91ms | 1ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 28ms | 13ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 41ms | 0ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 79ms | 31ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 33ms | 89ms | 4630ms | 5/5 | 3/5 | 5/5 |

## redis

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 62ms | 569ms | 6086ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 50ms | 712ms | 2ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 37ms | 23ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 253ms | 9ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 36ms | 213ms | 0ms | 5/5 | 2/5 | 5/5 |
| Semantic Search | 37ms | 729ms | 7439ms | 5/5 | 5/5 | 5/5 |

## spdlog

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 37ms | 63ms | 1213ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 32ms | 93ms | 0ms | 4/5 | 5/5 | 4/5 |
| Dependency Tracing | 28ms | 27ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 23ms | 4ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 29ms | 25ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 18ms | 70ms | 1000ms | 3/5 | 2/5 | 5/5 |

## cats-effect

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 46ms | 217ms | 830ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 51ms | 441ms | 1ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 34ms | 28ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 103ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 34ms | 98ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 27ms | 262ms | 1379ms | 5/5 | 3/5 | 5/5 |

## luarocks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 35ms | 55ms | 177ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 33ms | 67ms | 0ms | 5/5 | 4/5 | 4/5 |
| Dependency Tracing | 28ms | 16ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 45ms | 0ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 29ms | 34ms | 0ms | 4/5 | 3/5 | 5/5 |
| Semantic Search | 20ms | 99ms | 4172ms | 3/5 | 3/5 | 5/5 |

## phoenix

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 39ms | 16ms | 1143ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 36ms | 84ms | 0ms | 3/5 | 5/5 | 5/5 |
| Dependency Tracing | 29ms | 18ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 12ms | 0ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 30ms | 63ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 21ms | 176ms | 1892ms | 5/5 | 3/5 | 5/5 |

## postgrest

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 35ms | 46ms | 1796ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 36ms | 76ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 29ms | 14ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 41ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 32ms | 37ms | 0ms | 4/5 | 3/5 | 1/5 |
| Semantic Search | 21ms | 115ms | 4218ms | 5/5 | 3/5 | 5/5 |

## acme-sh

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 30ms | 16ms | 228ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 28ms | 58ms | 0ms | 3/5 | 0/5 | 4/5 |
| Dependency Tracing | 27ms | 0ms | 0ms | 5/5 | 2/5 | 5/5 |
| Architecture | 0ms | 12ms | 0ms | 3/5 | 0/5 | 2/5 |
| Code Navigation | 27ms | 46ms | 0ms | 4/5 | 2/5 | 5/5 |
| Semantic Search | 15ms | 141ms | 173ms | 3/5 | 1/5 | 5/5 |

## terraform-eks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 30ms | 35ms | 161ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 30ms | 68ms | 0ms | 3/5 | 5/5 | 4/5 |
| Dependency Tracing | 23ms | 0ms | 0ms | 5/5 | 2/5 | 5/5 |
| Architecture | 0ms | 35ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 26ms | 35ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 17ms | 102ms | 886ms | 3/5 | 3/5 | 5/5 |

## zls

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 31ms | 0ms | 335ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 29ms | 0ms | 0ms | 4/5 | 1/5 | 4/5 |
| Dependency Tracing | 25ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 3/5 | 1/5 | 2/5 |
| Code Navigation | 25ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Semantic Search | 15ms | 0ms | 236ms | 3/5 | 1/5 | 5/5 |

## cockroach

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 467ms | 4625ms | 383392ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 418ms | 5422ms | 19ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 431ms | 15ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 5ms | 2480ms | 28ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 248ms | 1261ms | 1ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 318ms | 3653ms | 43519ms | 5/5 | 3/5 | 5/5 |

## express

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 37ms | 74ms | 300ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 32ms | 83ms | 0ms | 3/5 | 3/5 | 1/5 |
| Dependency Tracing | 29ms | 17ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 26ms | 0ms | 3/5 | 0/5 | 2/5 |
| Code Navigation | 32ms | 28ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 19ms | 81ms | 870ms | 3/5 | 3/5 | 5/5 |

## prisma

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 151ms | 211ms | 4911ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 138ms | 404ms | 0ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 77ms | 16ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 1ms | 94ms | 23ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 79ms | 92ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 93ms | 290ms | 8852ms | 5/5 | 3/5 | 5/5 |

## rails

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 126ms | 1255ms | 22675ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 118ms | 788ms | 7ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 71ms | 19ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 417ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 74ms | 253ms | 1ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 74ms | 709ms | 10602ms | 5/5 | 5/5 | 5/5 |

## requests

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 36ms | 86ms | 112ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 34ms | 117ms | 0ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 33ms | 19ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 29ms | 1ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 31ms | 29ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 17ms | 89ms | 770ms | 3/5 | 3/5 | 5/5 |

## cosmopolitan

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 366ms | 3060ms | 197262ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 341ms | 3722ms | 18ms | 5/5 | 5/5 | 4/5 |
| Dependency Tracing | 177ms | 17ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 3ms | 1340ms | 274ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 174ms | 1226ms | 0ms | 5/5 | 4/5 | 1/5 |
| Semantic Search | 250ms | 3697ms | 48179ms | 5/5 | 3/5 | 5/5 |

## ripgrep

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 44ms | 117ms | 593ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 45ms | 182ms | 0ms | 4/5 | 2/5 | 5/5 |
| Dependency Tracing | 37ms | 18ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 43ms | 0ms | 4/5 | 3/5 | 2/5 |
| Code Navigation | 37ms | 51ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 20ms | 147ms | 1807ms | 3/5 | 3/5 | 5/5 |

## starship

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 50ms | 79ms | 651ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 47ms | 169ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 34ms | 19ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 42ms | 5ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 37ms | 41ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 27ms | 118ms | 8632ms | 3/5 | 3/5 | 5/5 |

## spring-boot

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 472ms | 770ms | 131962ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 508ms | 916ms | 12ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 263ms | 17ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 4ms | 388ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 271ms | 294ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 348ms | 957ms | 26501ms | 5/5 | 3/5 | 5/5 |

## spark

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 545ms | 2659ms | 355025ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 1102ms | 4929ms | 13ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 612ms | 16ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 7ms | 1376ms | 1ms | 3/5 | 4/5 | 4/5 |
| Code Navigation | 548ms | 1201ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 477ms | 3957ms | 40609ms | 5/5 | 5/5 | 5/5 |

## vapor

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 43ms | 126ms | 416ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 38ms | 204ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 33ms | 17ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 0ms | 50ms | 0ms | 3/5 | 0/5 | 2/5 |
| Code Navigation | 34ms | 48ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 21ms | 142ms | 422ms | 3/5 | 3/5 | 5/5 |

## wordpress

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 150ms | 1497ms | 35900ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 243ms | 2236ms | 4ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 75ms | 20ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 2ms | 807ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 78ms | 789ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 96ms | 2451ms | 10259ms | 5/5 | 5/5 | 5/5 |

## protobuf

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 104ms | 515ms | 16255ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 94ms | 705ms | 4ms | 5/5 | 4/5 | 5/5 |
| Dependency Tracing | 56ms | 19ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 1ms | 197ms | 39ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 73ms | 178ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 73ms | 506ms | 15586ms | 5/5 | 3/5 | 5/5 |

## crystal-lang

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 93ms | 0ms | 1351ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 82ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Dependency Tracing | 55ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 0ms | 3/5 | 1/5 | 2/5 |
| Code Navigation | 59ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 55ms | 0ms | 36646ms | 5/5 | 1/5 | 5/5 |

## dart-sdk

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 901ms | 0ms | 14803ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 2188ms | 0ms | 2ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 967ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 12ms | 0ms | 2ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 1239ms | 0ms | 1ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 962ms | 0ms | 25243ms | 5/5 | 1/5 | 5/5 |

## elixir-lang

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 54ms | 30ms | 2484ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 53ms | 184ms | 1ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 40ms | 20ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 16ms | 0ms | 3/5 | 0/5 | 2/5 |
| Code Navigation | 42ms | 142ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 27ms | 404ms | 3860ms | 5/5 | 5/5 | 5/5 |

## emqx

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 115ms | 0ms | 363ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 96ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Dependency Tracing | 64ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 66ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 64ms | 0ms | 28324ms | 5/5 | 1/5 | 5/5 |

## fsharp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 206ms | 0ms | 904ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 202ms | 0ms | 0ms | 3/5 | 1/5 | 5/5 |
| Dependency Tracing | 115ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 2ms | 0ms | 0ms | 3/5 | 1/5 | 2/5 |
| Code Navigation | 114ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 181ms | 0ms | 156736ms | 5/5 | 1/5 | 5/5 |

## ggplot2

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 55ms | 0ms | 28ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 52ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 39ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 3/5 | 1/5 | 2/5 |
| Code Navigation | 39ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 31ms | 0ms | 11662ms | 3/5 | 1/5 | 5/5 |

## iterm2

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 140ms | 0ms | 10549ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 116ms | 0ms | 2ms | 5/5 | 1/5 | 5/5 |
| Dependency Tracing | 69ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 3ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 73ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 66ms | 0ms | 10970ms | 5/5 | 1/5 | 5/5 |

## julia

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 79ms | 0ms | 2396ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 76ms | 0ms | 1ms | 5/5 | 1/5 | 4/5 |
| Dependency Tracing | 48ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 5ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 51ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 43ms | 0ms | 25193ms | 5/5 | 1/5 | 5/5 |

## kemal

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 40ms | 0ms | 6ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 35ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 35ms | 0ms | 0ms | 3/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 3/5 | 1/5 | 2/5 |
| Code Navigation | 33ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 20ms | 0ms | 1396ms | 3/5 | 1/5 | 5/5 |

## metabase

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 406ms | 0ms | 23547ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 429ms | 0ms | 1ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 232ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 5ms | 0ms | 124ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 234ms | 0ms | 1ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 289ms | 0ms | 35924ms | 5/5 | 1/5 | 5/5 |

## mojo-perl

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 42ms | 0ms | 140ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 37ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 29ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 4/5 | 1/5 | 2/5 |
| Code Navigation | 31ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 21ms | 0ms | 4607ms | 3/5 | 1/5 | 5/5 |

## nickel

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 51ms | 118ms | 999ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 51ms | 192ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 36ms | 15ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 54ms | 0ms | 3/5 | 3/5 | 2/5 |
| Code Navigation | 36ms | 47ms | 0ms | 3/5 | 3/5 | 5/5 |
| Semantic Search | 26ms | 149ms | 13101ms | 3/5 | 3/5 | 5/5 |

## nim

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 92ms | 0ms | 228ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 83ms | 0ms | 0ms | 3/5 | 1/5 | 1/5 |
| Dependency Tracing | 51ms | 0ms | 0ms | 3/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 0ms | 4/5 | 1/5 | 2/5 |
| Code Navigation | 52ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 47ms | 0ms | 50664ms | 3/5 | 1/5 | 5/5 |

## ocaml

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 108ms | 0ms | 1066ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 99ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Dependency Tracing | 59ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 8ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 59ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 73ms | 0ms | 56098ms | 5/5 | 1/5 | 5/5 |

## otp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 252ms | 0ms | 13837ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 229ms | 0ms | 3ms | 4/5 | 1/5 | 5/5 |
| Dependency Tracing | 124ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 3ms | 0ms | 17ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 215ms | 0ms | 2ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 152ms | 0ms | 25006ms | 3/5 | 1/5 | 5/5 |

## perl5

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 168ms | 0ms | 4051ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 146ms | 0ms | 1ms | 3/5 | 1/5 | 5/5 |
| Dependency Tracing | 91ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 2ms | 0ms | 4ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 88ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Semantic Search | 81ms | 0ms | 96257ms | 5/5 | 1/5 | 5/5 |

## ring

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 40ms | 0ms | 10ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 39ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 34ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 3/5 | 1/5 | 2/5 |
| Code Navigation | 35ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 19ms | 0ms | 1662ms | 3/5 | 1/5 | 5/5 |

## Summary Averages

| Metric | grep | ast-grep | code-intel |
|--------|------|----------|------------|
| Avg Time | 106ms | 351ms | 8455ms |
| Avg Quality | 4.0/5 | 2.1/5 | 4.2/5 |
| Total Output | 157,843,866 chars | 11,982,475 chars | 780,784 chars |
