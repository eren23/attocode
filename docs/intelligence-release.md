# Releasing Attocode Intelligence

The standalone distribution has its own version in `packages/code-intel/pyproject.toml` and release tags named `intel-vVERSION`. The legacy agent continues to use its existing `v*` tags.

## Release gate

A release checks quality and install health. It runs the product tests, the navigation gate, the ranking gate, and a clean install of the wheel on Linux and macOS. The wheel check starts the installed command as a stdio server, lists the daily tools and runs one search.

`packages/code-intel/evals/release_gate.py` checks agent speed: 720 paired agent runs with a median speedup of 20% or more. A release does not need it. Run it before a release says that agents are faster with the server. The agent studies so far found no such gain (see `packages/code-intel/evals/results/2026-10-10-agent-pilot.md` and `2026-10-10-agent-r3.md`).

## One-time publisher setup

The repository's GitHub environment `pypi-intelligence` accepts only `intel-v*` tags. In the maintainer's [PyPI publishing settings](https://pypi.org/manage/account/publishing/), create a pending GitHub publisher with these exact values:

| Field | Value |
|---|---|
| PyPI project | `attocode-code-intel` |
| GitHub owner | `eren23` |
| Repository | `attocode` |
| Workflow filename | `release-intelligence.yml` |
| Environment | `pypi-intelligence` |

PyPI creates the project on the first successful upload. A pending publisher does not reserve its name. This flow needs no API token in repository secrets. See [PyPI's pending publisher documentation](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

The 0.1.0 release created the project on 2026-10-11. The pending publisher is now an ordinary trusted publisher of the project, so later releases skip this step.

## The agent package depends on this package

`attocode` depends on `attocode-code-intel>=0.1.0,<0.2`. In the repository, the uv workspace installs the local source. A published `attocode` wheel gets the package from PyPI. Thus, when an `attocode` change needs new code in `attocode_intel`, release `attocode-code-intel` first. A 0.2 release of this package also needs a new upper bound in the root `pyproject.toml`.

## Release

1. Update the version in `packages/code-intel/pyproject.toml` and in `src/attocode_intel/__init__.py`. A test fails when the two differ. The CLI, the MCP server and the HTTP API read `__version__`. Refresh `uv.lock`, and merge a reviewed change with passing Intelligence checks.
2. Tag the validated commit, for example `git tag -a intel-v0.1.0 -m 'Attocode Intelligence 0.1.0'`, then push that tag.
3. Follow **Release intelligence** in GitHub Actions. It runs the full reusable checks: Python 3.12/3.13 product tests against migrated PostgreSQL, navigation budgets, generated catalog, standalone wheel isolation on Linux and macOS, dashboard build, and Docker runtime smoke test. It also runs the ranking gate. The release build then verifies the version/tag match and publishes the wheel and source distribution through GitHub OIDC.
4. Verify a clean `uv tool install attocode-code-intel==0.1.0`, run `init` and `doctor` in a disposable project, then create the GitHub release with installation instructions and the validation results.

If PyPI reports `invalid-publisher`, check the exact account settings above and rerun the failed publishing job after correcting them. Do not move an already published tag or reuse a published version. A package release does not deploy a hosted service.

If a workflow bug prevents publication, fix and merge the workflow through normal
CI, verify that the version is still absent from PyPI, and use a new tag such as
`intel-v0.1.5-retry.1`. The optional `-retry.N` suffix names the publishing attempt;
the package version remains `0.1.5`. Preserve the failed original tag and run all
release gates again. Confirm that package source and dependencies match the
original candidate when claiming a workflow-only retry. Never use this path to
replace a version that has already been uploaded to PyPI.
