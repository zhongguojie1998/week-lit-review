#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2.0", "httpx>=0.27"]
# ///
"""Local bioRxiv / medRxiv MCP server.

Drop-in replacement for the deepsense-hosted `bioRxiv` connector
(https://mcp.deepsense.ai/biorxiv/mcp), which is down. Backed by the public
bioRxiv API (https://api.biorxiv.org) for metadata/listing and Europe PMC for
keyword search. No API key required.

Run standalone:   uv run scripts/biorxiv_mcp.py
Wired via .mcp.json / plugin manifest for Claude Code.
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal, Optional

import httpx
from mcp.server.fastmcp import FastMCP

BIORXIV_API = "https://api.biorxiv.org"
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
USER_AGENT = "weekly-lit-review-biorxiv-mcp/1.0 (mailto:renlab@nygenome.org)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

Server = Literal["biorxiv", "medrxiv"]

mcp = FastMCP("bioRxiv")


async def _get_json(url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET a URL and parse JSON, raising a clear error on failure."""
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _normalize_doi(doi: str) -> str:
    """Strip URL/prefix noise so a DOI is in bare `10.xxxx/...` form."""
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip()


def _fmt_detail(rec: dict[str, Any]) -> dict[str, Any]:
    """Normalize a bioRxiv API detail record to a compact dict."""
    return {
        "doi": rec.get("doi"),
        "title": rec.get("title"),
        "authors": rec.get("authors"),
        "author_corresponding": rec.get("author_corresponding"),
        "institution": rec.get("author_corresponding_institution"),
        "date": rec.get("date"),
        "version": rec.get("version"),
        "category": rec.get("category"),
        "abstract": rec.get("abstract"),
        "published_doi": rec.get("published") if rec.get("published") not in ("NA", None) else None,
        "url": f"https://doi.org/{rec.get('doi')}" if rec.get("doi") else None,
        "pdf_url": (
            f"https://www.biorxiv.org/content/{rec.get('doi')}v{rec.get('version')}.full.pdf"
            if rec.get("doi") and rec.get("version") else None
        ),
    }


@mcp.tool()
async def get_preprint(doi: str, server: Server = "biorxiv") -> dict[str, Any]:
    """Fetch full metadata for a single preprint by DOI.

    Returns title, authors, abstract, category, version history, and the
    published-journal DOI if the preprint was later published.

    Args:
        doi: Preprint DOI, e.g. "10.1101/2024.01.01.573800" (URL forms accepted).
        server: "biorxiv" or "medrxiv".
    """
    doi = _normalize_doi(doi)
    url = f"{BIORXIV_API}/details/{server}/{doi}/na/json"
    data = await _get_json(url)
    collection = data.get("collection") or []
    if not collection:
        msg = data.get("messages", [{}])
        status = msg[0].get("status") if msg else "no results"
        return {"error": f"No preprint found for DOI {doi} on {server} ({status})."}
    # Latest version is last in the collection.
    versions = [_fmt_detail(r) for r in collection]
    latest = versions[-1]
    latest["all_versions"] = [
        {"version": v.get("version"), "date": v.get("date")} for v in versions
    ]
    return latest


@mcp.tool()
async def list_recent_preprints(
    from_date: str,
    to_date: str,
    server: Server = "biorxiv",
    category: Optional[str] = None,
    limit: int = 30,
) -> dict[str, Any]:
    """List preprints posted in a date range, newest first.

    Use this for "what came out this week" style queries. Optionally filter by
    bioRxiv subject category (e.g. "genomics", "bioinformatics", "neuroscience").

    Args:
        from_date: Start date, YYYY-MM-DD.
        to_date: End date, YYYY-MM-DD.
        server: "biorxiv" or "medrxiv".
        category: Optional case-insensitive subject-category filter.
        limit: Max records to return (1-100).
    """
    limit = max(1, min(limit, 100))
    results: list[dict[str, Any]] = []
    cursor = 0
    total: Optional[int] = None
    cat_lc = category.lower().strip() if category else None

    # Paginate (100/page) until we have `limit` matches or exhaust the range.
    while len(results) < limit:
        url = f"{BIORXIV_API}/details/{server}/{from_date}/{to_date}/{cursor}"
        data = await _get_json(url)
        msgs = data.get("messages") or [{}]
        if total is None:
            total = int(msgs[0].get("total", 0) or 0)
        collection = data.get("collection") or []
        if not collection:
            break
        for rec in collection:
            if cat_lc and (rec.get("category") or "").lower() != cat_lc:
                continue
            results.append(_fmt_detail(rec))
            if len(results) >= limit:
                break
        cursor += len(collection)
        if total is not None and cursor >= total:
            break

    return {
        "server": server,
        "from_date": from_date,
        "to_date": to_date,
        "category": category,
        "total_in_range": total,
        "returned": len(results),
        "preprints": results,
    }


@mcp.tool()
async def search_preprints(
    query: str,
    server: Optional[Server] = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Keyword/full-text search across bioRxiv & medRxiv preprints.

    Searches titles and abstracts via Europe PMC (the bioRxiv API itself has no
    keyword search). Returns the most relevant preprints with abstracts.

    Args:
        query: Free-text query, e.g. 'single-cell ATAC-seq chromatin'.
        server: Restrict to "biorxiv" or "medrxiv"; omit for both.
        limit: Max results (1-100).
    """
    limit = max(1, min(limit, 100))
    q = f"({query}) AND SRC:PPR"
    if server == "biorxiv":
        q += ' AND PUBLISHER:"bioRxiv"'
    elif server == "medrxiv":
        q += ' AND PUBLISHER:"medRxiv"'
    params = {
        "query": q,
        "format": "json",
        "resultType": "core",
        "pageSize": str(limit),
        "sort": "P_PDATE_D desc",
    }
    data = await _get_json(EUROPEPMC_API, params=params)
    hits = (data.get("resultList") or {}).get("result") or []
    out: list[dict[str, Any]] = []
    for h in hits:
        doi = h.get("doi")
        out.append({
            "doi": doi,
            "title": h.get("title"),
            "authors": h.get("authorString"),
            "date": h.get("firstPublishDate") or h.get("pubYear"),
            "publisher": h.get("publisher"),
            "abstract": h.get("abstractText"),
            "url": f"https://doi.org/{doi}" if doi else None,
        })
    return {
        "query": query,
        "server": server or "both",
        "hit_count": int(data.get("hitCount", len(out)) or len(out)),
        "returned": len(out),
        "results": out,
    }


@mcp.tool()
async def get_published_version(doi: str, server: Server = "biorxiv") -> dict[str, Any]:
    """Check whether a preprint was published in a journal, and where.

    Args:
        doi: Preprint DOI.
        server: "biorxiv" or "medrxiv".
    """
    doi = _normalize_doi(doi)
    url = f"{BIORXIV_API}/pubs/{server}/{doi}/na/json"
    data = await _get_json(url)
    collection = data.get("collection") or []
    if not collection:
        return {"doi": doi, "published": False, "note": "No published version found."}
    rec = collection[0]
    return {
        "preprint_doi": rec.get("biorxiv_doi") or rec.get("preprint_doi") or doi,
        "published": True,
        "published_doi": rec.get("published_doi"),
        "published_journal": rec.get("published_journal"),
        "published_date": rec.get("published_date"),
        "preprint_title": rec.get("preprint_title"),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
