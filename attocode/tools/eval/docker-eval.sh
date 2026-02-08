#!/bin/bash
# =============================================================================
# Deprecated: use ./scripts/eval-docker.sh instead
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Note: docker-eval.sh is deprecated, use ./scripts/eval-docker.sh instead" >&2
exec "$SCRIPT_DIR/../../scripts/eval-docker.sh" "$@"
