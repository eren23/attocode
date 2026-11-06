# Attocode Intelligence 0.1.27

Version 0.1.27 fixes a dictionary-size error during symbol inspection while the
workspace's AST cache is being hydrated.

## Namespace resolution during hydration

Namespace resolution previously iterated the live cache of parsed files. A
background hydration thread could add or remove a file during that iteration,
raising `RuntimeError: dictionary changed size during iteration`.

Each namespace build now takes a shallow snapshot of cached file membership.
That build keeps its starting membership; the next build sees subsequent additions
and removals. Hydration and partial-evidence reporting continue as before.

Two deterministic regression cases coordinate cache growth and shrinkage with a
writer thread. They check that the current build completes with its original
members and that a subsequent build sees the updated cache.

## Install or upgrade

Install with `uv tool install attocode-code-intel==0.1.27`, or upgrade an existing
installation with `uv tool upgrade attocode-code-intel`. Restart the MCP server
after upgrading so the running process loads the new version.
