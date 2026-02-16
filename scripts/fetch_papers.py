#!/usr/bin/env python3
"""
Fetch & Download — Genomics Paper Collector
============================================
Searches bioRxiv + journal RSS feeds for genomics papers, downloads PDFs,
and outputs a JSON manifest for Claude Code to review.

NO Anthropic API key needed — this script only does search + download.
Claude Code itself reads the PDFs and writes reviews.

Usage:
    python fetch_papers.py --config config.yaml
    python fetch_papers.py --days 7 --max-papers 20
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Lazy imports — installed at runtime if missing
# ---------------------------------------------------------------------------
requests = None
feedparser = None
yaml_mod = None


def install_deps():
    """Install required packages and import them."""
    global requests, feedparser, yaml_mod
    import subprocess

    deps = {"requests": "requests", "feedparser": "feedparser", "pyyaml": "yaml"}
    for pkg, import_name in deps.items():
        try:
            __import__(import_name)
        except ImportError:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    import requests as _requests
    import feedparser as _feedparser
    import yaml as _yaml

    requests = _requests
    feedparser = _feedparser
    yaml_mod = _yaml


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Default config path relative to this script: ../assets/config.yaml
_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG_PATH = _SCRIPT_DIR.parent / "assets" / "config.yaml"


def load_config(config_path: Optional[str] = None) -> dict:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        cfg = yaml_mod.safe_load(f) or {}
    # Ensure runtime-only defaults that aren't in the YAML
    cfg.setdefault("download_pdfs", True)
    cfg.setdefault("pdf_timeout", 30)
    cfg.setdefault("max_papers_per_source", 50)
    return cfg


# ---------------------------------------------------------------------------
# Source 1: bioRxiv
# ---------------------------------------------------------------------------
def fetch_biorxiv(cfg: dict, logger: logging.Logger) -> list[dict]:
    papers = []
    days = cfg["days_lookback"]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    limit = cfg["max_papers_per_source"]

    for cat in cfg["biorxiv_categories"]:
        logger.info(f"  bioRxiv category: {cat}")
        cursor = 0
        cat_papers = []
        while len(cat_papers) < limit:
            url = (
                f"https://api.biorxiv.org/details/biorxiv/"
                f"{start_date}/{end_date}/{cursor}/json"
            )
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"    bioRxiv API error: {e}")
                break

            collection = data.get("collection", [])
            if not collection:
                break

            for item in collection:
                item_cat = item.get("category", "").lower()
                if cat.lower() in item_cat:
                    doi = item.get("doi", "")
                    version = item.get("version", "1")
                    title = item.get("title", "").strip()
                    abstract = item.get("abstract", "")
                    if title and abstract:
                        uid = hashlib.md5(f"{doi or title}".encode()).hexdigest()[:12]
                        cat_papers.append({
                            "uid": uid,
                            "title": title,
                            "authors": item.get("authors", ""),
                            "abstract": abstract,
                            "source": f"bioRxiv ({item_cat})",
                            "url": f"https://doi.org/{doi}",
                            "doi": doi,
                            "date": item.get("date", ""),
                            "pdf_url": f"https://www.biorxiv.org/content/{doi}v{version}.full.pdf",
                        })

            cursor += len(collection)
            if len(collection) < 30:
                break
            time.sleep(0.5)

        logger.info(f"    {len(cat_papers)} papers found")
        papers.extend(cat_papers[:limit])

    # Deduplicate
    seen = set()
    unique = []
    for p in papers:
        key = p["doi"] or p["title"]
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# Source 2: Journal RSS Feeds
# ---------------------------------------------------------------------------
def fetch_journal_feeds(cfg: dict, logger: logging.Logger) -> list[dict]:
    papers = []
    cutoff = datetime.now() - timedelta(days=cfg["days_lookback"])

    for journal_name, feed_url in cfg["journal_feeds"].items():
        logger.info(f"  RSS: {journal_name}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            logger.warning(f"    Parse error: {e}")
            continue

        count = 0
        for entry in feed.entries[: cfg["max_papers_per_source"]]:
            pub_date = ""
            skip = False
            for date_attr in ("published_parsed", "updated_parsed"):
                parsed = getattr(entry, date_attr, None)
                if parsed:
                    try:
                        entry_dt = datetime(*parsed[:6])
                        if entry_dt < cutoff:
                            skip = True
                            break
                        pub_date = entry_dt.strftime("%Y-%m-%d")
                        break
                    except Exception:
                        pass
            if skip:
                continue

            title = entry.get("title", "").strip()
            abstract = entry.get("summary", entry.get("description", "")).strip()
            abstract = re.sub(r"<[^>]+>", "", abstract)
            link = entry.get("link", "")
            doi = entry.get("prism_doi", entry.get("dc_identifier", ""))
            authors = entry.get("author", entry.get("dc_creator", ""))

            if title:
                uid = hashlib.md5(f"{doi or title}".encode()).hexdigest()[:12]
                papers.append({
                    "uid": uid,
                    "title": title,
                    "authors": authors if isinstance(authors, str) else ", ".join(authors) if isinstance(authors, list) else "",
                    "abstract": abstract,
                    "source": journal_name,
                    "url": link,
                    "doi": doi,
                    "date": pub_date,
                    "pdf_url": "",
                })
                count += 1

        logger.info(f"    {count} entries")
        time.sleep(0.3)

    return papers


# ---------------------------------------------------------------------------
# Genomics filter
# ---------------------------------------------------------------------------
def filter_genomics(papers: list[dict], keywords: list[str]) -> list[dict]:
    result = []
    for p in papers:
        text = f"{p['title']} {p['abstract']}".lower()
        matched = [kw for kw in keywords if kw.lower() in text]
        if matched:
            p["matched_keywords"] = matched
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# PDF Download
# ---------------------------------------------------------------------------
def try_unpaywall_pdf(doi: str, timeout: int, logger: logging.Logger) -> Optional[str]:
    if not doi:
        logger.debug("    Unpaywall: no DOI, skipping")
        return None
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email=litreview@example.com"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            oa = data.get("best_oa_location") or {}
            pdf_url = oa.get("url_for_pdf")
            if pdf_url:
                logger.info(f"    Unpaywall: found OA PDF for DOI {doi}")
            else:
                logger.info(f"    Unpaywall: no OA PDF available for DOI {doi}")
            return pdf_url
        else:
            logger.warning(f"    Unpaywall: HTTP {resp.status_code} for DOI {doi}")
    except Exception as e:
        logger.warning(f"    Unpaywall: error for DOI {doi}: {e}")
    return None


def _make_descriptive_name(paper: dict) -> str:
    """Build a filename stem like: nature-genetics-zhang-2026-02-10-scrna-seq-tumor."""
    # Journal
    source = paper.get("source", "unknown")
    # Strip parenthetical like "bioRxiv (genomics)" -> "bioRxiv"
    source = re.sub(r'\s*\(.*?\)', '', source)
    journal = re.sub(r'[^a-z0-9]+', '-', source.lower()).strip('-')

    # First author last name
    authors = paper.get("authors", "")
    first_author = authors.split(",")[0].split(";")[0].strip() if authors else "unknown"
    # Last name is typically the last word
    last_name = re.sub(r'[^a-z]', '', first_author.split()[-1].lower()) if first_author else "unknown"

    # Date
    pub_date = paper.get("date", "")[:10] or "unknown-date"

    # Topic keywords: use the genomics_keywords that matched this paper
    matched = paper.get("matched_keywords", [])
    # Normalize to lowercase hyphenated slugs, deduplicate, take up to 4
    seen = set()
    kw_slugs = []
    for kw in matched:
        slug = re.sub(r'[^a-z0-9]+', '-', kw.lower()).strip('-')
        if slug and slug not in seen:
            seen.add(slug)
            kw_slugs.append(slug)
        if len(kw_slugs) >= 4:
            break
    topic = "-".join(kw_slugs) if kw_slugs else "paper"

    return f"{journal}-{last_name}-{pub_date}-{topic}"


def download_pdf(paper: dict, output_dir: Path, timeout: int, logger: logging.Logger) -> Optional[str]:
    safe_name = _make_descriptive_name(paper)
    pdf_path = output_dir / f"{safe_name}.pdf"
    title_short = paper['title'][:60]

    if pdf_path.exists() and pdf_path.stat().st_size > 1000:
        logger.info(f"    Already have PDF: {title_short}...")
        return str(pdf_path)

    urls_to_try = []
    if paper.get("pdf_url"):
        urls_to_try.append(("direct", paper["pdf_url"]))
    else:
        logger.info(f"    No direct pdf_url for: {title_short}...")

    unpaywall_url = try_unpaywall_pdf(paper.get("doi", ""), timeout, logger)
    if unpaywall_url:
        urls_to_try.append(("unpaywall", unpaywall_url))

    if not urls_to_try:
        logger.warning(f"    No PDF URLs to try for: {title_short}...")
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LitReviewBot/1.0; mailto:litreview@example.com)",
        "Accept": "application/pdf",
    }

    for source, url in urls_to_try:
        try:
            logger.info(f"    Trying {source}: {url[:100]}...")
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            content_type = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and (
                "pdf" in content_type.lower() or resp.content[:5] == b"%PDF-"
            ):
                pdf_path.write_bytes(resp.content)
                logger.info(f"    PDF downloaded ({source}): {title_short}... ({len(resp.content)} bytes)")
                return str(pdf_path)
            else:
                logger.warning(
                    f"    Failed ({source}): HTTP {resp.status_code}, "
                    f"Content-Type={content_type}, body={len(resp.content)} bytes"
                )
        except Exception as e:
            logger.warning(f"    Failed ({source}): {e}")
            continue

    logger.warning(f"    All PDF download attempts failed for: {title_short}...")
    return None


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------
def run(cfg: dict):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("fetch-papers")

    output_dir = Path(cfg.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    # PDFs go to a shared folder alongside the date-stamped output dir
    pdf_dir = output_dir.parent / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("FETCH & DOWNLOAD — Genomics Paper Collector")
    logger.info("=" * 60)

    # Step 1: Fetch
    logger.info("\nStep 1: Fetching papers...")
    all_papers = []

    logger.info(" [bioRxiv]")
    all_papers.extend(fetch_biorxiv(cfg, logger))

    logger.info(" [Journal RSS Feeds]")
    all_papers.extend(fetch_journal_feeds(cfg, logger))

    logger.info(f"  Total fetched: {len(all_papers)}")

    # Step 2: Filter
    logger.info("\nStep 2: Filtering to genomics...")
    genomics = filter_genomics(all_papers, cfg["genomics_keywords"])
    logger.info(f"  Filtered {len(all_papers)} -> {len(genomics)} genomics papers")

    max_eval = cfg.get("max_papers_to_evaluate", 30)
    if len(genomics) > max_eval:
        logger.info(f"  Capping at {max_eval} papers")
        genomics = genomics[:max_eval]

    if not genomics:
        logger.warning("  No genomics papers found. Exiting.")
        manifest = {"papers": [], "pdf_dir": str(pdf_dir), "date": datetime.now().strftime("%Y-%m-%d")}
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"\nMANIFEST: {manifest_path}")
        return

    # Step 3: Download PDFs
    if cfg.get("download_pdfs", True):
        logger.info("\nStep 3: Downloading PDFs...")
        timeout = cfg.get("pdf_timeout", 30)
        for i, paper in enumerate(genomics):
            logger.info(f"  [{i+1}/{len(genomics)}] {paper['title'][:60]}...")
            pdf_path = download_pdf(paper, pdf_dir, timeout, logger)
            paper["pdf_path"] = pdf_path or ""
            paper["review_mode"] = "pdf" if pdf_path else "abstract"
            time.sleep(0.3)

        pdf_count = sum(1 for p in genomics if p.get("pdf_path"))
        logger.info(f"  Downloaded {pdf_count}/{len(genomics)} PDFs")
    else:
        logger.info("\nStep 3: Skipping PDF download (--no-pdf)")
        for p in genomics:
            p["pdf_path"] = ""
            p["review_mode"] = "abstract"

    # Step 4: Write manifest
    manifest = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "days_lookback": cfg["days_lookback"],
        "pdf_dir": str(pdf_dir),
        "total_fetched": len(all_papers),
        "total_genomics": len(genomics),
        "total_pdfs": sum(1 for p in genomics if p.get("pdf_path")),
        "papers": genomics,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    logger.info("\n" + "=" * 60)
    logger.info("FETCH COMPLETE")
    logger.info(f"  Papers: {len(genomics)}")
    logger.info(f"  PDFs: {manifest['total_pdfs']}")
    logger.info(f"  Manifest: {manifest_path}")
    logger.info("=" * 60)

    # Print the manifest path on its own line for easy parsing
    print(f"\nMANIFEST: {manifest_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    install_deps()

    parser = argparse.ArgumentParser(
        description="Fetch & Download — Genomics Paper Collector"
    )
    parser.add_argument("--config", help="Path to config YAML file")
    parser.add_argument("--days", type=int, help="Days to look back (default: 7)")
    parser.add_argument("--max-papers", type=int, help="Max papers to fetch")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF download")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.days:
        cfg["days_lookback"] = args.days
    if args.max_papers:
        cfg["max_papers_to_evaluate"] = args.max_papers
    if args.no_pdf:
        cfg["download_pdfs"] = False
    cfg["output_dir"] = str(Path(args.output_dir).expanduser())

    run(cfg)


if __name__ == "__main__":
    main()
