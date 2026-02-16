---
name: weekly-lit-review
description: >
  Run the weekly genomics literature review pipeline. Searches bioRxiv and 15
  journal RSS feeds, downloads PDFs, then Claude reads each PDF and writes
  critical reviews with scores. No API key needed — works entirely within
  Claude Code. Triggers: "literature review", "weekly papers", "journal scan",
  "paper review", "genomics review", "preprint screening", "lit review".
argument-hint: "[--days N] [--max-papers N] [--no-pdf]"
---

# Weekly Genomics Literature Review

You are running a full literature review pipeline. Follow these steps exactly.

## Step 0: Ensure Output Directory Exists

The output directory structure is:

```
~/Desktop/Claude/week-lit-review-results/
├── pdfs/                    # Shared across runs — downloaded PDFs
├── reviews/                 # Shared across runs — individual review markdown files
└── {YYYY-MM-DD}/            # Per-run — manifest, logs, and summary
    ├── manifest.json
    ├── run_*.log
    └── summary.md
```

Create the directories if they don't exist:

```bash
mkdir -p ~/Desktop/Claude/week-lit-review-results/{pdfs,reviews,$(date +%Y-%m-%d)}
```

## Step 1: Check User Profile & Read Configuration

### 1a. Check for user profile

Check if a user profile file exists at `${CLAUDE_PLUGIN_ROOT}/user_profile.yaml`. This file stores the user's email (required for Unpaywall API and bioRxiv PDF downloads).

```
Read: ${CLAUDE_PLUGIN_ROOT}/user_profile.yaml
```

If the file **does not exist**, ask the user for their email address:

> "To download PDFs from bioRxiv and open-access sources, I need an email address for the Unpaywall API. This is only stored locally in the plugin directory. What email would you like to use?"

After the user provides their email, write the profile file:

```yaml
# User profile for weekly-lit-review plugin
# This file is stored locally and never uploaded
email: "user@example.com"
```

Save it to `${CLAUDE_PLUGIN_ROOT}/user_profile.yaml`.

### 1b. Read configuration

Read the config file to understand search parameters:
```
Read: ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml
```

Note the `biorxiv_categories`, `genomics_keywords`, and `journal_feeds` lists.

## Step 2: Fetch Papers & Download PDFs

**Try the fetch script first.** Pass the user's email (from `user_profile.yaml`) and any user arguments ($ARGUMENTS):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_papers.py \
  --config ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml \
  --output-dir ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d) \
  --email "{email from user_profile.yaml}" \
  $ARGUMENTS
```

If the script succeeds, read the manifest:
```
Read: ~/Desktop/Claude/week-lit-review-results/{YYYY-MM-DD}/manifest.json
```

### Fallback: If the fetch script fails (network/proxy errors)

Some environments (e.g., sandboxed sessions, claude cowork) block direct outbound HTTP to
external APIs. If the fetch script fails with proxy, connection, or 403 errors, use this
fallback approach instead:

1. **Check for a pre-fetched manifest** — the user may have run the fetch script locally first:
   ```
   Read: ~/Desktop/Claude/week-lit-review-results/{YYYY-MM-DD}/manifest.json
   ```
   If a manifest exists with papers in it, skip to Step 3.

2. **If no manifest exists, use WebSearch to find recent papers.** Run multiple searches using
   the WebSearch tool with queries like:
   - `"genomics" OR "genome sequencing" site:biorxiv.org {this week/month}`
   - `"single-cell RNA-seq" OR "spatial transcriptomics" new preprint {current year}`
   - `"GWAS" OR "population genetics" recent paper {current year}`
   - `"CRISPR screen" OR "functional genomics" new study {current year}`

   Use the `genomics_keywords` from the config to craft 4-6 diverse search queries.

3. **For each paper found via WebSearch**, use the WebFetch tool to retrieve the abstract
   and metadata from the paper's landing page (bioRxiv, Nature, Science, Cell, etc.).

4. **Build the manifest manually.** Write a JSON file at
   `~/Desktop/Claude/week-lit-review-results/{YYYY-MM-DD}/manifest.json` with the same schema:
   ```json
   {
     "date": "YYYY-MM-DD",
     "days_lookback": 7,
     "total_fetched": N,
     "total_genomics": N,
     "total_pdfs": 0,
     "papers": [
       {
         "uid": "12char_hash",
         "title": "...",
         "authors": "...",
         "abstract": "...",
         "source": "bioRxiv / Nature / etc.",
         "url": "https://...",
         "doi": "...",
         "date": "YYYY-MM-DD",
         "pdf_path": "",
         "review_mode": "abstract"
       }
     ]
   }
   ```
   Generate `uid` as the first 12 characters of the MD5 hash of the DOI or title.

Then proceed to Step 3 as normal.

## Step 3: Review Each Paper

For each paper in the manifest, do the following:

### 3a. Check if review already exists

Before reviewing, check if a review file for this paper already exists in `~/Desktop/Claude/week-lit-review-results/reviews/`. Construct the expected filename using the `{journal}-{last_name_of_first_author}-{publication_date}-{topic_keywords}.md` convention from the paper's metadata. If a matching review file exists, **skip this paper** — do not re-review it.

### 3b. Read the paper
- If `pdf_path` is non-empty, read the PDF file using the Read tool (Claude Code can read PDFs natively)
- If `pdf_path` is empty, use the abstract from the manifest

### 3c. Critically review the paper

Act as an **expert genomics reviewer at a top-tier journal** (Nature, Science, Cell level).
Be critical but fair. For each paper, assess:

1. **Novelty**: How original and new is the contribution? (2-4 sentences)
2. **Rigor**: Are experiments well-designed? Are controls appropriate? Statistical approach sound? (2-4 sentences)
3. **Methods**: Are methods appropriate, well-described, reproducible, technically sound? (2-4 sentences)
4. **Main Results**: What are the key findings? Are they well-supported by data? (3-5 sentences)
5. **Limitations**: Key weaknesses, caveats, missing experiments or analyses (2-4 sentences)
6. **Inspiration for the Field**: What new directions does this open? What follow-up studies does it inspire? (2-3 sentences)
7. **Your Own Thoughts**: Broader perspective — connections to other work, implications not discussed by authors, concerns about interpretation (2-4 sentences)

### 3d. Score the paper

Assign four scores on a **0-10 scale with decimal precision** (e.g., 5.1, 6.7, 8.3):

| Dimension | What to evaluate |
|-----------|-----------------|
| **Originality** | How novel is the question, approach, or finding? |
| **Methodology** | Rigor, appropriateness, and reproducibility of methods |
| **Significance** | Impact on the field and broader implications |
| **Overall** | Holistic assessment weighing all dimensions |

**Scoring guide:**
- 9.0-10.0: Exceptional / groundbreaking for the field
- 7.0-8.9: Strong contribution, solid methodology
- 5.0-6.9: Adequate but incremental
- 3.0-4.9: Significant concerns or limited novelty
- 0.0-2.9: Major flaws or not meaningful contribution

If reviewing from abstract only (no PDF available), note this limitation and be appropriately cautious with scores.

### 3e. Write individual review

For each paper, write a Markdown file at `~/Desktop/Claude/week-lit-review-results/reviews/{journal}-{last_name_of_first_author}-{publication_date}-{topic_keywords}.md` with this format:

- `{journal}`: Source journal/preprint server name, lowercase with hyphens (e.g., `nature-genetics`, `biorxiv`, `cell`, `science`)
- `{last_name_of_first_author}`: Last name of the first author, lowercase (e.g., `zhang`, `smith`)
- `{publication_date}`: Publication date as `YYYY-MM-DD`
- `{topic_keywords}`: The genomics keywords (from the config's `genomics_keywords` list) that matched the paper's title/abstract, lowercase with hyphens, up to 4 keywords. Use the `matched_keywords` field from the manifest if available. (e.g., `single-cell-rna-seq-spatial-transcriptomics`, `gwas-population-genetics`, `crispr-screen-functional-genomics`)

Example filename: `nature-genetics-zhang-2026-02-10-gwas-population-genetics-snp.md`

```markdown
# Review: {title}

| Field | Value |
|-------|-------|
| **Authors** | {authors} |
| **Source** | {source} |
| **Date** | {date} |
| **DOI** | {doi} |
| **URL** | {url} |
| **Review basis** | Full PDF / Abstract only |

---

## Scores

| Dimension | Score |
|-----------|-------|
| **Originality** | X.X / 10 |
| **Methodology** | X.X / 10 |
| **Significance** | X.X / 10 |
| **Overall** | **X.X / 10** |

---

## Novelty
{your assessment}

## Rigor
{your assessment}

## Methods
{your assessment}

## Main Results
{your assessment}

## Limitations
{your assessment}

## Inspiration for the Field
{your assessment}

## Reviewer's Additional Thoughts
{your additional perspective}
```

## Step 4: Write Summary Report

After reviewing all papers, write a summary at `~/Desktop/Claude/week-lit-review-results/{YYYY-MM-DD}/summary.md`:

- Sort papers by overall score (highest first)
- Include summary statistics (total papers, avg scores, how many from PDF vs abstract)
- For each paper: title (linked), source, date, all four scores in a table, and a 1-2 sentence summary of main results

## Step 5: Report to User

Tell the user:
- How many papers were reviewed
- How many from PDF vs abstract
- The top 3-5 highest-scored papers with their titles and overall scores
- Where the individual reviews are: `~/Desktop/Claude/week-lit-review-results/reviews/`
- Where the summary is: `~/Desktop/Claude/week-lit-review-results/{YYYY-MM-DD}/summary.md`
