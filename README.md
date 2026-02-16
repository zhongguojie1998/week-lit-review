# Weekly Genomics Literature Review — Claude Code Plugin

Automated pipeline that searches bioRxiv and top genomics journals, downloads full PDFs, and has Claude Code read them and produce critical reviewer-quality assessments with fine-grained scoring.

**No API key needed** — works entirely within Claude Code. The Python script only handles search and PDF download; Claude Code itself reads the PDFs and writes reviews.

## Installation

Install directly from Claude Code's interactive session:

```
/plugin marketplace add zhongguojie1998/weekly-lit-review
/plugin install weekly-lit-review
```

## Usage

Once installed, trigger the pipeline in any Claude Code session:

```
/weekly-lit-review:weekly-lit-review --days 7
/weekly-lit-review:weekly-lit-review --max-papers 10
/weekly-lit-review:weekly-lit-review --days 3 --no-pdf
```

Results are saved to `~/Desktop/Claude/week-lit-review-results/`.

### Non-interactive (from terminal)

Run directly from the command line without entering an interactive session:

```bash
# Defaults: 7 days, 80 papers, sonnet model
bash scripts/run_review.sh

# Customize
bash scripts/run_review.sh --days 3 --max-papers 10
bash scripts/run_review.sh --days 7 --model opus
bash scripts/run_review.sh --days 7 --no-pdf
```

## Pipeline Overview

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Read Config │────▶│ Search Papers│────▶│Download PDFs │────▶│Claude Reads  │────▶│ Write Report │
│  (YAML)      │     │ bioRxiv+RSS  │     │ (full text)  │     │ PDFs & Review│     │  (.md files) │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

### Step 1: Read Configuration
- Loads `assets/config.yaml`
- Configures search parameters: lookback days, max papers, categories, keywords
- Sets up journal RSS feed list and bioRxiv categories

### Step 2: Search for Papers
- **bioRxiv**: Queries the bioRxiv content API for recent preprints in configured categories (genomics, genetics, bioinformatics)
- **Journal RSS Feeds**: Parses RSS feeds from 15 journals across Nature, Science, and Cell series
- Filters all papers through genomics keyword matching on title + abstract
- Deduplicates by DOI
- **Fallback**: If network is restricted (e.g., sandboxed environments), uses Claude's built-in WebSearch/WebFetch tools

### Step 3: Download PDFs
- Attempts to download the full PDF for each paper
- bioRxiv: Uses the direct PDF URL pattern (`/content/{doi}v{version}.full.pdf`)
- Journals: Attempts PDF via Unpaywall API (free/legal open-access PDFs) and direct links
- Falls back to abstract-only review if PDF is unavailable

### Step 4: Claude Reads PDFs and Reviews
- Claude reads each PDF (or abstract if PDF unavailable) natively
- Acts as a **critical reviewer** and assesses each paper on:
  - **Novelty**: How original and new is the contribution?
  - **Rigor**: Are the experiments well-designed and controls appropriate?
  - **Methods**: Are the methods appropriate, well-described, and reproducible?
  - **Main Results**: What are the key findings? Are they well-supported?
  - **Limitations**: What are the weaknesses and caveats?
  - **Inspiration for the Field**: What new directions does this work open?
  - **Reviewer's Own Thoughts**: Additional perspective and commentary

### Step 5: Score the Manuscript
Each paper is scored on a 0-10 scale (with decimal precision, e.g., 5.1, 6.7):

| Dimension | What it measures |
|-----------|-----------------|
| **Originality** | Novelty of the question, approach, or finding |
| **Methodology** | Rigor, appropriateness, reproducibility of methods |
| **Significance** | Impact on the field and broader implications |
| **Overall** | Holistic assessment weighing all dimensions |

Score guide:
- 9.0-10.0: Exceptional / groundbreaking
- 7.0-8.9: Strong contribution
- 5.0-6.9: Adequate but incremental
- 3.0-4.9: Significant concerns
- 0.0-2.9: Major flaws

### Step 6: Generate Report
- Writes a detailed Markdown review per paper in `reviews/`
- Writes a summary report ranking all papers by overall score

## Prerequisites

1. **Python 3.10+** installed
2. **Internet access** (for bioRxiv API, RSS feeds, PDF downloads)
3. Dependencies auto-install on first run: `requests`, `feedparser`, `pyyaml`

## Configuration

The default config is in `assets/config.yaml`. Key settings:
- **days_lookback**: How many days back to search (default: 7)
- **max_papers_to_evaluate**: Max papers to review (default: 80)
- **biorxiv_categories**: Which bioRxiv categories to search
- **genomics_keywords**: Keywords for filtering journal papers
- **journal_feeds**: RSS feed URLs for journals to monitor

## Output

After a run, you'll find in `~/Desktop/Claude/week-lit-review-results/`:

```
week-lit-review-results/
  pdfs/                                                        # Shared — downloaded PDFs
    nature-genetics-zhang-2026-02-10-gwas-snp.pdf
  reviews/                                                     # Shared — individual reviews
    nature-genetics-zhang-2026-02-10-gwas-snp.md
  2026-02-14/                                                  # Per-run output
    manifest.json                                              # Fetched paper metadata
    summary.md                                                 # Ranked summary of all papers
    run_2026-02-14_150000.log                                  # Run log
```

## File Structure

```
weekly-lit-review/
  .claude-plugin/
    plugin.json                     # Plugin manifest
    marketplace.json                # Marketplace registry
  skills/
    weekly-lit-review/
      SKILL.md                      # Skill instructions
  assets/
    config.yaml             # Template configuration
  scripts/
    fetch_papers.py                 # Paper search & PDF download script
    run_review.sh                   # Non-interactive bash wrapper
```
