#!/bin/bash
# Daily 12:00pm pre-fetch for the weekly-lit-review interactive flow.
# Invoked by the launchd agent (assets/com.zhongguojie.weekly-lit-review.plist).
# Builds today's metadata-only candidate manifest (titles/abstracts, no PDFs),
# then posts a native macOS notification so the user can sit down and select
# papers to deep-review via `/weekly-lit-review --interactive`.
set -euo pipefail

# launchd hands us a minimal PATH — restore the dirs we need (python3, uv, etc.).
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"

REPO="/Users/guojiezhong/Desktop.personal/Claude/week-lit-review"
RESULTS="$HOME/Desktop/Claude/week-lit-review-results"
OUT="$RESULTS/$(date +%Y-%m-%d)"
LOG="$OUT/prefetch_$(date +%H%M%S).log"

mkdir -p "$RESULTS/source" "$RESULTS/reviews" "$OUT"

# Metadata-only fetch: writes manifest.json with abstracts, no source downloads.
python3 "$REPO/scripts/fetch_papers.py" \
  --config "$REPO/assets/config.yaml" \
  --output-dir "$OUT" \
  --no-pdf \
  >> "$LOG" 2>&1 || true

# Count genomics-matched candidates for the notification (0 if anything failed).
N=$(python3 - "$OUT/manifest.json" <<'PY' 2>/dev/null || echo 0
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get("total_genomics", 0))
except Exception:
    print(0)
PY
)

if [ "$N" -gt 0 ]; then
  MSG="$N new genomics papers ready. Run /weekly-lit-review --interactive to select & review."
else
  MSG="No new papers fetched (check $LOG). Run /weekly-lit-review --interactive to retry."
fi

osascript -e "display notification \"$MSG\" with title \"Daily Lit Review\" sound name \"Glass\"" || true
