# Weekly Genomics Literature Review — Deep PDF Review Pipeline

Automated pipeline that searches bioRxiv and top genomics journals, downloads full PDFs, and has Claude Code read them and produce critical reviewer-quality assessments with fine-grained scoring.

**No API key needed** — works entirely within Claude Code. The Python script only handles search and PDF download; Claude Code itself reads the PDFs and writes reviews.

## Pipeline Overview

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Read Config │────▶│ Search Papers│────▶│Download PDFs │────▶│Claude Reads  │────▶│ Write Report │
│  (YAML)      │     │ bioRxiv+RSS  │     │ (full text)  │     │ PDFs & Review│     │  (.md files) │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

## Steps in Detail

### Step 1: Read Configuration
- Loads `config.yaml` (or `config.example.yaml` as fallback)
- Configures search parameters: lookback days, max papers, categories, keywords
- Sets up journal RSS feed list and bioRxiv categories

### Step 2: Search for Papers
- **bioRxiv**: Queries the bioRxiv content API for recent preprints in configured categories (genomics, genetics, bioinformatics)
- **Journal RSS Feeds**: Parses RSS feeds from 15 journals across Nature, Science, and Cell series
- Filters all papers through genomics keyword matching on title + abstract
- Deduplicates by DOI

### Step 3: Download PDFs
- Attempts to download the full PDF for each paper
- bioRxiv: Uses the direct PDF URL pattern (`/content/{doi}v{version}.full.pdf`)
- Journals: Attempts PDF via Unpaywall API (free/legal open-access PDFs) and direct links
- Stores PDFs in `output/pdfs/` directory
- Falls back to abstract-only review if PDF is unavailable

### Step 4: Claude Reads PDFs and Reviews
- Sends each PDF (or abstract if PDF unavailable) to Claude via the Anthropic API
- Claude acts as a **critical reviewer** and assesses each paper on:
  - **Novelty**: How original and new is the contribution?
  - **Rigor**: Are the experiments well-designed and controls appropriate?
  - **Methods**: Are the methods appropriate, well-described, and reproducible?
  - **Main Results**: What are the key findings? Are they well-supported?
  - **Limitations**: What are the weaknesses and caveats?
  - **Inspiration for the Field**: What new directions does this work open?
  - **Claude's Own Thoughts**: Additional perspective and commentary

### Step 5: Score the Manuscript
Each paper is scored on a 0-10 scale (with decimal precision, e.g., 5.1, 6.7):
- **Originality** (0-10): How novel is the question, approach, or finding?
- **Methodology** (0-10): Rigor, appropriateness, and reproducibility of methods
- **Significance** (0-10): Impact on the field and broader implications
- **Overall** (0-10): Holistic assessment weighing all dimensions

Score guide:
- 9.0-10.0: Exceptional / groundbreaking
- 7.0-8.9: Strong contribution
- 5.0-6.9: Adequate but incremental
- 3.0-4.9: Significant concerns
- 0.0-2.9: Major flaws

### Step 6: Generate Report
- Writes a detailed Markdown report per paper in `output/reviews/`
- Writes a summary report ranking all papers by overall score
- Exports machine-readable JSON for downstream analysis

## Usage Instructions

### Prerequisites

1. **Python 3.10+** installed
2. **ANTHROPIC_API_KEY** set in your environment:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   ```
3. **Internet access** (for bioRxiv API, RSS feeds, PDF downloads)
4. Dependencies auto-install on first run: `requests`, `feedparser`, `anthropic`, `pyyaml`

### Option A: Run directly with Python

```bash
# Full pipeline with defaults (7 days, up to 30 papers, with PDFs)
python3 scripts/lit_review.py --config assets/config.example.yaml

# Customize
python3 scripts/lit_review.py --config assets/config.example.yaml --days 3 --max-papers 10

# Abstract-only mode (faster, no PDF downloads)
python3 scripts/lit_review.py --config assets/config.example.yaml --no-pdf

# Use a different Claude model
python3 scripts/lit_review.py --config assets/config.example.yaml --model claude-opus-4-20250514
```

### Option B: Run with the shell wrapper

```bash
bash scripts/run_review.sh                         # defaults
bash scripts/run_review.sh --days 3                # last 3 days
bash scripts/run_review.sh --max-papers 5          # fewer papers
bash scripts/run_review.sh --no-pdf                # abstract only
```

### Option C: Run non-interactively via Claude Code CLI

This uses `claude -p` to execute the pipeline in a single terminal command with no interactive session:

```bash
# Simple invocation
bash scripts/claude_review.sh

# With options
bash scripts/claude_review.sh --days 3 --max-papers 5

# Use Opus for the Claude Code orchestration layer
REVIEW_MODEL=opus bash scripts/claude_review.sh

# Or call claude -p directly (adjust path to your install location):
CLAUDECODE= claude -p "Run: python3 scripts/lit_review.py --config assets/config.example.yaml --days 7 --max-papers 10. Then read and display the summary report from the output directory." --model sonnet --allowedTools "Bash(run_review:*),Read"
```

### Configuration

Copy `config.example.yaml` to `config.yaml` and customize:

```bash
cp config.example.yaml config.yaml
```

Key settings:
- **days_lookback**: How many days back to search (default: 7)
- **max_papers_to_evaluate**: Controls cost — each paper costs ~$0.01-0.10 depending on model and PDF size
- **claude_model**: `claude-sonnet-4-5-20250929` (fast/cheap) or `claude-opus-4-20250514` (best quality)
- **biorxiv_categories**: Which bioRxiv categories to search
- **genomics_keywords**: Keywords for filtering journal papers
- **journal_feeds**: RSS feed URLs for journals to monitor

### Output

After a run, you'll find in `output/`:

```
output/
  summary_2026-02-14.md          # Ranked summary of all papers
  reviews_2026-02-14.json        # Machine-readable JSON
  reviews/
    a1b2c3_Paper_Title.md        # Individual detailed review per paper
  pdfs/
    a1b2c3_Paper_Title.pdf       # Downloaded PDFs
```

### Cost Estimate

| Model | Per paper (abstract) | Per paper (PDF) | 30 papers |
|-------|---------------------|-----------------|-----------|
| Sonnet | ~$0.01 | ~$0.05-0.15 | ~$1-4 |
| Opus | ~$0.05 | ~$0.20-0.60 | ~$5-15 |

### Scoring Dimensions

Each paper receives four scores on a 0-10 scale with decimal precision:

| Dimension | What it measures |
|-----------|-----------------|
| **Originality** | Novelty of the question, approach, or finding |
| **Methodology** | Rigor, appropriateness, reproducibility of methods |
| **Significance** | Impact on the field and broader implications |
| **Overall** | Holistic assessment weighing all dimensions |

### Review Sections

Each individual review contains:

| Section | Description |
|---------|-------------|
| **Novelty** | How original and new is the contribution? |
| **Rigor** | Experimental design, controls, statistical approach |
| **Methods** | Appropriateness, reproducibility, technical soundness |
| **Main Results** | Key findings and whether they are well-supported |
| **Limitations** | Weaknesses, caveats, missing experiments |
| **Inspiration** | New directions this work opens for the field |
| **Reviewer's Thoughts** | Claude's broader perspective and additional commentary |

## File Structure

```
weekly-lit-review/
  SKILL.md                              # This documentation
  assets/
    config.example.yaml                 # Template configuration
  scripts/
    lit_review.py                       # Main pipeline script
    run_review.sh                       # Direct shell wrapper
    claude_review.sh                    # Non-interactive claude -p wrapper
  output/                               # Generated after first run
    pdfs/
    reviews/
```
