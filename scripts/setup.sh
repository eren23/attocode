#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
command -v uv >/dev/null || { echo "Install uv, then rerun this script." >&2; exit 1; }
uv sync --locked --package attocode-code-intel --extra dev --extra service
uv run --no-sync attocode-code-intel --version
printf '%s\n' 'Intelligence development environment ready. No global installation or model extras were added.'
