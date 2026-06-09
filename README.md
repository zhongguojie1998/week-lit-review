# Weekly Genomics Literature Review — Claude Code Plugin

Automated pipeline that searches bioRxiv and top genomics journals, downloads full PDFs, and has Claude Code read them and produce critical reviewer-quality assessments with fine-grained scoring.

**No API key needed** — works entirely within Claude Code. The Python script only handles search and PDF download; Claude Code itself reads the PDFs and writes reviews.

## Installation

First, install Claude Code in terminal using the following command (for details, refer to https://code.claude.com/docs/en/setup#installation)

```
curl -fsSL https://claude.ai/install.sh | bash
```

Next, start an interactive session of Claude Code

```
claude
```

For the step `Select login method`, Select `Claude account with subscription`, then it will automatically ask for account credentials and jump to the browser.

Finally, install directly from Claude Code's interactive session:

```
/plugin marketplace add zhongguojie1998/weekly-lit-review
/plugin install weekly-lit-review
```

## Usage

Once installed, trigger the pipeline in any Claude Code session:

**Note**: It will consume tokens at the speed depending on the model you select. I recommend using `/model haiku` command first to set it to the lightest model before running the command.

```
/weekly-lit-review:weekly-lit-review --days 7
/weekly-lit-review:weekly-lit-review --max-papers 10
/weekly-lit-review:weekly-lit-review --days 3 --no-pdf
```

Results are saved to `~/Desktop/Claude/week-lit-review-results/`.

### Daily interactive mode + 12pm reminder

The interactive mode is human-in-the-loop: it fetches **titles/abstracts only**, shows a
numbered list of candidates, you pick which ones matter, and only the **selected** papers get
full-text download + deep review.

```
/weekly-lit-review:weekly-lit-review --interactive
```

Flow: query titles/abstracts → reply with your picks (`1-5, 9` / `all` / bare DOIs) → deep
review of just those → summary.

**Daily 12:00pm reminder (macOS `launchd`).** A local agent fires every day at noon, pre-fetches
today's candidate list (metadata only), and posts a notification so the list is ready when you
sit down. Install once:

```bash
cp assets/com.zhongguojie.weekly-lit-review.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.zhongguojie.weekly-lit-review.plist 2>/dev/null
launchctl load  ~/Library/LaunchAgents/com.zhongguojie.weekly-lit-review.plist
```

- **Force-run now:** `launchctl start com.zhongguojie.weekly-lit-review`
- **Check status:** `launchctl list | grep weekly-lit-review`
- **Stop/uninstall:** `launchctl unload ~/Library/LaunchAgents/com.zhongguojie.weekly-lit-review.plist`
- **Logs:** `~/Desktop/Claude/week-lit-review-results/launchd.{out,err}.log` and the dated
  `prefetch_*.log`.

> The plist and `scripts/daily_prefetch.sh` hardcode the repo path
> `/Users/guojiezhong/Desktop.personal/Claude/week-lit-review`. Edit both if you move the repo.

### macOS app (menu bar + window)

A native front-end (`app/`) wraps the interactive flow so you don't touch the terminal: a
**control-panel window** (Fetch candidates / Select & review / Open summary / engine picker) plus a
resident **📚 menu-bar** app that owns the daily 12:00 auto-fetch. Candidates persist in
`candidates/` and are reused across launches; selecting papers deep-reviews only the new ones and
builds a combined summary over everything selected.

Build and install the double-clickable app (then it auto-starts at login):

```bash
bash app/build_app.sh --install      # creates LitReview.app, copies to /Applications, adds a Login Item
open -a LitReview                     # launch now
```

See **`app/README.md`** for details (engine selection, dev/debug run via `app/run_app.sh`, limitations).

### Non-interactive (from terminal, experimental)

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
│  Read Config │────▶│ Search Papers│────▶│Download Full │────▶│Claude Reads  │────▶│ Write Report │
│  (YAML)      │     │ bioRxiv+RSS  │     │ Text (cascade)│    │ & Review     │     │ (HTML+JSON)  │
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

### Step 3: Download Full Text (fallback cascade)
Each paper runs through a cascade until full text is obtained:
- **bioRxiv/medRxiv** are fronted by a **Cloudflare challenge** that blocks plain HTTP — `curl`,
  `wget`, `requests`, and `paperscraper` all get a 403 challenge page, never the PDF. So the PDF is
  fetched with a real **headless browser** (Playwright + the system Chrome) that clears the
  challenge (detected via the `cf_clearance` cookie, with a retry for transient challenges).
- **Other / journal papers**: direct PDF URL → paperscraper → Semantic Scholar → **Unpaywall**
  (free/legal open-access copies) → Europe PMC (PDF + JATS XML) → CORE.
- **Last resort**: abstract-only (bioRxiv API metadata). The review is then flagged
  `review_basis: abstract` so it's explicit the full text wasn't read.

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
- Each paper review is written to the shared `reviews/` archive as **both** `{stem}.html` (styled)
  and `{stem}.json` (the structured record), via `scripts/render_review.py`.
- The per-run `summary.html` is built **in pure Python** (`scripts/render_summary.py`) from those
  JSON sidecars — **no extra LLM tokens** for the summary. It ranks all reviewed papers by overall
  score and links to each review in `reviews/`.
- Already-reviewed papers are detected by **DOI** (read from the sidecars), so re-selecting a paper
  reuses its stored review instead of re-reviewing — and the summary still lists it alongside any
  newly reviewed papers.

### Features to add
- Let the model read abstract and discussion first, do an initial score of the paper. Then proceed to comprehensive review if it passed certain criteria. 

## Prerequisites

1. **Python 3.10+** installed
2. **Internet access** (for bioRxiv API, RSS feeds, PDF downloads)
3. Dependencies auto-install on first run: `requests`, `feedparser`, `pyyaml`, `playwright`
4. **Google Chrome** installed — required to clear the bioRxiv Cloudflare challenge and fetch
   those PDFs (Playwright drives the system Chrome via `channel="chrome"`)

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
  source/                                            # Shared — downloaded full-text files (pdf/xml/json/txt)
  reviews/                                           # Shared — per-paper reviews: {stem}.html + {stem}.json
    biorxiv-zhang-2026-02-10-gwas-snp.html           #   styled review
    biorxiv-zhang-2026-02-10-gwas-snp.json           #   structured record (drives the summary)
  candidates/                                        # Persistent candidate list, reused across launches/days
    manifest.json
  2026-02-14/                                        # Per-run output
    manifest.json                                    # Papers fetched/reviewed this run
    _index.json                                      # Stems reviewed this run (input to render_summary.py)
    summary.html                                     # Ranked summary; links to ../reviews/*.html
    run_2026-02-14_150000.log                        # Run log
```

## File Structure

```
weekly-lit-review/
  .claude-plugin/
    plugin.json                     # Plugin manifest
    marketplace.json                # Marketplace registry
  skills/
    weekly-lit-review/
      SKILL.md                      # Skill router (modes + output conventions)
      references/                   # Per-mode instructions (doi, batch, interactive, gmail) + review-and-score
  assets/
    config.yaml                     # Template configuration
  scripts/
    fetch_papers.py                 # Paper search & full-text download cascade (browser-based bioRxiv fetch)
    render_review.py                # Review JSON -> reviews/{stem}.html + {stem}.json
    render_summary.py               # Builds {date}/summary.html from review JSON sidecars (pure Python)
    backfill_review_json.py         # Back-fills JSON sidecars for older HTML-only reviews
    run_review.sh                   # Non-interactive bash wrapper
  app/                              # macOS menu-bar + window app (see app/README.md)
```
