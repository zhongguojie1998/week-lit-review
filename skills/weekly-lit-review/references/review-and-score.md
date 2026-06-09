# Review & Score (shared by all modes)

This is the common procedure for reviewing one paper and for writing the run summary.
All modes link here. The HTML is produced by render scripts — **never write HTML by hand**;
emit compact JSON and let the scripts render it (saves tokens and keeps styling consistent).

## Per-paper procedure

For each paper in the manifest:

### 1. Skip if already reviewed
Construct the expected filename (see **Filename convention** below) and check
`~/Desktop/Claude/week-lit-review-results/reviews/{filename}.html`. If it exists, skip this
paper (unless the user explicitly asked to overwrite).

### 2. Read the paper
- `source_path` non-empty and `review_mode` is `"pdf"` → read the PDF with the Read tool.
- `review_mode` is `"text"` → read the file (`.json` = bioRxiv/Europe PMC metadata, `.xml` =
  JATS/OAI, `.txt` = stripped HTML).
- `source_path` empty (`review_mode` `"abstract"`) → use the abstract from the manifest.

### 3. Critically review
Act as an **expert genomics reviewer at a top-tier journal** (Nature/Science/Cell). Be critical
but fair. Write each section as prose (no HTML):
1. **Novelty** — originality of the contribution (2–4 sentences)
2. **Rigor** — design, controls, statistics (2–4 sentences)
3. **Methods** — appropriateness, reproducibility, technical soundness (2–4 sentences)
4. **Main Results** — key findings and how well-supported (3–5 sentences)
5. **Limitations** — weaknesses, caveats, missing experiments (2–4 sentences)
6. **Inspiration for the Field** — new directions, follow-ups (2–3 sentences)
7. **Reviewer's Additional Thoughts** — connections, implications, interpretation concerns (2–4)

### 4. Score (0–10, one decimal)
`originality`, `methodology`, `significance`, `overall`.
- 9.0–10.0 exceptional/groundbreaking · 7.0–8.9 strong, solid · 5.0–6.9 adequate/incremental
- 3.0–4.9 significant concerns/limited novelty · 0.0–2.9 major flaws
If reviewing from abstract only, say so and be appropriately cautious.

### 5. Write the review via the render script (no hand-written HTML)
Write a JSON file (e.g. to `~/Desktop/Claude/week-lit-review-results/{TODAY}/_review.json`) then render:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/render_review.py \
  ~/Desktop/Claude/week-lit-review-results/{TODAY}/_review.json
```
This writes `{stem}.html` **and** `{stem}.json` into the shared
`~/Desktop/Claude/week-lit-review-results/reviews/` dir, and records `{stem}` in
`{TODAY}/_index.json`. The persisted JSON is what builds the run summary later — no separate
summary JSON is hand-written.

JSON schema:
```json
{
  "title": "...", "authors": "...", "source": "...", "date": "YYYY-MM-DD",
  "doi": "...", "url": "...",
  "review_basis": "pdf | text | abstract",
  "matched_keywords": ["single-cell", "rna-seq"],
  "summary": "1–2 sentence main result (used as the summary-card blurb)",
  "scores": {"originality": 8.5, "methodology": 8.0, "significance": 8.5, "overall": 8.3},
  "sections": {
    "novelty": "...", "rigor": "...", "methods": "...", "main_results": "...",
    "limitations": "...", "inspiration": "...", "additional_thoughts": "..."
  }
}
```
The script derives the filename from `source` + first author + `date` + `matched_keywords`
(or pass an explicit `"filename"`). It prints the written path. Set `review_basis` to match how
you read the paper (`pdf`/`text`/`abstract`). The optional `summary` is the card blurb; if
omitted, the summary falls back to a trimmed Main Results.

### Filename convention
`{journal}-{first_author_lastname}-{publication_date}-{topic_keywords}.html`, all lowercase,
hyphenated; up to 4 keywords from `matched_keywords`.
Example: `nature-genetics-zhang-2026-02-10-gwas-population-genetics-snp.html`.

## Run summary

After all reviews are rendered, build the summary **in pure Python — do not hand-write a
summary JSON** (saves tokens). `render_summary.py` reads `{TODAY}/_index.json` (written by
render_review.py) and the persisted `reviews/{stem}.json` records, then writes `summary.html`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/render_summary.py --date {TODAY}
```

It auto-sorts papers by `scores.overall`, computes the stats, and links each card to
`../reviews/{stem}.html`. Nothing else to do for the summary.

## Report to the user
- How many papers reviewed; how many full-source (pdf/text) vs abstract-only.
- Top 3–5 by overall score (title + overall).
- Reviews (shared archive): `~/Desktop/Claude/week-lit-review-results/reviews/{filename}.html`
- Summary for this run: `~/Desktop/Claude/week-lit-review-results/{TODAY}/summary.html`
