#!/bin/bash
# =============================================================================
# eval-golden.sh - Run golden dataset evaluation
# =============================================================================
#
# Usage:
#   ./scripts/eval-golden.sh                        # Full golden dataset, local
#   ./scripts/eval-golden.sh --quick                # 3 quick tasks only
#   ./scripts/eval-golden.sh --docker               # Full golden dataset in Docker
#   ./scripts/eval-golden.sh --docker --dashboard   # Docker with dashboard (default)
#   ./scripts/eval-golden.sh --docker --no-dashboard
#   ./scripts/eval-golden.sh --dashboard            # Local run with local dashboard
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."

DOCKER=false
QUICK=false
DASHBOARD=""  # empty = use default per mode
DASHBOARD_PID=""
EXTRA_ARGS=()

# Cleanup: stop local dashboard if we started it
cleanup() {
    if [[ -n "$DASHBOARD_PID" ]]; then
        echo "Stopping local dashboard..."
        kill "$DASHBOARD_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Parse our flags, pass the rest through
while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker)
            DOCKER=true
            shift
            ;;
        --quick)
            QUICK=true
            shift
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

# Build CLI args
ARGS=(run -d golden --parallelism 3 --isolation worktree)

if $QUICK; then
    ARGS+=(--task-ids fix-typo-001,fix-import-001,fix-type-error-001)
fi

# Append any extra args
ARGS+=("${EXTRA_ARGS[@]}")

if $DOCKER; then
    # Pass dashboard flag through to eval-docker.sh
    if [[ "$DASHBOARD" == "true" ]]; then
        ARGS+=(--dashboard)
    elif [[ "$DASHBOARD" == "false" ]]; then
        ARGS+=(--no-dashboard)
    fi
    # Default: eval-docker.sh starts dashboard for run commands

    exec "$SCRIPT_DIR/eval-docker.sh" "${ARGS[@]}"
else
    # Local mode: optionally start dashboard in background
    if [[ "$DASHBOARD" == "true" ]]; then
        echo "Starting local dashboard..."
        cd "$PROJECT_ROOT"
        npm run dashboard &
        DASHBOARD_PID=$!
        sleep 3
        echo "Dashboard running at http://localhost:5173"
        cd "$PROJECT_ROOT"
    fi

    cd "$PROJECT_ROOT"
    exec npx tsx tools/eval/src/cli.ts "${ARGS[@]}"
fi
