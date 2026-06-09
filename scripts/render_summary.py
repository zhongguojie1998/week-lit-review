#!/usr/bin/env python3
"""Build the run summary HTML in pure Python from the per-paper review JSONs.

No LLM and no hand-written summary JSON: render_review.py persists a `{stem}.json`
record per review in the shared reviews/ dir and lists this run's stems in
`<date>/_index.json`. This script reads those and emits `<date>/summary.html`,
linking each card to `../reviews/{stem}.html`.

Usage:
    render_summary.py --date YYYY-MM-DD
    render_summary.py --index <date>/_index.json [--reviews-dir DIR] [--output PATH]

Papers are sorted by overall score (desc). Prints the written file path.
"""
from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

DEFAULT_RESULTS_DIR = Path.home() / "Desktop" / "Claude" / "week-lit-review-results"
DEFAULT_REVIEWS_DIR = DEFAULT_RESULTS_DIR / "reviews"

_STYLE = """
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 40px auto;
            padding: 0 20px;
            color: #333;
            background: #f5f5f5;
        }
        .container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; margin-bottom: 30px; }
        .stats { background: #ecf0f1; padding: 20px; border-radius: 5px; margin: 30px 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
        .stat-item { text-align: center; }
        .stat-value { font-size: 2em; font-weight: bold; color: #3498db; }
        .stat-label { color: #7f8c8d; font-size: 0.9em; }
        .paper-card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin: 20px 0; transition: box-shadow 0.3s; }
        .paper-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .paper-title { font-size: 1.3em; margin-bottom: 10px; }
        .paper-title a { color: #2c3e50; text-decoration: none; font-weight: 600; }
        .paper-title a:hover { color: #3498db; }
        .paper-meta { color: #7f8c8d; font-size: 0.9em; margin: 10px 0; }
        .scores { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 15px 0; }
        .score-item { text-align: center; padding: 10px; background: #f8f9fa; border-radius: 5px; }
        .score-label { font-size: 0.8em; color: #7f8c8d; margin-bottom: 5px; }
        .score-value { font-size: 1.5em; font-weight: bold; color: #2c3e50; }
        .score-overall { background: #3498db; color: white; }
        .score-overall .score-label { color: #ecf0f1; }
        .score-overall .score-value { color: white; }
        .paper-summary { margin-top: 15px; padding: 15px; background: #f8f9fa; border-left: 4px solid #3498db; font-style: italic; }
        .rank { display: inline-block; width: 40px; height: 40px; line-height: 40px; text-align: center; border-radius: 50%; background: #3498db; color: white; font-weight: bold; margin-right: 15px; }
"""


def _f(scores: dict, key: str) -> str:
    try:
        return f"{float(scores.get(key)):.1f}"
    except (TypeError, ValueError):
        return "—"


def _overall(p: dict) -> float:
    try:
        return float((p.get("scores") or {}).get("overall"))
    except (TypeError, ValueError):
        return -1.0


def _blurb(rec: dict, maxlen: int = 320) -> str:
    """One-line card summary: explicit `summary` field, else trimmed Main Results."""
    s = (rec.get("summary") or "").strip()
    if not s:
        sections = rec.get("sections") or {}
        s = (sections.get("main_results") or sections.get("novelty") or "").strip()
    if len(s) > maxlen:
        s = s[:maxlen].rsplit(" ", 1)[0] + "…"
    return s


def render_html(date: str, records: list[dict]) -> str:
    date = escape(date or "")
    papers = sorted(records, key=_overall, reverse=True)
    total = len(papers)
    full = sum(1 for p in papers if (p.get("review_basis") or "").lower() in ("pdf", "text"))
    abstract = sum(1 for p in papers if (p.get("review_basis") or "").lower() == "abstract")
    overalls = [_overall(p) for p in papers if _overall(p) >= 0]
    avg = f"{sum(overalls) / len(overalls):.1f}" if overalls else "—"

    cards = []
    for i, p in enumerate(papers, 1):
        scores = p.get("scores", {}) or {}
        fn = escape(p.get("filename", "") or "")
        cards.append(f"""        <div class="paper-card">
            <div class="paper-title">
                <span class="rank">{i}</span>
                <a href="../reviews/{fn}.html" target="_blank">{escape(p.get("title", "") or "")}</a>
            </div>
            <div class="paper-meta">
                <strong>Source:</strong> {escape(p.get("source", "") or "")} | <strong>Date:</strong> {escape(p.get("date", "") or "")} | <strong>Authors:</strong> {escape(p.get("authors", "") or "")}
            </div>
            <div class="scores">
                <div class="score-item"><div class="score-label">Originality</div><div class="score-value">{_f(scores, "originality")}</div></div>
                <div class="score-item"><div class="score-label">Methodology</div><div class="score-value">{_f(scores, "methodology")}</div></div>
                <div class="score-item"><div class="score-label">Significance</div><div class="score-value">{_f(scores, "significance")}</div></div>
                <div class="score-item score-overall"><div class="score-label">Overall</div><div class="score-value">{_f(scores, "overall")}</div></div>
            </div>
            <div class="paper-summary">{escape(_blurb(p))}</div>
        </div>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Literature Review Summary - {date}</title>
    <style>{_STYLE}    </style>
</head>
<body>
    <div class="container">
        <h1>Literature Review Summary - {date}</h1>

        <div class="stats">
            <div class="stat-item"><div class="stat-value">{total}</div><div class="stat-label">Total Papers Reviewed</div></div>
            <div class="stat-item"><div class="stat-value">{full}</div><div class="stat-label">Full Source Reviews</div></div>
            <div class="stat-item"><div class="stat-value">{abstract}</div><div class="stat-label">Abstract-Only Reviews</div></div>
            <div class="stat-item"><div class="stat-value">{avg}</div><div class="stat-label">Average Overall Score</div></div>
        </div>

{chr(10).join(cards)}
    </div>
</body>
</html>
"""


def _load_records(stems: list[str], reviews_dir: Path) -> list[dict]:
    records: list[dict] = []
    for stem in stems:
        jf = reviews_dir / f"{stem}.json"
        try:
            rec = json.loads(jf.read_text(encoding="utf-8"))
            rec.setdefault("filename", stem)
            records.append(rec)
        except (OSError, ValueError):
            print(f"warning: skipping missing/invalid review JSON: {jf}", file=sys.stderr)
    return records


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Build the run summary HTML from review JSONs.")
    ap.add_argument("--date", default="", help="Run date YYYY-MM-DD (locates <results>/<date>/_index.json).")
    ap.add_argument("--index", default="", help="Explicit path to the run's _index.json (overrides --date).")
    ap.add_argument("--reviews-dir", default=str(DEFAULT_REVIEWS_DIR),
                    help="Shared reviews dir holding {stem}.json (default: …/reviews).")
    ap.add_argument("--output", default="", help="Output HTML path (default: <results>/<date>/summary.html).")
    args = ap.parse_args(argv)

    if args.index:
        index_path = Path(args.index).expanduser()
        date = args.date or index_path.resolve().parent.name
    elif args.date:
        index_path = DEFAULT_RESULTS_DIR / args.date / "_index.json"
        date = args.date
    else:
        ap.error("provide --date or --index")

    try:
        stems = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"error: cannot read run index: {index_path}", file=sys.stderr)
        return 1

    reviews_dir = Path(args.reviews_dir).expanduser()
    records = _load_records(stems, reviews_dir)

    out = Path(args.output).expanduser() if args.output \
        else DEFAULT_RESULTS_DIR / date / "summary.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(date, records), encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
