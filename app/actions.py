"""Shared pipeline actions used by both front-ends (menu-bar app + control window).

Keeping fetch/selection here means the two UIs stay in sync and there's one place
that knows how to spawn the child scripts. Deep review lives in review_runner.py.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from paths import (
    CANDIDATES_DIR,
    CONFIG_PATH,
    FETCH_SCRIPT,
    PYTHON,
    REPO_ROOT,
    REVIEWS_DIR,
    manifest_path,
    today_dir,
)

SELECTION_UI: Path = Path(__file__).resolve().parent / "selection_ui.py"


def count_candidates() -> int:
    """Number of genomics candidates in the persistent manifest (0 if none)."""
    try:
        data = json.loads(manifest_path().read_text(encoding="utf-8"))
        return int(data.get("total_genomics", len(data.get("papers", []))))
    except Exception:
        return 0


def candidates_date() -> str:
    """The date the persistent candidates were fetched ('' if unknown)."""
    try:
        return json.loads(manifest_path().read_text(encoding="utf-8")).get("date", "") or ""
    except Exception:
        return ""


def fetch_candidates() -> tuple[int, Path]:
    """Fetch candidates (abstracts only) into the stable candidates/ dir. Blocking.

    Persists to manifest_path() so candidates are reused across launches/days and
    are not clobbered by the per-date DOI review manifest. Returns (rc, log_path).
    """
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    today_dir().mkdir(parents=True, exist_ok=True)
    log = today_dir() / f"app_fetch_{datetime.now():%H%M%S}.log"
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [PYTHON, str(FETCH_SCRIPT),
             "--config", str(CONFIG_PATH),
             "--output-dir", str(CANDIDATES_DIR),
             "--no-pdf"],
            cwd=str(REPO_ROOT), stdout=fh, stderr=subprocess.STDOUT, text=True,
        )
    return proc.returncode, log


def first_author_lastname(authors: str) -> str:
    """Last name of the first author (handles 'Last, F.' and 'First Last' forms)."""
    if not authors:
        return ""
    first = re.split(r";", authors)[0].strip()
    if "," in first:  # bioRxiv "Last, F." form
        return first.split(",")[0].strip()
    toks = first.split()
    return toks[-1] if toks else first


def reviewed_doi_map() -> dict[str, Path]:
    """Map reviewed DOI (lowercased) -> review HTML path, from reviews/*.json sidecars.

    DOI is the reliable identity key: the same paper can be filed under different
    dates across fetches, so filename matching is unreliable.
    """
    out: dict[str, Path] = {}
    if not REVIEWS_DIR.is_dir():
        return out
    for jf in REVIEWS_DIR.glob("*.json"):
        try:
            doi = (json.loads(jf.read_text(encoding="utf-8")).get("doi") or "").strip().lower()
        except (OSError, ValueError):
            continue
        html = jf.with_suffix(".html")
        if doi and html.exists():
            out[doi] = html
    return out


def find_existing_review(doi: str = "", lastname: str = "", date: str = "",
                         doi_map: dict[str, Path] | None = None) -> Path | None:
    """Existing review for a paper: by DOI (exact, preferred), else lastname+date.

    Pass a precomputed `doi_map` (from reviewed_doi_map()) when checking many papers
    to avoid rescanning the sidecars each call. The lastname+date fallback covers
    papers with no DOI or legacy reviews whose sidecar lacks one.
    """
    d = (doi or "").strip().lower()
    if d:
        m = doi_map if doi_map is not None else reviewed_doi_map()
        hit = m.get(d)
        if hit:
            return hit
    ln = (lastname or "").lower()
    dt = (date or "")[:10]
    if ln and REVIEWS_DIR.is_dir():
        for p in REVIEWS_DIR.glob("*.html"):
            n = p.name.lower()
            if ln in n and (dt in n if dt else True):
                return p
    return None


def _manifest_by_doi() -> dict[str, dict]:
    try:
        papers = json.loads(manifest_path().read_text(encoding="utf-8")).get("papers", [])
    except Exception:
        return {}
    return {(p.get("doi") or "").strip(): p for p in papers if (p.get("doi") or "").strip()}


def partition_reviewed(dois: list[str]) -> tuple[list[str], list[tuple[str, Path]]]:
    """Split DOIs into (to_review, already_reviewed).

    already_reviewed is [(doi, existing_review_path)]. Uses today's manifest to map
    each DOI to its author/date for the filename match.
    """
    by_doi = _manifest_by_doi()
    doi_map = reviewed_doi_map()
    to_review: list[str] = []
    already: list[tuple[str, Path]] = []
    for doi in dois:
        rec = by_doi.get(doi)
        existing = find_existing_review(
            doi=doi,
            lastname=first_author_lastname(rec.get("authors", "")) if rec else "",
            date=rec.get("date", "") if rec else "",
            doi_map=doi_map,
        )
        if existing:
            already.append((doi, existing))
        else:
            to_review.append(doi)
    return to_review, already


def run_selection() -> list[str]:
    """Open the picker window (own process) and return the chosen DOIs.

    Empty list if cancelled or nothing picked. Blocking — call from a thread.
    """
    with tempfile.NamedTemporaryFile("r", suffix=".json", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        subprocess.run(
            [PYTHON, str(SELECTION_UI), str(manifest_path()), str(out_path)],
            cwd=str(REPO_ROOT), text=True,
        )
        dois = json.loads(out_path.read_text(encoding="utf-8")).get("dois", [])
        return [d for d in dois if d]
    finally:
        out_path.unlink(missing_ok=True)
