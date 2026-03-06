#!/usr/bin/env bash
# basic-task.sh — Run a single non-interactive task with attocode
#
# Usage: bash examples/basic-task.sh
#
# This runs the agent in non-interactive mode (no TUI).
# The agent will complete the task and exit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Default task — override with TASK env var
TASK="${TASK:-"List all TypeScript files in src/ and summarize what each one does in one sentence."}"

echo "=== Attocode: Non-Interactive Task ==="
echo "Task: ${TASK}"
echo ""

npx tsx "${SCRIPT_DIR}/src/main.ts" \
  --task "${TASK}" \
  --max-iterations 10 \
  --no-tui
