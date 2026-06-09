#!/usr/bin/env python3
"""Back-fill `{stem}.json` sidecars for review HTMLs that predate them.

render_summary.py builds the run summary from the per-paper review JSON sidecars
that render_review.py now persists next to each `{stem}.html`. Older reviews have
only HTML; this parses each such HTML back into the review record so they can be
re-summarised. Idempotent: skips any HTML that already has a `.json` sidecar.

Usage:
    backfill_review_json.py [--reviews-dir DIR] [--force]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

DEFAULT_REVIEWS_DIR = Path.home() / "Desktop" / "Claude" / "week-lit-review-results" / "reviews"

# h2 label (after HTML-unescaping) -> review JSON section key.
SECTION_KEYS = {
    "Novelty": "novelty",
    "Rigor": "rigor",
    "Methods": "methods",
    "Main Results": "main_results",
    "Limitations": "limitations",
    "Inspiration for the Field": "inspiration",
    "Reviewer's Additional Thoughts": "additional_thoughts",
}
SCORE_KEYS = [("originality", "Originality"), ("methodology", "Methodology"),
              ("significance", "Significance"), ("overall", "Overall")]


def _text(s: str) -> str:
    """Strip tags and unescape entities to recover the original field text."""
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _meta(html_text: str, label: str) -> str:
    m = re.search(rf"<th>{re.escape(label)}</th><td>(.*?)</td>", html_text, re.S)
    return _text(m.group(1)) if m else ""


def parse_review_html(html_text: str) -> dict:
    rec: dict = {}
    m = re.search(r"<h1>(.*?)</h1>", html_text, re.S)
    rec["title"] = _text(m.group(1)) if m else ""
    rec["authors"] = _meta(html_text, "Authors")
    rec["source"] = _meta(html_text, "Source")
    rec["date"] = _meta(html_text, "Date")
    rec["doi"] = _meta(html_text, "DOI")
    rec["url"] = _meta(html_text, "URL")

    mb = re.search(r"<th>Review Basis</th><td>\s*<span class=\"([^\"]*)\"", html_text)
    cls = mb.group(1) if mb else "review-basis"
    rec["review_basis"] = ("abstract" if "abstract-only" in cls
                           else "text" if "text-source" in cls else "pdf")
    rec["matched_keywords"] = []  # not present in HTML

    scores: dict = {}
    for key, label in SCORE_KEYS:
        ms = re.search(rf"{label}.*?</td>\s*<td[^>]*>\s*([\d.]+)\s*/\s*10", html_text, re.S)
        if ms:
            scores[key] = float(ms.group(1))
    rec["scores"] = scores

    sections: dict = {}
    for m in re.finditer(r'<div class="section">\s*<h2>(.*?)</h2>\s*<p>(.*?)</p>',
                         html_text, re.S):
        key = SECTION_KEYS.get(_text(m.group(1)))
        if key:
            sections[key] = _text(m.group(2))
    rec["sections"] = sections
    return rec


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Back-fill review JSON sidecars from HTML.")
    ap.add_argument("--reviews-dir", default=str(DEFAULT_REVIEWS_DIR))
    ap.add_argument("--force", action="store_true", help="Overwrite existing sidecars.")
    args = ap.parse_args(argv)

    reviews_dir = Path(args.reviews_dir).expanduser()
    if not reviews_dir.is_dir():
        print(f"error: not a directory: {reviews_dir}", file=sys.stderr)
        return 1

    written = skipped = 0
    for html_path in sorted(reviews_dir.glob("*.html")):
        stem = html_path.stem
        json_path = reviews_dir / f"{stem}.json"
        if json_path.exists() and not args.force:
            skipped += 1
            continue
        rec = parse_review_html(html_path.read_text(encoding="utf-8"))
        rec["filename"] = stem
        json_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        n_sec, n_sc = len(rec["sections"]), len(rec["scores"])
        print(f"wrote {json_path.name}  (sections={n_sec}/7, scores={n_sc}/4)")
        written += 1

    print(f"\nback-fill complete: {written} written, {skipped} already had sidecars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
