#!/bin/bash
# =============================================================================
# eval-grade.sh - Grade predictions using official SWE-bench harness
# =============================================================================
#
# Usage:
#   ./scripts/eval-grade.sh <predictions.jsonl>
#   ./scripts/eval-grade.sh <predictions.jsonl> --max-workers 8
#   ./scripts/eval-grade.sh <predictions.jsonl> --timeout 3600
#   ./scripts/eval-grade.sh <predictions.jsonl> --run-id my-run
#
# This runs the official SWE-bench harness on a predictions file.
# The harness creates Docker containers per instance with proper conda
# environments — the gold standard for SWE-bench scoring.
#
# Prerequisites:
#   pip install swebench
#   Docker must be running (harness creates per-instance containers)
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -lt 1 || "$1" == "--help" || "$1" == "-h" ]]; then
    echo "Usage: $0 <predictions.jsonl> [options]"
    echo ""
    echo "Options:"
    echo "  --max-workers <n>     Parallel workers (default: 4)"
    echo "  --timeout <seconds>   Timeout per instance (default: 1800)"
    echo "  --run-id <id>         Run ID for output grouping"
    echo "  --output-dir <dir>    Output directory (default: ./swe-bench-results)"
    echo ""
    echo "Examples:"
    echo "  $0 tools/eval/results/predictions-2026-01-01.jsonl"
    echo "  $0 tools/eval/results/predictions-2026-01-01.jsonl --max-workers 8"
    exit 0
fi

PREDICTIONS="$1"
shift

if [[ ! -f "$PREDICTIONS" ]]; then
    echo "Error: Predictions file not found: $PREDICTIONS"
    exit 1
fi

# Check if swebench is installed
if ! python3 -c "import swebench" 2>/dev/null; then
    echo "Error: swebench not installed. Install with:"
    echo "  pip install swebench"
    exit 1
fi

echo "Grading predictions: $PREDICTIONS"
echo "Remaining args: $@"

cd "$PROJECT_ROOT"
exec npx tsx tools/eval/src/cli.ts grade --predictions "$PREDICTIONS" "$@"
