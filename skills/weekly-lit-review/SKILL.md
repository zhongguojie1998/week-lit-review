---
name: weekly-lit-review
description: >
  Run the weekly genomics literature review pipeline. Searches bioRxiv and 15
  journal RSS feeds, downloads PDFs, then Claude reads each PDF and writes
  critical reviews with scores. No API key needed — works entirely within
  Claude Code. Triggers: "literature review", "weekly papers", "journal scan",
  "paper review", "genomics review", "preprint screening", "lit review".
argument-hint: "[--days N] [--max-papers N] [--no-pdf] [--doi DOI]"
---

# Weekly Genomics Literature Review

You are running a full literature review pipeline. Follow these steps exactly.

## Mode Detection: Single DOI vs Batch Review

Check if the user provided a DOI in the arguments (e.g., `--doi 10.1101/2024.05.20.594981` or just the DOI string).

**If a DOI is provided:** Skip to **Single Paper Review Mode** (see section at the end).

**Otherwise:** Continue with the standard batch review pipeline below.

---

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
- For each paper: title (linked to individual review HTML in `../reviews/` directory), source, date, all four scores in a table, and a 1-2 sentence summary of main results

Use this HTML template:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Literature Review Summary - {YYYY-MM-DD}</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
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
        .stats {
            background: #ecf0f1;
            padding: 20px;
            border-radius: 5px;
            margin: 30px 0;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }
        .stat-item {
            text-align: center;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #3498db;
        }
        .stat-label {
            color: #7f8c8d;
            font-size: 0.9em;
        }
        .paper-card {
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            transition: box-shadow 0.3s;
        }
        .paper-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        .paper-title {
            font-size: 1.3em;
            margin-bottom: 10px;
        }
        .paper-title a {
            color: #2c3e50;
            text-decoration: none;
            font-weight: 600;
        }
        .paper-title a:hover {
            color: #3498db;
        }
        .paper-meta {
            color: #7f8c8d;
            font-size: 0.9em;
            margin: 10px 0;
        }
        .scores {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin: 15px 0;
        }
        .score-item {
            text-align: center;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .score-label {
            font-size: 0.8em;
            color: #7f8c8d;
            margin-bottom: 5px;
        }
        .score-value {
            font-size: 1.5em;
            font-weight: bold;
            color: #2c3e50;
        }
        .score-overall {
            background: #3498db;
            color: white;
        }
        .score-overall .score-label {
            color: #ecf0f1;
        }
        .score-overall .score-value {
            color: white;
        }
        .paper-summary {
            margin-top: 15px;
            padding: 15px;
            background: #f8f9fa;
            border-left: 4px solid #3498db;
            font-style: italic;
        }
        .rank {
            display: inline-block;
            width: 40px;
            height: 40px;
            line-height: 40px;
            text-align: center;
            border-radius: 50%;
            background: #3498db;
            color: white;
            font-weight: bold;
            margin-right: 15px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Literature Review Summary - {YYYY-MM-DD}</h1>

        <div class="stats">
            <div class="stat-item">
                <div class="stat-value">{total_papers}</div>
                <div class="stat-label">Total Papers Reviewed</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{pdf_count}</div>
                <div class="stat-label">Full PDF Reviews</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{abstract_count}</div>
                <div class="stat-label">Abstract-Only Reviews</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{avg_score}</div>
                <div class="stat-label">Average Overall Score</div>
            </div>
        </div>

        <!-- Repeat for each paper -->
        <div class="paper-card">
            <div class="paper-title">
                <span class="rank">1</span>
                <a href="../reviews/{filename}.html" target="_blank">{title}</a>
            </div>
            <div class="paper-meta">
                <strong>Source:</strong> {source} | <strong>Date:</strong> {date} | <strong>Authors:</strong> {authors}
            </div>
            <div class="scores">
                <div class="score-item">
                    <div class="score-label">Originality</div>
                    <div class="score-value">X.X</div>
                </div>
                <div class="score-item">
                    <div class="score-label">Methodology</div>
                    <div class="score-value">X.X</div>
                </div>
                <div class="score-item">
                    <div class="score-label">Significance</div>
                    <div class="score-value">X.X</div>
                </div>
                <div class="score-item score-overall">
                    <div class="score-label">Overall</div>
                    <div class="score-value">X.X</div>
                </div>
            </div>
            <div class="paper-summary">
                {1-2 sentence summary of main results}
            </div>
        </div>
        <!-- End repeat -->

    </div>
</body>
</html>
```

## Step 5: Report to User

Tell the user:
- How many papers were reviewed
- How many from PDF vs abstract
- The top 3-5 highest-scored papers with their titles and overall scores
- Where the individual reviews are: `~/Desktop/Claude/week-lit-review-results/reviews/` (HTML files)
- Where the summary is: `~/Desktop/Claude/week-lit-review-results/{YYYY-MM-DD}/summary.html`

---

## Single Paper Review Mode

When the user provides a single DOI (e.g., `--doi 10.1101/2024.05.20.594981` or just the DOI string):

### 1. Create output directories

```bash
mkdir -p ~/Desktop/Claude/week-lit-review-results/{pdfs,reviews}
```

### 2. Fetch paper metadata

Use Semantic Scholar API to get metadata:

```bash
curl -s "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,authors,abstract,year,venue,externalIds,openAccessPdf" | python3 -m json.tool
```

Parse the response to extract:
- Title
- Authors (format: "Last1, First1; Last2, First2")
- Abstract
- Publication date (year)
- DOI
- Source/venue
- OpenAccessPdf URL (if available)

### 3. Download PDF

Try to download the PDF using the fetch script's download cascade:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fetch_papers.py \
  --config ${CLAUDE_PLUGIN_ROOT}/assets/config.yaml \
  --output-dir ~/Desktop/Claude/week-lit-review-results/single-reviews \
  --days 3650 \
  --max-papers 1
```

Or manually construct a paper dict and call the download function directly via a Python snippet that imports from `fetch_papers.py`.

Alternatively, if you have the DOI, construct a temporary manifest with just this one paper and use the standard PDF download logic.

### 4. Extract genomics keywords

Match the paper's title and abstract against the `genomics_keywords` from the config to determine topic keywords for the filename.

### 5. Generate filename

Use the standard naming convention:
`{journal}-{last_name_of_first_author}-{publication_date}-{topic_keywords}.html`

### 6. Check if review exists

Check if `~/Desktop/Claude/week-lit-review-results/reviews/{filename}.html` already exists. If so, inform the user and ask if they want to overwrite.

### 7. Perform review

Follow the same review steps as the batch mode (3b-3e):
- Read the PDF or use abstract
- Critically review
- Score on 0-10 scale
- Write HTML review to `~/Desktop/Claude/week-lit-review-results/reviews/{filename}.html`

### 8. Report to user

Tell the user:
- Paper title and DOI
- Whether review was from PDF or abstract
- Overall score
- Path to the review: `~/Desktop/Claude/week-lit-review-results/reviews/{filename}.html`
