#!/usr/bin/env bash
# Run the weekly literature review non-interactively via Claude Code.
#
# Usage:
#   bash scripts/run_review.sh
#   bash scripts/run_review.sh --days 3
#   bash scripts/run_review.sh --days 7 --max-papers 20
#   bash scripts/run_review.sh --days 7 --model opus
#   bash scripts/run_review.sh --no-pdf

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG="${PLUGIN_DIR}/assets/config.example.yaml"

# Read defaults from config.yaml if it exists, otherwise config.example.yaml
if [[ -f "${PLUGIN_DIR}/config.yaml" ]]; then
    CONFIG="${PLUGIN_DIR}/config.yaml"
fi

# Parse values from YAML config (simple grep+awk, no dependency needed)
read_config() {
    grep "^${1}:" "$CONFIG" 2>/dev/null | awk '{print $2}' | tr -d '"'
}

DAYS="$(read_config days_lookback)"
MAX_PAPERS="$(read_config max_papers_to_evaluate)"
MODEL="$(read_config claude_code_model)"

# Fallback defaults if config parsing returns empty
DAYS="${DAYS:-7}"
MAX_PAPERS="${MAX_PAPERS:-80}"
MODEL="${MODEL:-sonnet}"
EXTRA_ARGS=""

# CLI arguments override config values
while [[ $# -gt 0 ]]; do
    case "$1" in
        --days)
            DAYS="$2"; shift 2 ;;
        --max-papers)
            MAX_PAPERS="$2"; shift 2 ;;
        --model)
            MODEL="$2"; shift 2 ;;
        --no-pdf)
            EXTRA_ARGS="$EXTRA_ARGS --no-pdf"; shift ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--days N] [--max-papers N] [--model MODEL] [--no-pdf]" >&2
            exit 1 ;;
    esac
done

# Build the skill arguments
SKILL_ARGS="--days ${DAYS} --max-papers ${MAX_PAPERS}${EXTRA_ARGS}"

echo "=== Weekly Genomics Literature Review ==="
echo "  Config:     ${CONFIG}"
echo "  Days:       ${DAYS}"
echo "  Max papers: ${MAX_PAPERS}"
echo "  Model:      ${MODEL}"
echo "  Extra args: ${EXTRA_ARGS:-none}"
echo "  Output:     ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d)/"
echo "=========================================="
echo ""

BASE_DIR="$HOME/Desktop/Claude/week-lit-review-results"
OUTPUT_DIR="${BASE_DIR}/$(date +%Y-%m-%d)"
mkdir -p "${OUTPUT_DIR}" "${BASE_DIR}/pdfs" "${BASE_DIR}/reviews"
LOG_FILE="${OUTPUT_DIR}/run_$(date +%Y-%m-%d_%H%M%S).log"

claude -p "/weekly-lit-review:weekly-lit-review ${SKILL_ARGS}" \
    --model "${MODEL}" \
    --plugin-dir "${PLUGIN_DIR}" \
    --allowedTools "Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch" \
    --verbose \
    --output-format text \
    2>&1 | tee "${LOG_FILE}"

echo ""
echo "Log saved to: ${LOG_FILE}"
