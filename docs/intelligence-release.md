# Releasing Attocode Intelligence

The standalone distribution has its own version in `packages/code-intel/pyproject.toml` and release tags named `intel-vVERSION`. The legacy agent continues to use its existing `v*` tags.

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

## Release

1. Update the package version and CLI version together, refresh `uv.lock`, and merge a reviewed change with passing Intelligence checks.
2. Tag the validated commit, for example `git tag -a intel-v0.1.0 -m 'Attocode Intelligence 0.1.0'`, then push that tag.
3. Follow **Release intelligence** in GitHub Actions. It runs the full reusable checks: Python 3.12/3.13 product tests against migrated PostgreSQL, navigation budgets, generated catalog, standalone wheel isolation, dashboard build, and Docker runtime smoke test. The release build then verifies the version/tag match and publishes the wheel and source distribution through GitHub OIDC.
4. Verify a clean `uv tool install attocode-code-intel==0.1.0`, run `init` and `doctor` in a disposable project, then create the GitHub release with installation instructions and the validation results.

If PyPI reports `invalid-publisher`, check the exact account settings above and rerun the failed publishing job after correcting them. Do not move an already published tag or reuse a published version. A package release does not deploy a hosted service.
