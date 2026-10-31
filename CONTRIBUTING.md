# Contributing to Attocode Intelligence

Python 3.12/3.13 and Git are supported. The root `pyproject.toml` is a virtual
workspace; `packages/code-intel` is the only publishable Python package. Keep
`attocode_intel` imports and the `attocode-code-intel` command stable.

## Repository layout

| Path | Contents |
|------|----------|
| `packages/code-intel/` | The product: `src/attocode_intel`, `tests`, `scripts` |
| `packages/code-intel/evals/` | Frozen study designs and results; not shipped in the wheel or sdist |
| `eval/` | Development and CI harness (`eval.quality`, `eval.matrix`); the product never imports it |
| `frontend/` | Dashboard, built into the service image |
| `docker/code-intel/` | Service image |
| `docs/`, `mkdocs.yml` | Documentation site |
| `scripts/` | CI helpers |

## Development

```sh
uv sync --locked --package attocode-code-intel --extra dev --extra service
uv run --no-sync python -m eval.quality local
```

The bounded local gate checks product contracts, scale and lifecycle behavior.
For the preserved engine and HTTP/MCP integration coverage:

```sh
uv run --no-sync python -m pytest -c packages/code-intel/pyproject.toml --confcutdir=packages/code-intel/tests packages/code-intel/tests/unit packages/code-intel/tests/integration -p eval.quality.no_agent -q
```

Run the complete package suite with `packages/code-intel/tests` instead. The
`no_agent` guard requires a clean environment without the retired `attocode`
distribution and rejects agent imports. Existing developer environments may still
contain that editable distribution; create a new environment with
`UV_PROJECT_ENVIRONMENT=/tmp/intelligence-dev uv sync --locked --package attocode-code-intel --extra dev --extra service`
and use the same environment variable on subsequent `uv run` commands. Do not
remove shared environments or caches to make a check pass.

PostgreSQL checks use `TEST_DATABASE_URL`; CI runs the real database, migrations,
locking and branch-isolation controls on both Python versions. The dashboard and
Docker image have separate CI checks. Real Python/TypeScript/Go/Rust language
servers and clean macOS/Linux wheels also gate delivery.

Optional embeddings, model-backed evaluations and broad corpus acquisition must
be explicit. Default development setup does not install model extras. The quality
runner uses deadlines, managed storage and scratch cleanup; follow
[the quality guide](https://github.com/eren23/attocode/blob/main/docs/intelligence-quality.md) before broad or cloud runs.

Use fresh source judgments for ranking changes, retain failed results and report
unsupported/limited evidence honestly. No agent-outcome or performance claim is
established by a passing unit suite. Run `scripts/check_pack_licenses.py` when
changing rule packs. Generate the tool catalog with
`packages/code-intel/scripts/generate_catalog.py` after tool changes.

Docs: `uv sync --locked --package attocode-code-intel --extra docs`, then
`uv run --no-sync mkdocs build --strict`. Published intelligence releases use
`intel-v*` tags and the standalone release workflow.
The retired agent and its development instructions are linked in
[the archive notes](https://github.com/eren23/attocode/blob/main/docs/legacy-agent.md).
