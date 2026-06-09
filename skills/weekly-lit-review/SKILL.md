---
name: weekly-lit-review
description: >
  Run the genomics literature review pipeline. Searches bioRxiv and 15 journal
  RSS feeds, downloads PDFs, then Claude reads each PDF and writes critical
  reviews with scores. Supports an interactive daily mode (--interactive): query
  titles/abstracts, pick papers from a selectable list, then deep-review only the
  chosen ones. No API key needed — works entirely within Claude Code. Triggers:
  "literature review", "weekly papers", "journal scan", "paper review", "genomics
  review", "preprint screening", "lit review", "daily papers".
argument-hint: "[--interactive] [--days N] [--max-papers N] [--no-pdf] [--doi DOI [--doi DOI ...]]"
---

# Weekly Genomics Literature Review

A literature-review pipeline. To keep context small, the detailed steps live in per-mode
reference files — **read only the one that matches the invocation**, plus the shared
review/score procedure.

## Mode Detection

Pick exactly one mode from `$ARGUMENTS`, then read that file and follow it:

| If arguments contain… | Read and follow |
|------------------------|-----------------|
| `--interactive`        | `${CLAUDE_PLUGIN_ROOT}/skills/weekly-lit-review/references/mode-interactive.md` |
| `--gmail-stork`        | `${CLAUDE_PLUGIN_ROOT}/skills/weekly-lit-review/references/mode-gmail-stork.md` |
| one or more `--doi`    | `${CLAUDE_PLUGIN_ROOT}/skills/weekly-lit-review/references/mode-doi.md` |
| otherwise (default)    | `${CLAUDE_PLUGIN_ROOT}/skills/weekly-lit-review/references/mode-batch.md` |

Every mode reuses the shared procedure in
`${CLAUDE_PLUGIN_ROOT}/skills/weekly-lit-review/references/review-and-score.md`
(how to read a paper, the 7 review sections, 0–10 scoring, and how reviews/summary HTML are
produced via the render scripts). Read it when you reach the review step.

## Common setup (all modes)

1. **Ensure directories exist:**
   ```bash
   mkdir -p ~/Desktop/Claude/week-lit-review-results/{source,reviews,$(date +%Y-%m-%d)}
   ```
   Layout: `source/` (shared downloaded files), `reviews/` (shared review HTML + JSON
   archive — the canonical store for dedup), `{YYYY-MM-DD}/` (per-run manifest, logs,
   `_index.json`, and `summary.html`).

2. **Read the config** for search parameters (`biorxiv_categories`, `genomics_keywords`,
   `journal_feeds`, `review_engine`):
   ```
   Read: ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml
   ```

`{TODAY}` below means `$(date +%Y-%m-%d)`.

## Output conventions

- Reviews and summary are written by render scripts (`scripts/render_review.py`,
  `scripts/render_summary.py`) — **do not write HTML by hand.** Per-paper reviews come from
  compact JSON; the summary is built in pure Python from the persisted review JSONs (no
  hand-written summary JSON). Details and schemas are in `references/review-and-score.md`.
- Individual reviews (HTML + JSON): `~/Desktop/Claude/week-lit-review-results/reviews/{filename}.{html,json}`
- Per-run summary: `~/Desktop/Claude/week-lit-review-results/{TODAY}/summary.html`
