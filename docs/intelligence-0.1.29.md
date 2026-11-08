# Attocode Intelligence 0.1.29

Version 0.1.29 recognizes Perl `.t` test scripts across discovery and parsing,
restoring their native imports and caller evidence when a Perl grammar is
installed or cached.

## Perl test navigation

Test ranking already recognized `.t` paths as test candidates, but the parser's
extension mappings assigned them an unknown language. Both the canonical AST
entry point and direct generic-parser inference now select Perl for `.t` files.
Grammar acquisition remains explicit; navigation uses installed or cached grammars.

Four additional maintained regressions cover shared language identity and three
unchanged files from `Perl/perl5@ef53bc6892cb851320be193e8cd9b15b2494e24c`.
The fixture checks the real `Carp::croak` definition, a qualified test call,
an importer and a suggested test. All eight navigation checks run within the
actual `dist/Carp` distribution root, whose `lib/` layout follows existing
conservative import resolution.

A separate repository-root check verifies default `dist/` exclusion, narrow
Carp inclusion, live refresh, restart and subsequent exclusion while preserving
unrelated generated-directory exclusions. The acquired-grammar gate requires
83 cases with no skips. Source bytes, hashes and witness lines are checked before
navigation; the fixture is used only as source data.

These checks establish targeted syntax and heuristic relationships in the pinned
distribution. Complex Perl syntax can still yield partial parser evidence, and
custom repository-wide runtime load paths remain outside this fixture's scope.

## Install or upgrade

Install with `uv tool install attocode-code-intel==0.1.29`, or upgrade an existing
installation with `uv tool upgrade attocode-code-intel`. Restart the MCP server
after upgrading so the running process loads the new version.
