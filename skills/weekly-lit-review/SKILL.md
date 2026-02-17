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
    └── summary.html
```

Create the directories if they don't exist:

```bash
mkdir -p ~/Desktop/Claude/week-lit-review-results/{pdfs,reviews,$(date +%Y-%m-%d)}
```

## Step 1: Read Configuration

Read the config file to understand search parameters:
```
Read: ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml
```

Note the `biorxiv_categories`, `genomics_keywords`, and `journal_feeds` lists.

## Step 2: Fetch Papers & Download PDFs

**Try the fetch script first.** Pass through any user arguments ($ARGUMENTS):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_papers.py \
  --config ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml \
  --output-dir ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d) \
  $ARGUMENTS \
  2>&1 | tee ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d)/run_$(date +%Y-%m-%d_%H%M%S).log
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

Before reviewing, check if a review file for this paper already exists in `~/Desktop/Claude/week-lit-review-results/reviews/`. Construct the expected filename using the `{journal}-{last_name_of_first_author}-{publication_date}-{topic_keywords}.html` convention from the paper's metadata. If a matching review file exists, **skip this paper** — do not re-review it.

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

For each paper, write an HTML file at `~/Desktop/Claude/week-lit-review-results/reviews/{journal}-{last_name_of_first_author}-{publication_date}-{topic_keywords}.html` with this format:

- `{journal}`: Source journal/preprint server name, lowercase with hyphens (e.g., `nature-genetics`, `biorxiv`, `cell`, `science`)
- `{last_name_of_first_author}`: Last name of the first author, lowercase (e.g., `zhang`, `smith`)
- `{publication_date}`: Publication date as `YYYY-MM-DD`
- `{topic_keywords}`: The genomics keywords (from the config's `genomics_keywords` list) that matched the paper's title/abstract, lowercase with hyphens, up to 4 keywords. Use the `matched_keywords` field from the manifest if available. (e.g., `single-cell-rna-seq-spatial-transcriptomics`, `gwas-population-genetics`, `crispr-screen-functional-genomics`)

Example filename: `nature-genetics-zhang-2026-02-10-gwas-population-genetics-snp.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Review: {title}</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 40px auto;
            padding: 0 20px;
            color: #333;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        h1 {
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 30px;
        }
        h2 {
            color: #34495e;
            margin-top: 30px;
            border-left: 4px solid #3498db;
            padding-left: 15px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background-color: #3498db;
            color: white;
            font-weight: 600;
        }
        tr:hover {
            background-color: #f5f5f5;
        }
        .score-overall {
            font-size: 1.2em;
            font-weight: bold;
            color: #e74c3c;
        }
        .metadata {
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
        }
        .metadata a {
            color: #3498db;
            text-decoration: none;
        }
        .metadata a:hover {
            text-decoration: underline;
        }
        .section {
            margin: 25px 0;
        }
        .review-basis {
            display: inline-block;
            padding: 5px 12px;
            background: #2ecc71;
            color: white;
            border-radius: 4px;
            font-size: 0.9em;
        }
        .review-basis.abstract-only {
            background: #e67e22;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>

        <div class="metadata">
            <table>
                <tr>
                    <th>Authors</th>
                    <td>{authors}</td>
                </tr>
                <tr>
                    <th>Source</th>
                    <td>{source}</td>
                </tr>
                <tr>
                    <th>Date</th>
                    <td>{date}</td>
                </tr>
                <tr>
                    <th>DOI</th>
                    <td><a href="https://doi.org/{doi}" target="_blank">{doi}</a></td>
                </tr>
                <tr>
                    <th>URL</th>
                    <td><a href="{url}" target="_blank">{url}</a></td>
                </tr>
                <tr>
                    <th>Review Basis</th>
                    <td><span class="review-basis">Full PDF</span></td> <!-- or class="review-basis abstract-only">Abstract Only</span> -->
                </tr>
            </table>
        </div>

        <h2>Scores</h2>
        <table>
            <thead>
                <tr>
                    <th>Dimension</th>
                    <th>Score</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Originality</td>
                    <td>X.X / 10</td>
                </tr>
                <tr>
                    <td>Methodology</td>
                    <td>X.X / 10</td>
                </tr>
                <tr>
                    <td>Significance</td>
                    <td>X.X / 10</td>
                </tr>
                <tr>
                    <td><strong>Overall</strong></td>
                    <td class="score-overall">X.X / 10</td>
                </tr>
            </tbody>
        </table>

        <div class="section">
            <h2>Novelty</h2>
            <p>{your assessment}</p>
        </div>

        <div class="section">
            <h2>Rigor</h2>
            <p>{your assessment}</p>
        </div>

        <div class="section">
            <h2>Methods</h2>
            <p>{your assessment}</p>
        </div>

        <div class="section">
            <h2>Main Results</h2>
            <p>{your assessment}</p>
        </div>

        <div class="section">
            <h2>Limitations</h2>
            <p>{your assessment}</p>
        </div>

        <div class="section">
            <h2>Inspiration for the Field</h2>
            <p>{your assessment}</p>
        </div>

        <div class="section">
            <h2>Reviewer's Additional Thoughts</h2>
            <p>{your additional perspective}</p>
        </div>
    </div>
</body>
</html>
```

## Step 4: Write Summary Report

After reviewing all papers, write a summary at `~/Desktop/Claude/week-lit-review-results/{YYYY-MM-DD}/summary.html`:

- Sort papers by overall score (highest first)
- Include summary statistics (total papers, avg scores, how many from PDF vs abstract)
- For each paper: title (linked to individual review HTML), source, date, all four scores in a table, and a 1-2 sentence summary of main results
- Use a similar HTML template with proper styling for readability

## Step 5: Report to User

Tell the user:
- How many papers were reviewed
- How many from PDF vs abstract
- The top 3-5 highest-scored papers with their titles and overall scores
- Where the individual reviews are: `~/Desktop/Claude/week-lit-review-results/reviews/` (HTML files)
- Where the summary is: `~/Desktop/Claude/week-lit-review-results/{YYYY-MM-DD}/summary.html`
