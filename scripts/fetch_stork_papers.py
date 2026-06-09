#!/usr/bin/env python3
"""
fetch_stork_papers.py — Gmail Stork Integration
================================================
Reads Stork publication-alert emails from Gmail, extracts PMIDs,
fetches metadata from PubMed, downloads PDFs, and writes a manifest
in the same format as fetch_papers.py.

Credentials:
  ~/.gmail-mcp/credentials.json   — OAuth tokens (access/refresh)
  ~/.gmail-mcp/gcp-oauth.keys.json — client_id / client_secret

Usage:
    python fetch_stork_papers.py --output-dir ~/Desktop/Claude/week-lit-review-results/2026-03-06
    python fetch_stork_papers.py --max-emails 3 --no-pdf --keywords "basal ganglia,GWAS"
"""

import argparse
import base64
import hashlib
import json
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------
requests = None


def install_deps():
    global requests
    import subprocess
    deps = {
        "requests": "requests",
        "google-api-python-client": "googleapiclient",
        "google-auth-oauthlib": "google_auth_oauthlib",
        "google-auth": "google.auth",
    }
    for pkg, import_name in deps.items():
        try:
            __import__(import_name.split(".")[0])
        except ImportError:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    import requests as _requests
    requests = _requests


# ---------------------------------------------------------------------------
# Gmail Auth
# ---------------------------------------------------------------------------
_CREDS_PATH = Path.home() / ".gmail-mcp" / "credentials.json"
_OAUTH_KEYS_PATH = Path.home() / ".gmail-mcp" / "gcp-oauth.keys.json"
_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def build_gmail_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    if not _CREDS_PATH.exists():
        raise FileNotFoundError(f"Gmail credentials not found at {_CREDS_PATH}")
    if not _OAUTH_KEYS_PATH.exists():
        raise FileNotFoundError(f"OAuth keys not found at {_OAUTH_KEYS_PATH}")

    raw = json.loads(_CREDS_PATH.read_text())
    oauth_keys = json.loads(_OAUTH_KEYS_PATH.read_text())
    client_cfg = oauth_keys.get("installed") or oauth_keys.get("web", {})

    creds = Credentials(
        token=raw.get("access_token"),
        refresh_token=raw.get("refresh_token"),
        token_uri=client_cfg.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_cfg["client_id"],
        client_secret=client_cfg["client_secret"],
        scopes=_GMAIL_SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Persist refreshed token
        raw["access_token"] = creds.token
        _CREDS_PATH.write_text(json.dumps(raw, indent=2))

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Gmail: search + read
# ---------------------------------------------------------------------------
def search_stork_emails(service, max_emails: int, logger: logging.Logger) -> list[str]:
    """Return list of message IDs for Stork alert emails."""
    query = 'subject:"Stork has brought you" from:storkapp.me'
    logger.info(f"  Gmail search: {query!r}")
    result = service.users().messages().list(
        userId="me", q=query, maxResults=max_emails
    ).execute()
    messages = result.get("messages", [])
    logger.info(f"  Found {len(messages)} Stork email(s)")
    return [m["id"] for m in messages]


def get_email_plain_text(service, msg_id: str) -> str:
    """Fetch a Gmail message and return its decoded plain text."""
    msg = service.users().messages().get(
        userId="me", messageId=msg_id, format="full"
    ).execute()

    def _extract_parts(payload) -> str:
        mime = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if mime == "text/plain" and body_data:
            return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")

        if mime == "text/html" and body_data:
            html = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
            # Strip HTML tags
            text = re.sub(r"<[^>]+>", " ", html)
            return re.sub(r"\s+", " ", text)

        for part in payload.get("parts", []):
            result = _extract_parts(part)
            if result:
                return result
        return ""

    return _extract_parts(msg.get("payload", {}))


# ---------------------------------------------------------------------------
# Parse Stork email: extract PMIDs (and optional title/journal context)
# ---------------------------------------------------------------------------
def parse_stork_email(text: str, logger: logging.Logger) -> list[dict]:
    """Extract paper entries from a Stork alert email body."""
    # Pattern: PMID: XXXXXXXX doi: XX.XXXX/...
    pmid_pattern = re.compile(r"PMID:\s*(\d+)\s+doi:\s*(\S+)")
    # Pattern for 'by Authors (Year) Journal' preceding the PMID line
    context_pattern = re.compile(
        r"by\s+(.{5,200}?)\s+\((\d{4})\)\s+([^\n\r<]{3,80}?)(?:\s*\(impact factor[^)]*\))?\s*$",
        re.MULTILINE,
    )

    entries = []
    for m in pmid_pattern.finditer(text):
        pmid = m.group(1)
        doi = m.group(2).strip().rstrip(".")

        # Look backwards ~600 chars for author/year/journal context
        before = text[max(0, m.start() - 600) : m.start()]
        ctx = list(context_pattern.finditer(before))
        authors, year, journal = "", "", ""
        if ctx:
            last = ctx[-1]
            authors = last.group(1).strip()
            year = last.group(2)
            journal = last.group(3).strip()

        entries.append({
            "pmid": pmid,
            "doi": doi,
            "authors": authors,
            "year": year,
            "journal": journal,
        })

    logger.info(f"  Parsed {len(entries)} paper entries from email")
    return entries


# ---------------------------------------------------------------------------
# PubMed: fetch metadata by PMID
# ---------------------------------------------------------------------------
_PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def fetch_pubmed_metadata(pmid: str, logger: logging.Logger) -> Optional[dict]:
    """Fetch structured metadata for a single PMID via NCBI E-utilities."""
    try:
        resp = requests.get(
            _PUBMED_EFETCH,
            params={"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"  PubMed efetch error for PMID {pmid}: {e}")
        return None

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.warning(f"  PubMed XML parse error for PMID {pmid}: {e}")
        return None

    article = root.find(".//PubmedArticle")
    if article is None:
        logger.warning(f"  PMID {pmid}: no PubmedArticle in response")
        return None

    # Title
    title_el = article.find(".//ArticleTitle")
    title = "".join(title_el.itertext()).strip() if title_el is not None else ""

    # Abstract
    abstract_parts = article.findall(".//AbstractText")
    abstract = " ".join("".join(el.itertext()).strip() for el in abstract_parts)

    # Authors
    authors_list = []
    for author in article.findall(".//Author"):
        last = author.findtext("LastName", "")
        fore = author.findtext("ForeName", "")
        if last:
            authors_list.append(f"{last} {fore}".strip())
    authors = "; ".join(authors_list)

    # Journal
    journal = article.findtext(".//Journal/Title", "") or article.findtext(".//MedlineTA", "")

    # Publication date
    pub_date_el = article.find(".//PubDate")
    year = pub_date_el.findtext("Year", "") if pub_date_el is not None else ""
    month = pub_date_el.findtext("Month", "01") if pub_date_el is not None else "01"
    day = pub_date_el.findtext("Day", "01") if pub_date_el is not None else "01"
    # Normalize month name -> number
    month_map = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    }
    month = month_map.get(month[:3], month.zfill(2))
    pub_date = f"{year}-{month}-{day.zfill(2)}" if year else ""

    # DOI from ArticleIdList
    doi = ""
    for aid in article.findall(".//ArticleId"):
        if aid.get("IdType") == "doi":
            doi = aid.text or ""
            break

    if not title:
        logger.warning(f"  PMID {pmid}: empty title, skipping")
        return None

    uid = hashlib.md5(f"{pmid}".encode()).hexdigest()[:12]
    return {
        "uid": uid,
        "pmid": pmid,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "source": journal,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "doi": doi,
        "date": pub_date,
        "pdf_url": "",
        "matched_keywords": [],
    }


# ---------------------------------------------------------------------------
# Keyword filter
# ---------------------------------------------------------------------------
def filter_by_keywords(papers: list[dict], keywords: list[str]) -> list[dict]:
    if not keywords:
        return papers
    result = []
    for p in papers:
        text = f"{p['title']} {p['abstract']}".lower()
        matched = [kw for kw in keywords if kw.lower() in text]
        if matched:
            p["matched_keywords"] = matched
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# PDF download — re-use fetch_papers.py cascade
# ---------------------------------------------------------------------------
def _import_download_fn():
    """Import download_source from fetch_papers in the same scripts/ dir."""
    import importlib.util
    script_dir = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "fetch_papers", script_dir / "fetch_papers.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.download_source


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run(args):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("fetch-stork")

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir.parent / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("FETCH STORK PAPERS — Gmail + PubMed Pipeline")
    logger.info("=" * 60)

    # Step 1: Gmail — find Stork emails
    logger.info("\nStep 1: Connecting to Gmail...")
    service = build_gmail_service()
    msg_ids = search_stork_emails(service, args.max_emails, logger)
    if not msg_ids:
        logger.warning("  No Stork emails found. Exiting.")
        return

    # Step 2: Parse emails — collect unique PMIDs
    logger.info("\nStep 2: Parsing Stork emails...")
    seen_pmids: set[str] = set()
    all_entries: list[dict] = []
    for msg_id in msg_ids:
        logger.info(f"  Reading message {msg_id}...")
        text = get_email_plain_text(service, msg_id)
        entries = parse_stork_email(text, logger)
        for entry in entries:
            if entry["pmid"] not in seen_pmids:
                seen_pmids.add(entry["pmid"])
                all_entries.append(entry)

    logger.info(f"  Total unique PMIDs: {len(all_entries)}")

    if args.max_papers and len(all_entries) > args.max_papers:
        logger.info(f"  Capping at {args.max_papers} papers")
        all_entries = all_entries[: args.max_papers]

    # Step 3: Fetch PubMed metadata
    logger.info("\nStep 3: Fetching PubMed metadata...")
    papers = []
    for i, entry in enumerate(all_entries):
        pmid = entry["pmid"]
        logger.info(f"  [{i+1}/{len(all_entries)}] PMID {pmid}...")
        meta = fetch_pubmed_metadata(pmid, logger)
        if meta:
            # Backfill from email parse if PubMed fields are empty
            if not meta["authors"] and entry["authors"]:
                meta["authors"] = entry["authors"]
            if not meta["source"] and entry["journal"]:
                meta["source"] = entry["journal"]
            if not meta["doi"] and entry["doi"]:
                meta["doi"] = entry["doi"]
            papers.append(meta)
        time.sleep(0.35)  # NCBI rate limit: ~3 req/s without API key

    logger.info(f"  Fetched metadata for {len(papers)}/{len(all_entries)} papers")

    # Step 4: Optional keyword filter
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else []
    if keywords:
        before = len(papers)
        papers = filter_by_keywords(papers, keywords)
        logger.info(f"\nStep 4: Keyword filter '{args.keywords}': {before} -> {len(papers)} papers")
    else:
        logger.info("\nStep 4: No keyword filter — keeping all papers")

    if not papers:
        logger.warning("  No papers after filtering. Exiting.")
        return

    # Step 5: Download source files
    if not args.no_pdf:
        logger.info("\nStep 5: Downloading source files...")
        download_source = _import_download_fn()
        for i, paper in enumerate(papers):
            logger.info(f"  [{i+1}/{len(papers)}] {paper['title'][:60]}...")
            source_path, source_format = download_source(paper, source_dir, 30, logger)
            paper["source_path"] = source_path or ""
            paper["source_format"] = source_format or ""
            paper["review_mode"] = (
                "pdf" if source_format == "pdf"
                else "text" if source_format in ("json", "xml", "txt")
                else "abstract"
            )
            time.sleep(0.3)
        source_count = sum(1 for p in papers if p.get("source_path"))
        logger.info(f"  Downloaded {source_count}/{len(papers)} source files")
    else:
        logger.info("\nStep 5: Skipping source file download (--no-pdf)")
        for p in papers:
            p["source_path"] = ""
            p["source_format"] = ""
            p["review_mode"] = "abstract"

    # Step 6: Write manifest
    manifest = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mode": "gmail-stork",
        "gmail_emails_read": len(msg_ids),
        "source_dir": str(source_dir),
        "total_fetched": len(all_entries),
        "total_papers": len(papers),
        "total_sources": sum(1 for p in papers if p.get("source_path")),
        "papers": papers,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    logger.info("\n" + "=" * 60)
    logger.info("STORK FETCH COMPLETE")
    logger.info(f"  Emails read:  {len(msg_ids)}")
    logger.info(f"  PMIDs found:  {len(all_entries)}")
    logger.info(f"  Papers kept:  {len(papers)}")
    logger.info(f"  Source files: {manifest['total_sources']}")
    logger.info(f"  Manifest:     {manifest_path}")
    logger.info("=" * 60)

    print(f"\nMANIFEST: {manifest_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    install_deps()

    parser = argparse.ArgumentParser(
        description="Fetch Stork publication-alert papers via Gmail + PubMed"
    )
    parser.add_argument(
        "--output-dir",
        default=f"~/Desktop/Claude/week-lit-review-results/{datetime.now().strftime('%Y-%m-%d')}",
        help="Output directory for manifest.json",
    )
    parser.add_argument(
        "--max-emails",
        type=int,
        default=1,
        help="Number of Stork emails to read (default: 1 = most recent)",
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=None,
        help="Cap total papers to process",
    )
    parser.add_argument(
        "--keywords",
        default="",
        help="Comma-separated keywords to filter papers (empty = keep all)",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Skip PDF/source download",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
