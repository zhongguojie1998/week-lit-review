# Mode: Interactive Daily Review

Triggered by `--interactive`. Human-in-the-loop: fetch titles/abstracts only, let the user pick
papers from a list, then deep-review only the selected ones. A 12:00 launchd job usually
pre-fetches today's candidate list.

## Phase A — Candidate list (titles/abstracts only)
1. `mkdir -p ~/Desktop/Claude/week-lit-review-results/{source,reviews,$(date +%Y-%m-%d)}`
2. Check for today's pre-fetched manifest: `~/Desktop/Claude/week-lit-review-results/{TODAY}/manifest.json`.
   - Exists with papers → use it; skip to Phase B.
   - Missing → build it now (metadata only, no downloads):
     ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_papers.py \
       --config ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml \
       --output-dir ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d) \
       --no-pdf $ARGUMENTS \
       2>&1 | tee ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d)/run_$(date +%Y-%m-%d_%H%M%S).log
     ```
3. Optional: if the user wants more, use the local **bioRxiv MCP** tools (`search_preprints`,
   `list_recent_preprints`) and merge hits into the list.

## Phase B — Present a numbered, selectable list
1. Drop papers already reviewed (matching file in `reviews/` per the filename convention).
2. Print a numbered table: `# | Date | Source | 1st author | Corresponding | Affiliation |
   Keywords | Title` (corresponding/affiliation from manifest; show `—` when absent).
3. Ask the user which to deep-review; accept numbers, ranges (`1-5, 9`), `all`, or DOIs.
   **Do not proceed until they choose.**

## Phase C — Deep-review the picks (full text)
Hand the selected DOIs to DOI mode to download full text:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_papers.py \
  --config ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml \
  --output-dir ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d) \
  --doi {doi1} --doi {doi2} ... \
  2>&1 | tee ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d)/run_$(date +%Y-%m-%d_%H%M%S).log
```
Then review each selected paper following **`references/review-and-score.md`**. For a pick with
no DOI, `WebFetch` its `url`, else review from the abstract.

## Phase D — Summary & report
Write the summary and report per **`references/review-and-score.md`**, covering only the
deep-reviewed picks.
