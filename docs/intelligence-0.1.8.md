# Attocode Intelligence 0.1.8

0.1.8 makes change reports easier to focus and reduces repeated class evidence.
The standalone distribution remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.8
cd /path/to/project
attocode-code-intel changes --file src/worker.py --symbol Worker.work
attocode-code-intel changes --class-mode expand
```

Repeat `--file` and `--symbol` for several exact paths or names. Filters intersect,
match either side of a rename/source change and apply before result caps. Reports
distinguish unmatched selectors, excluded scope and capped omissions. Saved-report
refresh retains the selection; freshness still checks the complete Git snapshot.

Changed classes now default to bounded identity/member summaries. Changed methods
keep their caller paths, but class-wide callers are not collected by default.
Use `--class-mode expand` to retain the previous traversal or `trace` a class
directly. Removed/historical classes receive no current-caller follow-up.
Top-level bounds include caller, impact, test and summary limits.

Full local MCP `change_context` accepts `files`, `symbols` and
`class_mode="summary"` or `"expand"`. Daily keeps its 16 advertised tools; lean
and ranking defaults stay unchanged. Existing client configurations are preserved.
Restart the MCP connection after upgrading. See the
[workflow guide](guides/change-investigation.md) for evidence and limits.

Three historical Python fix replays preserved 45 non-class caller flows. The two
class-heavy reports shrank from 257,931 to 174,205 bytes (32.5%) and from 406,914
to 212,152 bytes (47.9%). Class-wide evidence is deliberately omitted in summary
mode; these measurements do not establish better agent outcomes or general speed.
See the [replay evidence](../packages/code-intel/evals/results/2026-10-17-focused-change-reports.md).

The feature package passed 952 local tests with nine environment skips and all
17 required upstream checks. Uploaded product artifacts verified all 22 focus,
29 existing workflow and 51 SQL/HTTP cases without skips on both Python 3.12 and
3.13, including PostgreSQL locking controls. The combined suite passed 3,948 tests
with 29 skipped/expected-failure cases. The unchanged ranking gate, four real
language servers, Linux/macOS wheels, Docker and dashboard checks passed too.
Release-specific install, upgrade and publication results are recorded in the
GitHub release after publication.

No new cloud benchmark, agent study or model download is included. The historical
Cockroach timing results are not fresh 0.1.8 validation.
