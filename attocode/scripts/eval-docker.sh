#!/bin/bash
# =============================================================================
# eval-docker.sh - Run evaluations in Docker from project root
# =============================================================================
#
# Usage (from project root):
#   ./scripts/eval-docker.sh build
#   ./scripts/eval-docker.sh run -d golden --trace
#   ./scripts/eval-docker.sh run -d golden --trace --dashboard
#   ./scripts/eval-docker.sh run -d golden --trace --no-dashboard
#   ./scripts/eval-docker.sh dashboard
#   ./scripts/eval-docker.sh shell
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."

COMPOSE_CMD="docker compose -f $PROJECT_ROOT/tools/eval/docker-compose.yml --project-directory $PROJECT_ROOT"

DASHBOARD_STARTED=false

# Cleanup on exit: stop dashboard if we started it
cleanup() {
    if [[ "$DASHBOARD_STARTED" == "true" ]]; then
        echo "Stopping dashboard..."
        $COMPOSE_CMD stop dashboard 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Auto-build the Docker image if it doesn't exist
ensure_image() {
    if ! docker image inspect attocode-eval >/dev/null 2>&1; then
        echo "Docker image not found, building..."
        $COMPOSE_CMD build eval
    fi
}

# Check for required environment variables when using specific providers
check_api_keys() {
    local provider=""
    for arg in "$@"; do
        if [[ "$arg" == "--provider" || "$arg" == "-p" ]]; then
            provider="next"
        elif [[ "$provider" == "next" ]]; then
            provider="$arg"
        fi
    done

    # Default provider is openrouter
    if [[ -z "$provider" ]]; then
        provider="openrouter"
    fi

    case "$provider" in
        anthropic)
            if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
                echo "Error: ANTHROPIC_API_KEY is required for Anthropic provider"
                exit 1
            fi
            ;;
        openrouter)
            if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
                echo "Error: OPENROUTER_API_KEY is required for OpenRouter provider"
                exit 1
            fi
            ;;
        openai)
            if [[ -z "${OPENAI_API_KEY:-}" ]]; then
                echo "Error: OPENAI_API_KEY is required for OpenAI provider"
                exit 1
            fi
            ;;
    esac
}

# Start the dashboard in background and wait for it
start_dashboard() {
    ensure_image
    echo "Starting dashboard at http://localhost:3000..."
    $COMPOSE_CMD up -d dashboard
    DASHBOARD_STARTED=true
    sleep 2
    echo "Dashboard running at http://localhost:3000"
}

show_help() {
    echo "Docker Evaluation Runner (run from project root)"
    echo ""
    echo "Commands:"
    echo "  build             Build the Docker image"
    echo "  shell             Open a shell in the container"
    echo "  dashboard         Start the trace dashboard at localhost:3000 (foreground)"
    echo "  *                 Pass through to eval CLI"
    echo ""
    echo "Flags (for run commands):"
    echo "  --build           Force rebuild Docker image before running"
    echo "  --dashboard       Start trace dashboard alongside eval (default for run)"
    echo "  --no-dashboard    Skip starting the dashboard"
    echo ""
    echo "Examples:"
    echo "  ./scripts/eval-docker.sh build"
    echo "  ./scripts/eval-docker.sh run -d golden --trace"
    echo "  ./scripts/eval-docker.sh run -d swe-bench-lite --parallelism 5 --isolation worktree"
    echo "  ./scripts/eval-docker.sh run -d golden --trace --no-dashboard"
    echo "  ./scripts/eval-docker.sh dashboard"
    echo "  ./scripts/eval-docker.sh shell"
}

# Extract --build, --dashboard, --no-dashboard from args, pass the rest through
FORCE_BUILD=false
START_DASHBOARD=""  # empty = use default per command
PASSTHROUGH_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --build)
            FORCE_BUILD=true
            ;;
        --dashboard)
            START_DASHBOARD=true
            ;;
        --no-dashboard)
            START_DASHBOARD=false
            ;;
        *)
            PASSTHROUGH_ARGS+=("$arg")
            ;;
    esac
done

# Re-set positional params to passthrough args
set -- "${PASSTHROUGH_ARGS[@]}"

# Force rebuild if requested
if [[ "$FORCE_BUILD" == "true" ]]; then
    echo "Building Docker image..."
    $COMPOSE_CMD build eval
fi

case "${1:-}" in
    build)
        echo "Building Docker image..."
        $COMPOSE_CMD build eval
        ;;
    shell)
        ensure_image
        echo "Opening shell in container..."
        $COMPOSE_CMD run --rm eval /bin/bash
        ;;
    dashboard)
        ensure_image
        echo "Starting trace dashboard at http://localhost:3000..."
        $COMPOSE_CMD up dashboard
        ;;
    -h|--help|help)
        show_help
        ;;
    *)
        ensure_image

        # Check API keys for run commands
        if [[ "${1:-}" == "run" ]]; then
            check_api_keys "$@"
        fi

        # Default: start dashboard for run commands
        if [[ -z "$START_DASHBOARD" && "${1:-}" == "run" ]]; then
            START_DASHBOARD=true
        fi

        if [[ "$START_DASHBOARD" == "true" ]]; then
            start_dashboard
        fi

        # Pass all arguments to the eval CLI
        $COMPOSE_CMD run --rm eval npm run eval -- "$@"
        ;;
esac
