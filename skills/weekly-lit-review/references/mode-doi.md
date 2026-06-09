# Mode: DOI-Specific Review

Triggered by one or more `--doi` flags. Fetch and review only those DOIs.

## 1. Fetch the DOIs (downloads full text via the cascade)
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_papers.py \
  --config ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml \
  --output-dir ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d) \
  --doi {doi1} --doi {doi2} ... \
  2>&1 | tee ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d)/run_$(date +%Y-%m-%d_%H%M%S).log
```
This fetches metadata (Semantic Scholar), downloads the source via the full cascade (bioRxiv
PDFs come via a headless browser that clears Cloudflare), and writes `manifest.json` in DOI mode.

## 2. Review each paper
Read `~/Desktop/Claude/week-lit-review-results/{TODAY}/manifest.json` and follow
**`references/review-and-score.md`** for each paper, then write the summary and report.

**Do not check for already-reviewed papers here** — the caller has already filtered those out
in Python (`app/actions.py:partition_reviewed`), so every DOI in the manifest is meant to be
reviewed. Skip review-and-score.md's "Skip if already reviewed" step and review them all.

This runs **headless** via `claude -p`, so **never pause to ask** the user anything — just
review every paper and finish.

For a selected paper with **no DOI** (rare here), fall back to `WebFetch` of its `url`, else
review from the abstract and set `review_basis: "abstract"`.
