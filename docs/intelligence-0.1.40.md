# Attocode Intelligence 0.1.40

Version 0.1.40 corrects MCP resource discovery for the selected tool profile.
Earlier versions advertised templates whose backing operations that profile could
not call. A client could discover one of these resources and then fail to read it.

## Upgrade

```sh
uv tool install --python 3.12 'attocode-code-intel==0.1.40'
attocode-code-intel --version
```

Reconnect the host MCP connection after installation to load the new package.
The CLI version does not identify an existing server process.

## Resource templates

| Profile | Advertised templates |
| --- | --- |
| Local daily | Project files and symbol references |
| Local lean | None |
| Local full | Project files, symbol references, and repository knowledge |
| Remote daily or full | Project files, symbol references, and repository knowledge |

The guidelines resource remains available in every profile. These profiles apply
to stdio and native HTTP. Legacy SSE retains its older server behavior.

Template discovery now uses the active MCP tool catalog. The resource read
handler still checks profile availability and remote repository authorization.
An excluded operation remains unavailable through a direct resource URI.

## Verification and limits

Seven maintained stdio cases check discovery, successful reads, guidelines, and
excluded direct reads across local daily, full, and lean profiles. Authenticated
HTTP controls check remote daily/full template lists, knowledge reads, and denied
cross-tenant reads with cancellation off and on.

The denial checks require an error without identifying its exact cause. Successful
remote project/symbol resource reads and invalid-profile responses have no new
protocol tests. Local HTTP has source reasoning but no new direct transport test.
These checks do not establish discovery latency, host UI behavior, or compatibility
with every SDK version.

Maintained release gates cover Python 3.12/3.13, PostgreSQL, engine/product suites,
native grammars, real language servers, macOS wheels, and clean installs/upgrades
from published 0.1.39. Publication verification binds actual packages to tagged
source. Hosted features remain opt-in.

The saved-index and search freshness corrections in
[0.1.39](intelligence-0.1.39.md), [0.1.38](intelligence-0.1.38.md), and
[0.1.37](intelligence-0.1.37.md) retain their existing boundaries.
