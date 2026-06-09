"""Selection window (runs as its own process to avoid the rumps/pywebview
main-runloop conflict).

Usage:
    python3 selection_ui.py <manifest.json> <out_selection.json>

Renders the candidate table, lets the user pick papers, and writes the chosen
DOIs to <out_selection.json> as {"dois": [...]} (empty list if cancelled).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import webview  # pywebview

import actions  # shared author/reviewed helpers (scans per-date result folders)

HTML_PATH = Path(__file__).resolve().parent / "selection.html"


def _enrich(papers: list[dict]) -> list[dict]:
    doi_map = actions.reviewed_doi_map()  # computed once for all papers
    out: list[dict] = []
    for i, p in enumerate(papers, 1):
        ln = actions.first_author_lastname(p.get("authors", ""))
        doi = (p.get("doi") or "").strip()
        out.append({
            "n": i,
            "uid": p.get("uid") or doi or p.get("title", "")[:24],
            "doi": doi,
            "has_doi": bool(doi),
            "title": p.get("title", ""),
            "abstract": p.get("abstract", ""),
            "date": (p.get("date") or "")[:10],
            "source": p.get("source", ""),
            "first_author": ln,
            "corresponding_author": p.get("corresponding_author", ""),
            "affiliation": p.get("affiliation", ""),
            "matched_keywords": p.get("matched_keywords", []),
            "reviewed": actions.find_existing_review(
                doi=doi, lastname=ln, date=p.get("date", ""), doi_map=doi_map) is not None,
        })
    return out


class Api:
    def __init__(self, papers: list[dict]):
        self._papers = papers
        self.result: list[str] = []
        self.window = None

    def get_papers(self) -> list[dict]:
        return self._papers

    def submit(self, dois: list[str]) -> None:
        self.result = [d for d in (dois or []) if d]
        if self.window:
            self.window.destroy()

    def cancel(self) -> None:
        self.result = []
        if self.window:
            self.window.destroy()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: selection_ui.py <manifest.json> <out.json>", file=sys.stderr)
        return 2
    manifest_path, out_path = Path(argv[1]), Path(argv[2])
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    papers = _enrich(data.get("papers", []))

    api = Api(papers)
    window = webview.create_window(
        "Select papers to deep-review",
        HTML_PATH.as_uri(),
        js_api=api,
        width=1200,
        height=820,
    )
    api.window = window
    webview.start()  # blocks until the window is destroyed

    out_path.write_text(json.dumps({"dois": api.result}), encoding="utf-8")
    # pywebview/Cocoa can leave non-daemon threads alive after start() returns,
    # which would hang this process and block the parent waiting on it. Exit hard.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
