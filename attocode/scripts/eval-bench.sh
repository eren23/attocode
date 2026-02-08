#!/bin/bash
# =============================================================================
# eval-bench.sh - Run SWE-bench evaluation (Docker only)
# =============================================================================
#
# Usage:
#   ./scripts/eval-bench.sh                 # Default: 5 tasks, Docker, with dashboard
#   ./scripts/eval-bench.sh --limit 10      # 10 tasks
#   ./scripts/eval-bench.sh --parallelism 3 # 3 parallel workers
#   ./scripts/eval-bench.sh --instance-ids django__django-10914
#   ./scripts/eval-bench.sh --no-dashboard  # Skip dashboard
#   ./scripts/eval-bench.sh --dashboard     # Explicit dashboard (default)
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LIMIT=""
PARALLELISM=5
INSTANCE_IDS=""
DASHBOARD=true
EXTRA_ARGS=()

# Parse our flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --parallelism)
            PARALLELISM="$2"
            shift 2
            ;;
        --instance-ids)
            INSTANCE_IDS="$2"
            shift 2
            ;;
        --dashboard)
            DASHBOARD=true
            shift
            ;;
        --no-dashboard)
            DASHBOARD=false
            shift
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# Set env vars for SWE-bench
if [[ -n "$LIMIT" ]]; then
    export SWE_BENCH_LIMIT="$LIMIT"
fi

if [[ -n "$INSTANCE_IDS" ]]; then
    export SWE_BENCH_INSTANCE_IDS="$INSTANCE_IDS"
fi

# Always run in Docker (Python deps required)
ARGS=(run -d swe-bench-lite --parallelism "$PARALLELISM" --isolation worktree --trace --cost-limit 50)
ARGS+=("${EXTRA_ARGS[@]}")

# Pass dashboard flag through
if $DASHBOARD; then
    ARGS+=(--dashboard)
else
    ARGS+=(--no-dashboard)
fi

exec "$SCRIPT_DIR/eval-docker.sh" "${ARGS[@]}"
