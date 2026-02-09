#!/bin/bash
# =============================================================================
# eval-compare.sh - Compare two evaluation runs
# =============================================================================
#
# Usage:
#   ./scripts/eval-compare.sh tools/eval/results/run-a.json tools/eval/results/run-b.json
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <baseline.json> <challenger.json>"
    exit 1
fi

cd "$PROJECT_ROOT"
exec npx tsx tools/eval/src/cli.ts compare "$1" "$2"
