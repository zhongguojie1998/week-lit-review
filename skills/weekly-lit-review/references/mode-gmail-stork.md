# Mode: Gmail Stork

Triggered by `--gmail-stork` (optional `--max-emails N`, `--max-papers N`,
`--keywords "kw1,kw2"`, `--no-pdf`). Reviews papers from Google Scholar "Stork" alert emails.

## 1. Run the Stork fetch script
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_stork_papers.py \
  --output-dir ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d) \
  $ARGUMENTS \
  2>&1 | tee ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d)/run_$(date +%Y-%m-%d_%H%M%S).log
```
The script authenticates with Gmail (OAuth at `~/.gmail-mcp/`), finds the most recent Stork
alert email(s), parses each `PMID: … doi: …` entry, fetches PubMed metadata, optionally filters
by `--keywords`, downloads sources, and writes `manifest.json`.

## 2. Review each paper
Read `~/Desktop/Claude/week-lit-review-results/{TODAY}/manifest.json` and follow
**`references/review-and-score.md`** for each paper, then write the summary and report
(mention how many Stork emails were read and PMIDs extracted).
