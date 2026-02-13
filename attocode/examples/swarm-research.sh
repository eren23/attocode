#!/usr/bin/env bash
# swarm-research.sh — Multi-agent swarm research example
#
# Usage: bash examples/swarm-research.sh
#
# Launches attocode in swarm mode with multiple specialist workers.
# Each worker researches a subtopic in parallel, then the orchestrator
# merges findings into a final report.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TOPIC="${TOPIC:-"Compare TypeScript build tools: tsc, esbuild, swc, and tsup"}"

echo "=== Attocode: Swarm Research ==="
echo "Topic: ${TOPIC}"
echo ""

npx tsx "${SCRIPT_DIR}/src/main.ts" \
  --task "${TOPIC}" \
  --swarm auto \
  --max-iterations 30 \
  --trace
