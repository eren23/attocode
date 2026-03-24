# 3-Way Code Intelligence Comparison

Generated: 2026-03-24 12:34
Tools: grep, ast-grep, code-intel
Repos: attocode, fastapi, pandas, deno, aspnetcore, laravel, swiftformat, okhttp, gh-cli, faker, redis, spdlog, cats-effect, luarocks, phoenix, postgrest, acme-sh, terraform-eks, zls, cockroach, express, prisma, rails, requests, cosmopolitan, ripgrep, starship, spring-boot, spark, vapor, wordpress, protobuf, crystal-lang, dart-sdk, elixir-lang, emqx, fsharp, ggplot2, iterm2, julia, kemal, metabase, mojo-perl, nickel, nim, ocaml, otp, perl5, ring

## attocode

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 59ms | 348ms | — | 3/5 | 1/5 | — |
| Symbol Discovery | 44ms | 396ms | — | 4/5 | 4/5 | — |
| Dependency Tracing | 26ms | 10ms | — | 5/5 | 4/5 | — |
| Architecture | 0ms | 114ms | — | 3/5 | 0/5 | — |
| Code Navigation | 25ms | 106ms | — | 4/5 | 4/5 | — |
| Semantic Search | 31ms | 301ms | — | 5/5 | 3/5 | — |

## fastapi

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 78ms | 160ms | 1775ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 83ms | 226ms | 1ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 35ms | 14ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 54ms | 150ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 36ms | 61ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 41ms | 150ms | 24157ms | 3/5 | 3/5 | 5/5 |

## pandas

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 66ms | 906ms | 26978ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 71ms | 1144ms | 7ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 37ms | 28ms | 0ms | 5/5 | 5/5 | 5/5 |
| Architecture | 1ms | 274ms | 37ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 48ms | 321ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 48ms | 940ms | 8738ms | 5/5 | 5/5 | 5/5 |

## deno

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 269ms | 486ms | 53792ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 250ms | 791ms | 3ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 134ms | 17ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 3ms | 211ms | 10ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 137ms | 173ms | 1ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 145ms | 600ms | 36512ms | 5/5 | 3/5 | 5/5 |

## aspnetcore

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 338ms | 1880ms | 89011ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 366ms | 3628ms | 7ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 185ms | 13ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 5ms | 1021ms | 7ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 192ms | 851ms | 0ms | 5/5 | 0/5 | 5/5 |
| Semantic Search | 227ms | 2695ms | 24577ms | 5/5 | 1/5 | 5/5 |

## laravel

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 81ms | 457ms | 13331ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 79ms | 513ms | 4ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 46ms | 17ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 203ms | 2ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 51ms | 168ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 43ms | 482ms | 3277ms | 5/5 | 3/5 | 5/5 |

## swiftformat

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 39ms | 312ms | 1571ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 37ms | 460ms | 2ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 25ms | 15ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 0ms | 120ms | 0ms | 3/5 | 2/5 | 4/5 |
| Code Navigation | 29ms | 108ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 22ms | 336ms | 1251ms | 3/5 | 3/5 | 5/5 |

## okhttp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 52ms | 178ms | 1438ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 51ms | 227ms | 1ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 33ms | 17ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 83ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 36ms | 72ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 28ms | 235ms | 1814ms | 3/5 | 3/5 | 5/5 |

## gh-cli

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 51ms | 259ms | 2548ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 47ms | 355ms | 1ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 33ms | 14ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 101ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 37ms | 98ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 32ms | 274ms | 2940ms | 3/5 | 3/5 | 5/5 |

## faker

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 45ms | 107ms | 1652ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 47ms | 96ms | 1ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 31ms | 15ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 44ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 34ms | 29ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 33ms | 88ms | 4147ms | 5/5 | 3/5 | 5/5 |

## redis

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 60ms | 542ms | 5374ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 54ms | 657ms | 2ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 37ms | 24ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 259ms | 8ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 37ms | 238ms | 0ms | 5/5 | 2/5 | 5/5 |
| Semantic Search | 37ms | 693ms | 6976ms | 5/5 | 5/5 | 5/5 |

## spdlog

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 32ms | 53ms | 1196ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 27ms | 84ms | 0ms | 4/5 | 5/5 | 4/5 |
| Dependency Tracing | 26ms | 23ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 21ms | 4ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 25ms | 19ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 16ms | 61ms | 933ms | 3/5 | 2/5 | 5/5 |

## cats-effect

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 46ms | 185ms | 808ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 51ms | 345ms | 1ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 34ms | 27ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 89ms | 0ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 31ms | 79ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 23ms | 265ms | 1286ms | 5/5 | 3/5 | 5/5 |

## luarocks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 38ms | 46ms | 174ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 36ms | 69ms | 0ms | 5/5 | 4/5 | 4/5 |
| Dependency Tracing | 26ms | 18ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 43ms | 0ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 28ms | 32ms | 0ms | 4/5 | 3/5 | 5/5 |
| Semantic Search | 21ms | 99ms | 3670ms | 3/5 | 3/5 | 5/5 |

## phoenix

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 37ms | 15ms | 1053ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 39ms | 77ms | 0ms | 3/5 | 5/5 | 5/5 |
| Dependency Tracing | 28ms | 17ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 12ms | 0ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 30ms | 51ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 21ms | 159ms | 1732ms | 5/5 | 3/5 | 5/5 |

## postgrest

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 34ms | 46ms | 3322ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 33ms | 73ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 26ms | 13ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 39ms | 0ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 28ms | 32ms | 0ms | 4/5 | 3/5 | 5/5 |
| Semantic Search | 19ms | 103ms | 2323ms | 5/5 | 3/5 | 5/5 |

## acme-sh

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 34ms | 19ms | 223ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 32ms | 53ms | 0ms | 3/5 | 0/5 | 4/5 |
| Dependency Tracing | 27ms | 0ms | 0ms | 5/5 | 2/5 | 5/5 |
| Architecture | 0ms | 13ms | 0ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 28ms | 46ms | 0ms | 4/5 | 2/5 | 5/5 |
| Semantic Search | 16ms | 134ms | 168ms | 3/5 | 1/5 | 5/5 |

## terraform-eks

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 29ms | 35ms | 160ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 30ms | 63ms | 0ms | 3/5 | 5/5 | 4/5 |
| Dependency Tracing | 23ms | 0ms | 0ms | 5/5 | 2/5 | 5/5 |
| Architecture | 0ms | 34ms | 0ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 25ms | 37ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 17ms | 99ms | 834ms | 3/5 | 3/5 | 5/5 |

## zls

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 32ms | 0ms | 326ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 30ms | 0ms | 0ms | 4/5 | 1/5 | 4/5 |
| Dependency Tracing | 26ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 27ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Semantic Search | 14ms | 0ms | 224ms | 3/5 | 1/5 | 5/5 |

## cockroach

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 414ms | 3384ms | 424704ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 461ms | 4323ms | 19ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 262ms | 20ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 4ms | 1938ms | 27ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 263ms | 1144ms | 1ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 292ms | 3431ms | 41541ms | 5/5 | 3/5 | 5/5 |

## express

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 37ms | 67ms | 313ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 29ms | 78ms | 0ms | 3/5 | 3/5 | 1/5 |
| Dependency Tracing | 27ms | 16ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 53ms | 0ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 27ms | 27ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 17ms | 78ms | 813ms | 3/5 | 3/5 | 5/5 |

## prisma

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 134ms | 196ms | 4924ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 133ms | 386ms | 0ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 74ms | 16ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 1ms | 92ms | 21ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 74ms | 91ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 93ms | 275ms | 8336ms | 5/5 | 3/5 | 5/5 |

## rails

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 132ms | 1121ms | 18831ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 125ms | 681ms | 6ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 67ms | 19ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 1ms | 447ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 73ms | 260ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 71ms | 665ms | 10678ms | 5/5 | 5/5 | 5/5 |

## requests

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 35ms | 88ms | 125ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 35ms | 134ms | 0ms | 4/5 | 4/5 | 5/5 |
| Dependency Tracing | 33ms | 20ms | 0ms | 5/5 | 4/5 | 5/5 |
| Architecture | 0ms | 29ms | 1ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 36ms | 30ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 19ms | 89ms | 863ms | 3/5 | 3/5 | 5/5 |

## cosmopolitan

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 425ms | 3239ms | 197838ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 332ms | 4314ms | 16ms | 5/5 | 5/5 | 4/5 |
| Dependency Tracing | 169ms | 17ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 3ms | 1546ms | 269ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 208ms | 1355ms | 0ms | 5/5 | 4/5 | 1/5 |
| Semantic Search | 254ms | 3846ms | 46148ms | 5/5 | 3/5 | 5/5 |

## ripgrep

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 42ms | 111ms | 596ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 35ms | 171ms | 0ms | 4/5 | 2/5 | 5/5 |
| Dependency Tracing | 27ms | 15ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 47ms | 0ms | 4/5 | 3/5 | 4/5 |
| Code Navigation | 30ms | 47ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 19ms | 137ms | 1631ms | 3/5 | 3/5 | 5/5 |

## starship

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 49ms | 78ms | 650ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 45ms | 155ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 35ms | 18ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 38ms | 4ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 36ms | 39ms | 0ms | 4/5 | 4/5 | 5/5 |
| Semantic Search | 27ms | 111ms | 7386ms | 3/5 | 3/5 | 5/5 |

## spring-boot

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 477ms | 748ms | 139319ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 454ms | 872ms | 11ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 361ms | 17ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 4ms | 364ms | 7ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 282ms | 286ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 335ms | 882ms | 30258ms | 5/5 | 3/5 | 5/5 |

## spark

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 531ms | 2682ms | 350842ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 658ms | 5085ms | 13ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 337ms | 19ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 6ms | 1404ms | 6ms | 3/5 | 4/5 | 4/5 |
| Code Navigation | 349ms | 1233ms | 0ms | 5/5 | 5/5 | 5/5 |
| Semantic Search | 466ms | 4117ms | 42265ms | 5/5 | 5/5 | 5/5 |

## vapor

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 48ms | 132ms | 415ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 38ms | 209ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 34ms | 19ms | 0ms | 5/5 | 3/5 | 5/5 |
| Architecture | 0ms | 47ms | 0ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 35ms | 48ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 22ms | 154ms | 423ms | 3/5 | 3/5 | 5/5 |

## wordpress

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 146ms | 1587ms | 40230ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 128ms | 2185ms | 4ms | 4/5 | 5/5 | 5/5 |
| Dependency Tracing | 77ms | 20ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 1ms | 824ms | 2ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 78ms | 785ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 97ms | 2285ms | 9616ms | 5/5 | 5/5 | 5/5 |

## protobuf

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 100ms | 459ms | 16896ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 91ms | 720ms | 4ms | 5/5 | 4/5 | 5/5 |
| Dependency Tracing | 57ms | 20ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 1ms | 203ms | 37ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 72ms | 169ms | 0ms | 5/5 | 3/5 | 5/5 |
| Semantic Search | 75ms | 518ms | 16919ms | 5/5 | 3/5 | 5/5 |

## crystal-lang

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 95ms | 0ms | 137ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 78ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Dependency Tracing | 54ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 58ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 55ms | 0ms | 45044ms | 5/5 | 1/5 | 5/5 |

## dart-sdk

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 901ms | 0ms | 16529ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 1355ms | 0ms | 2ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 882ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 11ms | 0ms | 1ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 881ms | 0ms | 2ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 791ms | 0ms | 23241ms | 5/5 | 1/5 | 5/5 |

## elixir-lang

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 54ms | 29ms | 2245ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 53ms | 175ms | 1ms | 5/5 | 5/5 | 5/5 |
| Dependency Tracing | 40ms | 19ms | 0ms | 5/5 | 0/5 | 5/5 |
| Architecture | 0ms | 17ms | 0ms | 3/5 | 0/5 | 4/5 |
| Code Navigation | 41ms | 126ms | 0ms | 5/5 | 4/5 | 5/5 |
| Semantic Search | 29ms | 382ms | 3790ms | 5/5 | 5/5 | 5/5 |

## emqx

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 115ms | 0ms | 348ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 96ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Dependency Tracing | 62ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 1ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 66ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 63ms | 0ms | 28908ms | 5/5 | 1/5 | 5/5 |

## fsharp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 210ms | 0ms | 912ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 197ms | 0ms | 0ms | 3/5 | 1/5 | 5/5 |
| Dependency Tracing | 109ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 2ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 112ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 180ms | 0ms | 883449ms | 5/5 | 1/5 | 5/5 |

## ggplot2

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 48ms | 0ms | 31ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 43ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 30ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 30ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 27ms | 0ms | 8468ms | 3/5 | 1/5 | 5/5 |

## iterm2

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 126ms | 0ms | 9019ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 106ms | 0ms | 2ms | 5/5 | 1/5 | 5/5 |
| Dependency Tracing | 71ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 2ms | 0ms | 3ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 65ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 63ms | 0ms | 5943ms | 5/5 | 1/5 | 5/5 |

## julia

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 71ms | 0ms | 2412ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 66ms | 0ms | 1ms | 5/5 | 1/5 | 4/5 |
| Dependency Tracing | 38ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 5ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 44ms | 0ms | 1ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 39ms | 0ms | 19592ms | 5/5 | 1/5 | 5/5 |

## kemal

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 30ms | 0ms | 5ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 28ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 26ms | 0ms | 0ms | 3/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 27ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 15ms | 0ms | 1094ms | 3/5 | 1/5 | 5/5 |

## metabase

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 388ms | 0ms | 22313ms | 3/5 | 1/5 | 5/5 |
| Symbol Discovery | 420ms | 0ms | 1ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 223ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 4ms | 0ms | 127ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 222ms | 0ms | 1ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 284ms | 0ms | 35980ms | 5/5 | 1/5 | 5/5 |

## mojo-perl

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 45ms | 0ms | 149ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 45ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 38ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 4/5 | 1/5 | 4/5 |
| Code Navigation | 37ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 22ms | 0ms | 6005ms | 3/5 | 1/5 | 5/5 |

## nickel

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 62ms | 140ms | 1020ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 57ms | 210ms | 0ms | 4/5 | 3/5 | 5/5 |
| Dependency Tracing | 43ms | 19ms | 0ms | 4/5 | 0/5 | 5/5 |
| Architecture | 0ms | 55ms | 1ms | 3/5 | 3/5 | 4/5 |
| Code Navigation | 47ms | 48ms | 0ms | 3/5 | 3/5 | 5/5 |
| Semantic Search | 31ms | 155ms | 17147ms | 3/5 | 3/5 | 5/5 |

## nim

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 100ms | 0ms | 232ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 91ms | 0ms | 0ms | 3/5 | 1/5 | 1/5 |
| Dependency Tracing | 61ms | 0ms | 0ms | 3/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 0ms | 4/5 | 1/5 | 4/5 |
| Code Navigation | 59ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 53ms | 0ms | 6617ms | 3/5 | 1/5 | 5/5 |

## ocaml

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 120ms | 0ms | 1075ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 105ms | 0ms | 1ms | 4/5 | 1/5 | 5/5 |
| Dependency Tracing | 67ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 8ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 67ms | 0ms | 0ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 77ms | 0ms | 73279ms | 5/5 | 1/5 | 5/5 |

## otp

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 260ms | 0ms | 13622ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 233ms | 0ms | 3ms | 4/5 | 1/5 | 5/5 |
| Dependency Tracing | 131ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 3ms | 0ms | 17ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 170ms | 0ms | 2ms | 5/5 | 1/5 | 1/5 |
| Semantic Search | 153ms | 0ms | 23894ms | 3/5 | 1/5 | 5/5 |

## perl5

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 171ms | 0ms | 5323ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 142ms | 0ms | 1ms | 3/5 | 1/5 | 5/5 |
| Dependency Tracing | 90ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Architecture | 1ms | 0ms | 4ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 88ms | 0ms | 0ms | 5/5 | 1/5 | 5/5 |
| Semantic Search | 80ms | 0ms | 94615ms | 5/5 | 1/5 | 5/5 |

## ring

| Task | grep | ast-grep | code-intel | grep Q | ast-grep Q | code-intel Q |
|------|------|----------|------------|--------|------------|--------------|
| Project Orientation | 42ms | 0ms | 10ms | 3/5 | 1/5 | 4/5 |
| Symbol Discovery | 40ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Dependency Tracing | 35ms | 0ms | 0ms | 4/5 | 1/5 | 5/5 |
| Architecture | 0ms | 0ms | 0ms | 3/5 | 1/5 | 4/5 |
| Code Navigation | 37ms | 0ms | 0ms | 4/5 | 1/5 | 1/5 |
| Semantic Search | 22ms | 0ms | 1867ms | 3/5 | 1/5 | 5/5 |

## Summary Averages

| Metric | grep | ast-grep | code-intel |
|--------|------|----------|------------|
| Avg Time | 94ms | 315ms | 10757ms |
| Avg Quality | 4.0/5 | 2.1/5 | 4.4/5 |
| Total Output | 157,846,121 chars | 11,982,480 chars | 872,707 chars |
