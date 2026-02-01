#!/bin/bash
# =============================================================================
# docker-eval.sh - Run SWE-bench evaluation in Docker
# =============================================================================
#
# This script wraps docker compose to run evaluations in an isolated container.
# All Python/Node dependencies are bundled in the image for reproducibility.
#
# Usage:
#   ./docker-eval.sh run -d swe-bench-lite --provider openrouter -m anthropic/claude-3.5-sonnet:beta
#   ./docker-eval.sh run -d golden --trace
#   ./docker-eval.sh list -d swe-bench-lite
#   ./docker-eval.sh compare results/a.json results/b.json
#
# Environment variables:
#   ANTHROPIC_API_KEY     - Required for Anthropic provider
#   OPENROUTER_API_KEY    - Required for OpenRouter provider
#   OPENAI_API_KEY        - Required for OpenAI provider
#   SWE_BENCH_LIMIT       - Limit number of SWE-bench instances
#   SWE_BENCH_INSTANCE_IDS - Comma-separated list of specific instances
#
# Examples:
#   # Run 5 SWE-bench instances
#   SWE_BENCH_LIMIT=5 ./docker-eval.sh run -d swe-bench-lite --trace
#
#   # Run with cost limit
#   ./docker-eval.sh run -d golden --cost-limit 1.00
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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

    case "$provider" in
        anthropic)
            if [[ -z "$ANTHROPIC_API_KEY" ]]; then
                echo "Error: ANTHROPIC_API_KEY is required for Anthropic provider"
                exit 1
            fi
            ;;
        openrouter)
            if [[ -z "$OPENROUTER_API_KEY" ]]; then
                echo "Error: OPENROUTER_API_KEY is required for OpenRouter provider"
                exit 1
            fi
            ;;
        openai)
            if [[ -z "$OPENAI_API_KEY" ]]; then
                echo "Error: OPENAI_API_KEY is required for OpenAI provider"
                exit 1
            fi
            ;;
    esac
}

# Show help
show_help() {
    echo "Docker Evaluation Runner"
    echo ""
    echo "Commands:"
    echo "  build       Build the Docker image"
    echo "  shell       Open a shell in the container"
    echo "  dashboard   Start the trace dashboard"
    echo "  *           Pass through to eval CLI"
    echo ""
    echo "Examples:"
    echo "  ./docker-eval.sh build"
    echo "  ./docker-eval.sh run -d golden --trace"
    echo "  ./docker-eval.sh run -d swe-bench-lite --provider openrouter -m z-ai/glm-4.7"
    echo "  ./docker-eval.sh dashboard"
    echo "  ./docker-eval.sh shell"
}

case "${1:-}" in
    build)
        echo "Building Docker image..."
        docker compose build eval
        ;;
    shell)
        echo "Opening shell in container..."
        docker compose run --rm eval /bin/bash
        ;;
    dashboard)
        echo "Starting trace dashboard..."
        echo "Dashboard will be available at http://localhost:3000"
        docker compose up dashboard
        ;;
    -h|--help|help)
        show_help
        ;;
    *)
        # Check API keys for run commands
        if [[ "${1:-}" == "run" ]]; then
            check_api_keys "$@"
        fi

        # Pass all arguments to the eval CLI
        docker compose run --rm eval npx tsx tools/eval/src/cli.ts "$@"
        ;;
esac
