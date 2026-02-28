#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Attocode Python Setup ==="
echo "Project: $PROJECT_DIR"
echo ""

# 1. Check for uv
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv is not installed."
    echo ""
    echo "Install uv first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  # or: brew install uv"
    echo ""
    echo "Then re-run this script."
    exit 1
fi

cd "$PROJECT_DIR"

# 2. Dev install (creates .venv, installs everything)
echo "[1/3] Installing attocode with all extras via uv..."
uv sync --all-extras

# 3. Global install (attocode, attocodepy, attoswarm on PATH)
echo "[2/3] Installing global commands via uv tool..."
uv tool install --force . --with anthropic --with openai

# 4. Verify
echo "[3/3] Verifying install..."
if command -v attocode &>/dev/null; then
    VERSION=$(attocode --version 2>/dev/null || echo "unknown")
    echo "  attocode $VERSION"
    echo "  Commands available: attocode, attocodepy, attoswarm"
else
    echo "  WARNING: attocode not found on PATH"
    echo "  You may need to add ~/.local/bin to your PATH"
fi

echo ""
echo "=== Done ==="
echo "Run from anywhere:"
echo "  attocode              # interactive TUI"
echo "  attocode \"prompt\"     # single-turn"
echo "  attoswarm run ...     # swarm orchestration"
