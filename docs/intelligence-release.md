# Releasing Attocode Intelligence

The standalone distribution has its own version in `packages/code-intel/pyproject.toml` and release tags named `intel-vVERSION`. Historical agent `v*` tags remain preserved; the active repository publishes intelligence only.

See the [0.1.19 release notes](intelligence-0.1.19.md) for the latest changes and upgrade instructions.

## Release gate

A release checks quality and install health. It runs engine/product tests, PostgreSQL, bounded navigation, the ranking gate, real language servers, and clean wheel checks on Linux and macOS. The wheel check starts daily/lean stdio sessions and exercises navigation/search. It also verifies full-profile change investigation and CLI export/check/refresh from the installed package. The historical 36-pack cloud matrix is separate evidence; a standard release does not implicitly authorize a fresh cloud rental or agent study.

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

## Historical agent compatibility

Previously published agent distributions depend on `attocode-code-intel>=0.1.0,<0.2`. The root is now a development workspace, with no agent package or agent release workflow. Preserve the standalone identity and existing compatibility within 0.1.x; do not repurpose the published `attocode` distribution. See [legacy agent migration](legacy-agent.md).

## Release

### Verification on GitHub runners

Product CI runs the maintained candidate verifier for Python 3.12 and 3.13,
including clean installs and upgrades from 0.1.18. The release workflow runs
`published-verification` after PyPI publication, checking actual published artifact
hashes, source/tag identity and both installed trees. Its
`intelligence-published-verification` artifact retains the report and logs, even
on failure. A failed post-publication check does not undo an uploaded PyPI version;
preserve the tag and investigate before creating the GitHub release.

The commands below describe the same maintained verifier for an explicitly chosen
remote or disposable environment. Repository operators keep broad and release
installation validation on runners.

<a id="maintained-local-verification"></a>

### Maintained verifier

From the development workspace, verify a built wheel and source distribution
before publication. Use the candidate's actual version and an older released
baseline; development source is recorded as a working tree:

```sh
.venv/bin/python packages/code-intel/scripts/check_release.py candidate \
  --version 0.1.19 --baseline-version 0.1.18 --source . \
  --wheel dist/attocode_code_intel-0.1.19-py3-none-any.whl \
  --sdist dist/attocode_code_intel-0.1.19.tar.gz \
  --allow-downloads --report /tmp/intelligence-candidate.json
```

The verifier creates isolated clean and upgrade environments. It compares both
installed Python trees and versions with the wheel and source, runs CLI/MCP,
init/doctor and bounded search continuation checks, and writes a JSON report
with identities, timings, resource limits and cleanup outcomes. It refuses to
overwrite a report. Downloads require `--allow-downloads`; offline checks need
`--wheelhouse` with every dependency and `--baseline-wheel`.

After publication, run `published` with the same version, baseline, source and
report options, omitting `--wheel` and `--sdist`. It fetches the exact PyPI wheel
and sdist and checks their published hashes. Published source must be at the
matching `intel-vVERSION` tag, with package Python inputs and `pyproject.toml`
matching tag blobs. Local notes outside those inputs can remain untracked.
The verifier does not publish, change tags, or restart another client's MCP.

### Publication steps

1. Update the version in `packages/code-intel/pyproject.toml` and in `packages/code-intel/src/attocode_intel/__init__.py`. A test fails when the two differ. The CLI, the MCP server and the HTTP API read `__version__`. Refresh `uv.lock`, and merge a reviewed change with passing Intelligence checks.
2. Tag the validated commit, for example `git tag -a intel-v0.1.0 -m 'Attocode Intelligence 0.1.0'`, then push that tag.
3. Follow **Release intelligence** in GitHub Actions. It runs the full reusable checks: Python 3.12/3.13 product tests against migrated PostgreSQL, navigation budgets, generated catalog, standalone wheel isolation on Linux and macOS, dashboard build, and Docker runtime smoke test. It also runs the ranking gate. The release build then verifies the version/tag match and publishes the wheel and source distribution through GitHub OIDC.
4. Verify that `published-verification` passed on the GitHub runner, including clean installation, upgrade, `init`, `doctor`, installed identities and continuation. Download its report and exact PyPI artifacts, verify their hashes, then create the GitHub release with installation instructions and validation results.

If PyPI reports `invalid-publisher`, check the exact account settings above and rerun the failed publishing job after correcting them. Do not move an already published tag or reuse a published version. A package release does not deploy a hosted service.

If a release-gate failure prevents publication, diagnose, fix and merge it through
normal CI, verify that the version is still absent from PyPI, and use a new tag such as
`intel-v0.1.5-retry.1`. The optional `-retry.N` suffix names the publishing attempt;
the package version remains `0.1.5`. Preserve the failed original tag and run all
release gates again. Record packaged-source changes in a repaired candidate;
confirm source and dependencies match when claiming a workflow-only retry. Never use this path to
replace a version that has already been uploaded to PyPI.
