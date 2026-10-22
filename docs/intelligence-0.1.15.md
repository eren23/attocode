# Attocode Intelligence 0.1.15

0.1.15 isolates native parser state between threads, gives language-server stderr
one reader, and continues bounded recovery when unresolved native lookups have no
static callers. The standalone package remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.15
```

Restart the MCP connection after upgrading so it loads the new package.

## Changes

- **Native parser ownership.** Each thread reuses its own parser cache, preventing
  another worker from resuming a different document's timed-out parser state.
  The existing 100 ms native parse limit and recovery behavior remain unchanged.
- **One stderr reader.** Language-server diagnostics use the existing dedicated
  drain. Competing readers no longer steal output or trigger concurrent-read errors.
- **Recovery without static callers.** An unresolved definition and empty native
  references continue within the existing two-second deadline and four-attempt
  cap. Resolved unused declarations keep their fast path; persistent nulls remain
  partial evidence.
- **Rust startup diagnostics.** Opt-in CI capture retains initialization, document
  generations, protocol traffic, stderr and the first failure stage, with explicit
  byte limits and completeness markers. It adds no protocol requests or reader.
- **Verification on GitHub runners.** Product CI checks the candidate wheel and
  sdist against source, clean installs and upgrades from 0.1.14. After publication,
  the release workflow checks the actual PyPI artifacts and both installed Python
  trees, CLI/MCP/init/doctor behavior and bounded search continuation. Reports and
  logs are retained even on failure.

## Verification and limits

The implementation regressions demonstrate parser-state leakage, competing stderr
readers and early termination without static callers. They do not establish the
original intermittent Rust readiness or OCaml cold-parse trigger. These remain
open investigations. Existing parser limits, tool profiles and ranking defaults
remain unchanged; no relevance, agent-benefit or restart-speed gain is claimed.

The GitHub release records the exact release workflow, uploaded test evidence,
actual PyPI verification and artifact hashes. Publication does not upgrade any
global installation or restart an existing host connection.
