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

All output goes to `~/Desktop/Claude/week-lit-review-results/`. Create it if it doesn't exist:

```bash
mkdir -p ~/Desktop/Claude/week-lit-review-results
```

## Step 1: Read Configuration

Read the config file to understand search parameters:
```
Read: ${CLAUDE_PLUGIN_ROOT}/assets/config.example.yaml
```
(If the user has a `config.yaml` at the project root, use that instead.)

Note the `biorxiv_categories`, `genomics_keywords`, and `journal_feeds` lists.

## Step 2: Fetch Papers & Download PDFs

**Try the fetch script first.** Pass through any user arguments ($ARGUMENTS):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_papers.py \
  --config ${CLAUDE_PLUGIN_ROOT}/assets/config.example.yaml \
  --output-dir ~/Desktop/Claude/week-lit-review-results \
  $ARGUMENTS
```

If the script succeeds, read the manifest:
```
Read: ~/Desktop/Claude/week-lit-review-results/manifest.json
```

### Fallback: If the fetch script fails (network/proxy errors)

Some environments (e.g., sandboxed sessions, claude cowork) block direct outbound HTTP to
external APIs. If the fetch script fails with proxy, connection, or 403 errors, use this
fallback approach instead:

1. **Check for a pre-fetched manifest** — the user may have run the fetch script locally first:
   ```
   Read: ~/Desktop/Claude/week-lit-review-results/manifest.json
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
   `~/Desktop/Claude/week-lit-review-results/manifest.json` with the same schema:
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

### 3a. Read the paper
- If `pdf_path` is non-empty, read the PDF file using the Read tool (Claude Code can read PDFs natively)
- If `pdf_path` is empty, use the abstract from the manifest

### 3b. Critically review the paper

Act as an **expert genomics reviewer at a top-tier journal** (Nature, Science, Cell level).
Be critical but fair. For each paper, assess:

1. **Novelty**: How original and new is the contribution? (2-4 sentences)
2. **Rigor**: Are experiments well-designed? Are controls appropriate? Statistical approach sound? (2-4 sentences)
3. **Methods**: Are methods appropriate, well-described, reproducible, technically sound? (2-4 sentences)
4. **Main Results**: What are the key findings? Are they well-supported by data? (3-5 sentences)
5. **Limitations**: Key weaknesses, caveats, missing experiments or analyses (2-4 sentences)
6. **Inspiration for the Field**: What new directions does this open? What follow-up studies does it inspire? (2-3 sentences)
7. **Your Own Thoughts**: Broader perspective — connections to other work, implications not discussed by authors, concerns about interpretation (2-4 sentences)

### 3c. Score the paper

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

### 3d. Write individual review

For each paper, write a Markdown file at `~/Desktop/Claude/week-lit-review-results/reviews/{uid}_{title_slug}.md` with this format:

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

After reviewing all papers, write a summary at `~/Desktop/Claude/week-lit-review-results/summary_{date}.md`:

- Sort papers by overall score (highest first)
- Include summary statistics (total papers, avg scores, how many from PDF vs abstract)
- For each paper: title (linked), source, date, all four scores in a table, and a 1-2 sentence summary of main results

## Step 5: Report to User

Tell the user:
- How many papers were reviewed
- How many from PDF vs abstract
- The top 3-5 highest-scored papers with their titles and overall scores
- Where the full reports are: `~/Desktop/Claude/week-lit-review-results/reviews/` and `~/Desktop/Claude/week-lit-review-results/summary_{date}.md`
