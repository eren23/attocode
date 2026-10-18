# Attocode Intelligence 0.1.10

0.1.10 changes the search order for "tested" questions and counts Swift test
folders as tests. The standalone distribution remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.10
```

Restart the MCP connection after you upgrade.

## Changes

- **"tested" questions.** A short search with "tested" or "testing" (and no
  "test" or "tests") keeps the source-first order and shows the best test hit
  second. Before, the test file often missed the first five results.
  Searches with "test" or "tests" do not change: test hits still go first.
- **Swift and Xcode test folders.** Files under `Tests/` or `Specs/` (any
  letter case) and under Xcode test targets such as `ModernTests/` or
  `MyAppUITests/` are now test files. Before, only lowercase `test/` and
  `tests/` folders counted, so Swift tests ranked as source in default search.
  The singular `Test/` folder and file names such as
  `NoForceTryInTests.swift` do not count, because they can be source code.

Indexes and caches do not change. Both changes apply when a search runs.
Client configurations do not change.

## Measured effect

On 16 new frozen validation questions over aspnetcore, luarocks, zls and otp,
judged files at five went from 14 to 16 with no individual loss. See the
["tested" questions report](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-test-source-slot.md).

Of 36 cached pinned packs, the Swift rule changes the test classification of
files in only three: SwiftFormat (219 files), iTerm2 (130) and aspnetcore (55,
all in test folders). On 12 consumed questions in SwiftFormat and aspnetcore,
one exact-symbol control gained its judged file and quote at five, with no
loss.

## Rejected search candidate

For "test" and "tests" searches, a candidate moved the source file named by
the best test hit (`FooTest.java` to `Foo.java`) to second place. It gained
two judged files on development and none on 16 new validation questions over
crystal, dart-sdk, postgrest and ring, so it does not ship. Most tests check
code in a file with another name. See the
[paired source report](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-18-paired-source.md).

Release-specific install, upgrade and publication results are recorded in the
GitHub release after publication. No cloud benchmark, agent study or model
download is part of this release.
