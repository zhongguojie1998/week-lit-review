# Mode: Standard Batch Review (default)

Fetch papers from bioRxiv + journal RSS feeds, download sources, review every paper.

## 1. Fetch papers & download sources
Pass through any user arguments (`$ARGUMENTS`):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_papers.py \
  --config ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml \
  --output-dir ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d) \
  $ARGUMENTS \
  2>&1 | tee ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d)/run_$(date +%Y-%m-%d_%H%M%S).log
```

Then read the manifest: `~/Desktop/Claude/week-lit-review-results/{TODAY}/manifest.json`.

### Fallback if the fetch script fails (network/proxy/403)
1. Check for a pre-fetched manifest at the path above; if it has papers, proceed.
2. Otherwise use **WebSearch** with 4–6 queries built from the config's `genomics_keywords`
   (e.g. `"single-cell RNA-seq" new preprint 2026 site:biorxiv.org`), then **WebFetch** each
   landing page for title/abstract/metadata.
3. Build `manifest.json` manually with this per-paper schema and `review_mode: "abstract"`:
   `uid` (12-char md5 of doi or title), `title`, `authors`, `abstract`, `source`, `url`, `doi`,
   `date`, `source_path: ""`, `source_format: ""`, `review_mode: "abstract"`.

## 2. Review every paper
Follow **`references/review-and-score.md`** for each paper, then write the run summary and
report to the user as described there.
