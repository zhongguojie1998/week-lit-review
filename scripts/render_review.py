#!/usr/bin/env python3
"""Render a single paper review to HTML from a compact JSON description.

This keeps the (large) HTML/CSS out of the model's context AND output: the agent
emits only the review data as JSON, this script writes the styled HTML.

Usage:
    render_review.py <review.json> [--reviews-dir DIR]

Writes two files into the shared reviews/ dir: `{stem}.html` (styled review) and
`{stem}.json` (the record, used later by render_summary.py to build the run
summary in pure Python). Also appends `{stem}` to `<review.json dir>/_index.json`
so render_summary.py knows which reviews belong to this run.

review.json schema:
{
  "title": str, "authors": str, "source": str, "date": "YYYY-MM-DD",
  "doi": str, "url": str,
  "review_basis": "pdf" | "text" | "abstract",
  "filename": str,                     # optional, without .html; else derived
  "matched_keywords": [str, ...],      # optional, used only to derive filename
  "scores": {"originality": float, "methodology": float,
             "significance": float, "overall": float},
  "sections": {"novelty": str, "rigor": str, "methods": str,
               "main_results": str, "limitations": str,
               "inspiration": str, "additional_thoughts": str}
}
Prints the written file path.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path

DEFAULT_REVIEWS_DIR = Path.home() / "Desktop" / "Claude" / "week-lit-review-results" / "reviews"

_BASIS = {
    "pdf": ("review-basis", "Full PDF"),
    "text": ("review-basis text-source", "Full Text / Metadata"),
    "abstract": ("review-basis abstract-only", "Abstract Only"),
}

_STYLE = """
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 40px auto;
            padding: 0 20px;
            color: #333;
            background: #f5f5f5;
        }
        .container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; margin-bottom: 30px; }
        h2 { color: #34495e; margin-top: 30px; border-left: 4px solid #3498db; padding-left: 15px; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background-color: #3498db; color: white; font-weight: 600; }
        tr:hover { background-color: #f5f5f5; }
        .score-overall { font-size: 1.2em; font-weight: bold; color: #e74c3c; }
        .metadata { background: #ecf0f1; padding: 15px; border-radius: 5px; margin: 20px 0; }
        .metadata a { color: #3498db; text-decoration: none; }
        .metadata a:hover { text-decoration: underline; }
        .section { margin: 25px 0; }
        .review-basis { display: inline-block; padding: 5px 12px; background: #2ecc71; color: white; border-radius: 4px; font-size: 0.9em; }
        .review-basis.text-source { background: #2980b9; }
        .review-basis.abstract-only { background: #e67e22; }
"""

_SECTION_ORDER = [
    ("novelty", "Novelty"),
    ("rigor", "Rigor"),
    ("methods", "Methods"),
    ("main_results", "Main Results"),
    ("limitations", "Limitations"),
    ("inspiration", "Inspiration for the Field"),
    ("additional_thoughts", "Reviewer's Additional Thoughts"),
]


def _slug(text: str, maxlen: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:maxlen]


def derive_filename(rec: dict) -> str:
    source = re.sub(r"\s*\(.*?\)", "", rec.get("source", "") or "unknown")
    journal = _slug(source) or "unknown"
    authors = rec.get("authors", "") or ""
    first = authors.split(";")[0].split(",")[0].strip()
    last = re.sub(r"[^a-z]", "", first.split()[-1].lower()) if first.split() else "unknown"
    date = (rec.get("date", "") or "unknown-date")[:10]
    kws = rec.get("matched_keywords") or []
    topic = "-".join(_slug(k) for k in kws[:4] if _slug(k)) or "paper"
    return f"{journal}-{last}-{date}-{topic}"


def _score(scores: dict, key: str) -> str:
    v = scores.get(key)
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "—"


def render_html(rec: dict) -> str:
    scores = rec.get("scores", {}) or {}
    sections = rec.get("sections", {}) or {}
    basis_class, basis_label = _BASIS.get((rec.get("review_basis") or "pdf").lower(),
                                          _BASIS["pdf"])
    doi = escape(rec.get("doi", "") or "")
    url = escape(rec.get("url", "") or "")
    title = escape(rec.get("title", "") or "Untitled")

    section_html = "\n".join(
        f'''        <div class="section">
            <h2>{escape(label)}</h2>
            <p>{escape(sections.get(key, "") or "—")}</p>
        </div>'''
        for key, label in _SECTION_ORDER
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Review: {title}</title>
    <style>{_STYLE}    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>

        <div class="metadata">
            <table>
                <tr><th>Authors</th><td>{escape(rec.get("authors", "") or "")}</td></tr>
                <tr><th>Source</th><td>{escape(rec.get("source", "") or "")}</td></tr>
                <tr><th>Date</th><td>{escape(rec.get("date", "") or "")}</td></tr>
                <tr><th>DOI</th><td><a href="https://doi.org/{doi}" target="_blank">{doi}</a></td></tr>
                <tr><th>URL</th><td><a href="{url}" target="_blank">{url}</a></td></tr>
                <tr><th>Review Basis</th><td><span class="{basis_class}">{basis_label}</span></td></tr>
            </table>
        </div>

        <h2>Scores</h2>
        <table>
            <thead><tr><th>Dimension</th><th>Score</th></tr></thead>
            <tbody>
                <tr><td>Originality</td><td>{_score(scores, "originality")} / 10</td></tr>
                <tr><td>Methodology</td><td>{_score(scores, "methodology")} / 10</td></tr>
                <tr><td>Significance</td><td>{_score(scores, "significance")} / 10</td></tr>
                <tr><td><strong>Overall</strong></td><td class="score-overall">{_score(scores, "overall")} / 10</td></tr>
            </tbody>
        </table>

{section_html}
    </div>
</body>
</html>
"""


def _record_in_index(index_path: Path, stem: str) -> None:
    """Append stem to the run index (a JSON list of stems), de-duped, order-preserving."""
    try:
        stems = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(stems, list):
            stems = []
    except (OSError, ValueError):
        stems = []
    if stem not in stems:
        stems.append(stem)
        index_path.write_text(json.dumps(stems, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render a paper review JSON to HTML.")
    ap.add_argument("review_json", help="Path to the review JSON file.")
    ap.add_argument("--reviews-dir", default=str(DEFAULT_REVIEWS_DIR),
                    help="Shared reviews output dir (default: …/week-lit-review-results/reviews).")
    args = ap.parse_args(argv)

    review_path = Path(args.review_json)
    rec = json.loads(review_path.read_text(encoding="utf-8"))
    reviews_dir = Path(args.reviews_dir).expanduser()
    reviews_dir.mkdir(parents=True, exist_ok=True)
    stem = rec.get("filename") or derive_filename(rec)
    stem = stem[:-5] if stem.endswith(".html") else stem

    out = reviews_dir / f"{stem}.html"
    out.write_text(render_html(rec), encoding="utf-8")
    # Persist the record so render_summary.py can build the summary without an LLM.
    rec["filename"] = stem
    (reviews_dir / f"{stem}.json").write_text(
        json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    # Record this review in the run's index (kept beside the input _review.json).
    _record_in_index(review_path.resolve().parent / "_index.json", stem)

    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
