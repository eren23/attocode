# Perl module roots

This configuration is available in the development checkout and the next
maintenance release after 0.1.31.

For a workspace whose Perl modules live outside the root or `lib`, set explicit
roots in `.attocode/config.toml`:

```toml
[perl]
module_roots = ["lib", "dist/Carp/lib"]
```

An explicit list replaces the defaults. Include `"."` if modules directly under
the workspace root should resolve too. An empty list disables static Perl module
lookup. Without this setting, the defaults are `"."` and `"lib"`.

Roots must be workspace-relative directories. Separators and dot components are
normalized, and duplicate roots are removed. Safe internal symlinks resolve to
their physical workspace path. Absolute paths, parent traversal, control
characters, outward symlinks and non-string entries are skipped. A safe root
that does not exist cannot add any files. Missing, malformed or incorrectly
typed outer configuration keeps the defaults. The loader accepts only a
contained regular configuration file of at most 1,000,000 bytes.

Roots affect resolution over files already discovered by the index. They do
not override exclusions. For example, to include just the `dist/Carp` source
distribution under an otherwise excluded build directory, add this to the
workspace's root `.gitignore`:

```gitignore
!dist/
dist/*
!dist/Carp/
```

If multiple configured roots contain the same module, resolution stays
unresolved; list order does not select a winner. Definitions remain searchable
in their own files. Perl `.t` test scripts participate when discovered.

Changes to effective roots are picked up on the next tool operation and after
reopening the workspace, even when source files have not changed. Reordering
roots or changing unrelated remote settings keeps the same dependency policy.
Saving remote settings preserves existing TOML data, including these roots;
comments and formatting may change.

This is conservative static resolution. The index does not execute Perl,
evaluate `use lib` or `BEGIN`, or read runtime `@INC` and global module paths.
Native syntax and literal call evidence do not prove a runtime binding.
