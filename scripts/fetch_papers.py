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
                f"?category={requests.utils.quote(cat)}"
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
                            "corresponding_author": item.get("author_corresponding", ""),
                            "affiliation": item.get("author_corresponding_institution", ""),
                            "abstract": abstract,
                            "source": f"bioRxiv ({item_cat})",
                            "url": f"https://doi.org/{doi}",
                            "doi": doi,
                            "date": item.get("date", ""),
                            "pdf_url": f"https://www.biorxiv.org/content/{doi}v{version}.full.pdf",
                        })

            cursor += len(collection)
            if len(collection) < 100:
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
                    "corresponding_author": "",  # not exposed in RSS feeds
                    "affiliation": "",           # not exposed in RSS feeds
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
# Filters
# ---------------------------------------------------------------------------
def filter_non_research_articles(papers: list[dict], logger: logging.Logger) -> list[dict]:
    """Filter out corrections, errata, retractions, and other non-research content."""
    exclusion_patterns = [
        r'\bauthor correction\b',
        r'\bcorrection\b.*\b(to|for)\b',
        r'\berratum\b',
        r'\berrata\b',
        r'\bretraction\b',
        r'\bwithdrawal\b',
        r'\bexpression of concern\b',
        r'\bpublisher\s+correction\b',
        r'\bpublisher\s+note\b',
        r'\bcorrigendum\b',
        r'\badditional information\b.*\bcorrection\b',
    ]

    compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in exclusion_patterns]

    filtered = []
    excluded_count = 0
    for p in papers:
        title = p.get("title", "")
        # Check if title matches any exclusion pattern
        if any(pattern.search(title) for pattern in compiled_patterns):
            excluded_count += 1
            logger.debug(f"  Excluded: {title[:60]}...")
            continue
        filtered.append(p)

    if excluded_count > 0:
        logger.info(f"  Filtered out {excluded_count} correction/erratum articles")

    return filtered


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
def try_semantic_scholar_pdf(doi: str, title: str, timeout: int, logger: logging.Logger) -> Optional[str]:
    """Semantic Scholar: free API, returns openAccessPdf URL if available."""
    # Try DOI first, fall back to title search
    paper_id = f"DOI:{doi}" if doi else None
    if not paper_id and not title:
        return None
    try:
        if paper_id:
            url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=openAccessPdf"
        else:
            url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={requests.utils.quote(title[:200])}&limit=1&fields=openAccessPdf"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            # Search endpoint wraps results in "data" list
            if "data" in data and data["data"]:
                data = data["data"][0]
            oa_pdf = data.get("openAccessPdf") or {}
            pdf_url = oa_pdf.get("url")
            if pdf_url:
                # If URL points to a PMC/NCBI page, route through Europe PMC (no JS challenge)
                pmc_match = re.search(r'(PMC\d+)', pdf_url)
                if pmc_match and ("ncbi.nlm.nih.gov" in pdf_url or "europepmc.org" in pdf_url):
                    pdf_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmc_match.group(1)}&blobtype=pdf"
                # If URL points to bioRxiv (likely Cloudflare-blocked), skip it
                elif "biorxiv.org" in pdf_url:
                    logger.info(f"    Semantic Scholar: URL is bioRxiv (Cloudflare-blocked), skipping")
                    return None
                logger.info(f"    Semantic Scholar: found OA PDF")
            else:
                logger.info(f"    Semantic Scholar: no OA PDF available")
            return pdf_url
        elif resp.status_code == 404:
            logger.info(f"    Semantic Scholar: paper not found")
        elif resp.status_code == 429:
            logger.warning(f"    Semantic Scholar: rate limited")
        else:
            logger.warning(f"    Semantic Scholar: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"    Semantic Scholar: error: {e}")
    return None


def try_europepmc_pdf(doi: str, timeout: int, logger: logging.Logger) -> tuple[Optional[str], Optional[str]]:
    """Europe PMC: resolve DOI to PMCID via Europe PMC API, then serve PDF directly (no JS challenge).
    Returns (pdf_url, pmcid) or (None, None)."""
    if not doi:
        return None, None
    try:
        # Search Europe PMC by DOI
        search_url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query=DOI:{doi}&format=json&resultType=core"
        )
        resp = requests.get(search_url, timeout=timeout)
        if resp.status_code != 200:
            logger.info(f"    Europe PMC: search HTTP {resp.status_code}")
            return None, None

        data = resp.json()
        results = data.get("resultList", {}).get("result", [])
        pmcid = None
        for rec in results:
            pmcid = rec.get("pmcid")
            if pmcid:
                break
        if not pmcid:
            logger.info(f"    Europe PMC: no PMCID found for DOI {doi}")
            return None, None

        # Europe PMC serves PDFs directly without JS proof-of-work
        pdf_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"
        logger.info(f"    Europe PMC: found {pmcid}")
        return pdf_url, pmcid
    except Exception as e:
        logger.warning(f"    Europe PMC: error: {e}")
    return None, None


def try_core_pdf(doi: str, title: str, timeout: int, logger: logging.Logger) -> Optional[str]:
    """CORE API: free, rate-limited (10 req/10s), returns hosted PDF URL."""
    if not doi and not title:
        return None
    try:
        # CORE search by DOI or title
        query = doi if doi else title[:150]
        url = f"https://api.core.ac.uk/v3/search/works?q={requests.utils.quote(query)}&limit=1"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                download_url = results[0].get("downloadUrl")
                if download_url:
                    logger.info(f"    CORE: found PDF")
                    return download_url
                else:
                    logger.info(f"    CORE: paper found but no downloadUrl")
            else:
                logger.info(f"    CORE: no results")
        elif resp.status_code == 429:
            logger.warning(f"    CORE: rate limited")
        else:
            logger.warning(f"    CORE: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"    CORE: error: {e}")
    return None


def try_paperscraper_pdf(doi: str, pdf_path: Path, logger: logging.Logger) -> bool:
    """paperscraper: uses DOI to download PDF with its own fallback chain (BioC-PMC, eLife, etc.)."""
    if not doi:
        return False
    try:
        from paperscraper.pdf import save_pdf
    except ImportError:
        try:
            import subprocess
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "paperscraper", "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            from paperscraper.pdf import save_pdf
        except Exception as e:
            logger.warning(f"    paperscraper: failed to install: {e}")
            return False
    try:
        save_pdf({"doi": doi}, filepath=str(pdf_path))
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            logger.info(f"    paperscraper: PDF downloaded ({pdf_path.stat().st_size} bytes)")
            return True
        else:
            logger.info(f"    paperscraper: no PDF retrieved for DOI {doi}")
            # Clean up empty/tiny files
            if pdf_path.exists():
                pdf_path.unlink()
            return False
    except Exception as e:
        logger.warning(f"    paperscraper: error: {e}")
        if pdf_path.exists() and pdf_path.stat().st_size < 1000:
            pdf_path.unlink()
        return False


def try_biorxiv_api_format(doi: str, fmt: str, name: str, output_dir: Path, timeout: int, logger: logging.Logger) -> Optional[tuple]:
    """Fetch bioRxiv API response in 'json' or 'xml' format. Returns (path, ext) or None."""
    url = f"https://api.biorxiv.org/details/biorxiv/{doi}/na/{fmt}"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            if fmt == "json":
                data = resp.json().get("collection", [])
                if data:
                    path = output_dir / f"{name}.json"
                    path.write_text(json.dumps(data[0], indent=2))
                    logger.info(f"    bioRxiv API JSON: saved metadata ({path.stat().st_size} bytes)")
                    return str(path), "json"
            elif fmt == "xml":
                if len(resp.content) > 500:
                    path = output_dir / f"{name}.xml"
                    path.write_bytes(resp.content)
                    logger.info(f"    bioRxiv API XML: saved ({path.stat().st_size} bytes)")
                    return str(path), "xml"
    except Exception as e:
        logger.warning(f"    bioRxiv API {fmt}: error: {e}")
    return None


def try_europepmc_xml(pmcid: str, name: str, output_dir: Path, timeout: int, logger: logging.Logger) -> Optional[tuple]:
    """Fetch JATS XML for a PMC article. Returns (path, ext) or None."""
    url = (
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query=PMCID:{pmcid}&format=xml&resultType=full"
    )
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200 and len(resp.content) > 1000:
            path = output_dir / f"{name}.xml"
            path.write_bytes(resp.content)
            logger.info(f"    Europe PMC XML: saved ({path.stat().st_size} bytes)")
            return str(path), "xml"
    except Exception as e:
        logger.warning(f"    Europe PMC XML: error: {e}")
    return None


def try_fetch_text(paper_url: str, name: str, output_dir: Path, timeout: int, headers: dict, logger: logging.Logger) -> Optional[tuple]:
    """Fetch HTML from paper URL, strip tags, save as .txt. Returns (path, ext) or None."""
    if not paper_url:
        return None
    try:
        resp = requests.get(paper_url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 500:
                path = output_dir / f"{name}.txt"
                path.write_text(text[:500_000], encoding="utf-8", errors="ignore")
                logger.info(f"    HTML-to-text: saved ({path.stat().st_size} bytes)")
                return str(path), "txt"
    except Exception as e:
        logger.warning(f"    HTML-to-text: error: {e}")
    return None


_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def try_browser_pdf(doi: str, pdf_url_hint: str, source: str, pdf_path: Path,
                    timeout: int, logger: logging.Logger) -> bool:
    """Download a bioRxiv/medRxiv PDF via a real browser (Playwright + the system
    Chrome). bioRxiv fronts every request with a Cloudflare challenge that blocks
    plain HTTP (and cloudscraper/paperscraper), but a real browser clears it.
    Uses channel="chrome" so no Chromium download is needed. Returns True on success.
    """
    if not doi:
        return False
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        import subprocess
        installed = False
        for extra in ([], ["--user"], ["--break-system-packages"]):
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "-q", "playwright", *extra],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                installed = True
                break
            except Exception:
                continue
        if not installed:
            logger.warning("    browser-pdf: playwright not available and install failed")
            return False
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            logger.warning(f"    browser-pdf: playwright import failed: {e}")
            return False

    host = "www.medrxiv.org" if ("medrxiv" in (source or "").lower()
                                 or "medrxiv" in (pdf_url_hint or "").lower()) else "www.biorxiv.org"
    versions: list[str] = []
    m = re.search(r"v(\d+)", pdf_url_hint or "")
    if m:
        versions.append(f"v{m.group(1)}")
    for v in ("v1", "v2", "v3"):
        if v not in versions:
            versions.append(v)

    ms = max(timeout, 60) * 1000

    def _cleared(page, ctx) -> bool:
        """Cloudflare challenge solved? The cf_clearance cookie is the reliable
        signal; fall back to the page title no longer being a challenge page."""
        try:
            if any(c.get("name") == "cf_clearance" for c in ctx.cookies()):
                return True
        except Exception:  # noqa: BLE001
            pass
        t = (page.title() or "").lower()
        return bool(t) and "just a moment" not in t and "attention required" not in t

    try:
        with sync_playwright() as p:
            try:
                # --disable-blink-features=AutomationControlled lowers the chance
                # Cloudflare flags the headless browser and serves an unsolvable loop.
                browser = p.chromium.launch(
                    channel="chrome", headless=True,
                    args=["--disable-blink-features=AutomationControlled"])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"    browser-pdf: chrome launch failed ({repr(e)[:80]})")
                return False
            try:
                ctx = browser.new_context(accept_downloads=True, user_agent=_BROWSER_UA)
                page = ctx.new_page()
                # Fetch the PDF from *inside* the page (same-origin fetch carries the
                # full browser fingerprint + cf_clearance cookie). A lightweight
                # APIRequestContext.get() gets re-challenged by Cloudflare; in-page
                # fetch does not, once the article page has cleared the challenge.
                fetch_js = """async (url) => {
                    const r = await fetch(url, {credentials: 'include'});
                    if (!r.ok) return {ok: false, status: r.status};
                    const buf = await r.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let bin = '';
                    const CHUNK = 0x8000;
                    for (let i = 0; i < bytes.length; i += CHUNK) {
                        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
                    }
                    return {ok: true, status: r.status, b64: btoa(bin)};
                }"""
                import base64
                for v in versions:
                    art = f"https://{host}/content/{doi}{v}"
                    try:
                        # Up to 2 navigations: a transient challenge sometimes clears
                        # only on a reload. Don't gate on goto status — the challenge
                        # page returns 403 first, then the browser clears it.
                        cleared = False
                        for attempt in range(2):
                            page.goto(art, wait_until="domcontentloaded", timeout=ms)
                            for _ in range(40):  # wait up to ~40s for Cloudflare
                                if _cleared(page, ctx):
                                    cleared = True
                                    break
                                page.wait_for_timeout(1000)
                            if cleared:
                                break
                        res = page.evaluate(fetch_js, art + ".full.pdf")
                        if res and res.get("ok") and res.get("b64"):
                            body = base64.b64decode(res["b64"])
                            if body[:5] == b"%PDF-" and len(body) > 1000:
                                pdf_path.write_bytes(body)
                                logger.info(f"    browser-pdf: downloaded {len(body)} bytes from {art}.full.pdf")
                                return True
                        logger.info(f"    browser-pdf: {v} no PDF "
                                    f"({(res or {}).get('status')}, cleared={cleared})")
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"    browser-pdf: {v} error {repr(e)[:80]}")
                        continue
                return False
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"    browser-pdf: error {repr(e)[:120]}")
        return False


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


# Unpaywall just needs a contact email (any well-formed address); override in config.
_UNPAYWALL_EMAIL = "weekly-lit-review@users.noreply.github.com"


def try_unpaywall_pdf(doi: str, timeout: int, logger: logging.Logger) -> Optional[str]:
    """Find an open-access PDF URL for the DOI via Unpaywall. Returns a URL or None.

    Unpaywall indexes legal OA copies across publishers/repositories; many sit on
    hosts reachable by plain HTTP (unlike Cloudflare-fronted bioRxiv).
    """
    if not doi:
        return None
    try:
        resp = requests.get(f"https://api.unpaywall.org/v2/{doi}",
                            params={"email": _UNPAYWALL_EMAIL}, timeout=timeout)
        if resp.status_code != 200:
            logger.info(f"    Unpaywall: HTTP {resp.status_code}")
            return None
        data = resp.json()
        candidates = [data.get("best_oa_location") or {}]
        candidates += data.get("oa_locations", []) or []
        for loc in candidates:
            url = (loc or {}).get("url_for_pdf")
            if url:
                logger.info("    Unpaywall: OA PDF found")
                return url
        logger.info("    Unpaywall: no OA PDF")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"    Unpaywall error: {repr(e)[:80]}")
    return None


def download_source(paper: dict, output_dir: Path, timeout: int, logger: logging.Logger) -> tuple[Optional[str], Optional[str]]:
    """Download paper in any available format. Returns (file_path, format_ext) or (None, None)."""
    safe_name = _make_descriptive_name(paper)
    title_short = paper['title'][:60]

    # Skip if any format already exists
    for ext in (".pdf", ".json", ".xml", ".txt"):
        existing = output_dir / f"{safe_name}{ext}"
        if existing.exists() and existing.stat().st_size > 1000:
            logger.info(f"    Already have source file ({ext[1:]}): {title_short}...")
            return str(existing), ext[1:]

    doi = paper.get("doi", "")
    title = paper.get("title", "")
    paper_url = paper.get("url", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/pdf,text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    pdf_path = output_dir / f"{safe_name}.pdf"

    def _try_download_pdf(source: str, url: str) -> bool:
        """Attempt to download a PDF from url. Returns True on success."""
        try:
            logger.info(f"    Trying {source}: {url[:100]}...")
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            content_type = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and (
                "pdf" in content_type.lower() or resp.content[:5] == b"%PDF-"
            ):
                pdf_path.write_bytes(resp.content)
                logger.info(f"    PDF downloaded ({source}): {title_short}... ({len(resp.content)} bytes)")
                return True
            else:
                logger.warning(
                    f"    Failed ({source}): HTTP {resp.status_code}, "
                    f"Content-Type={content_type}, body={len(resp.content)} bytes"
                )
        except Exception as e:
            logger.warning(f"    Failed ({source}): {e}")
        return False

    src_l = paper.get("source", "").lower()
    url_l = paper_url.lower()
    is_biorxiv = (
        doi.startswith("10.1101") or doi.startswith("10.64898")
        or "biorxiv" in src_l or "medrxiv" in src_l
        or "biorxiv.org" in url_l or "medrxiv.org" in url_l
    )

    if is_biorxiv:
        # bioRxiv cascade. Prefer the FULL PDF; only fall back to abstract-only
        # API metadata as a last resort (otherwise reviews silently degrade).

        # Source 1: Direct PDF URL (cheap; usually Cloudflare-blocked but worth a shot)
        if paper.get("pdf_url"):
            if _try_download_pdf("direct", paper["pdf_url"]):
                return str(pdf_path), "pdf"
        else:
            logger.info(f"    No direct pdf_url for: {title_short}...")

        # Source 2: Real browser (Playwright + Chrome) — clears Cloudflare, gets the PDF
        if try_browser_pdf(doi, paper.get("pdf_url", ""), paper.get("source", ""),
                           pdf_path, timeout, logger):
            return str(pdf_path), "pdf"

        # Source 3: paperscraper
        if try_paperscraper_pdf(doi, pdf_path, logger):
            return str(pdf_path), "pdf"

        # Source 4: Semantic Scholar
        s2_url = try_semantic_scholar_pdf(doi, title, timeout, logger)
        if s2_url and _try_download_pdf("semantic-scholar", s2_url):
            return str(pdf_path), "pdf"

        # Source 5: Europe PMC
        europepmc_url, _ = try_europepmc_pdf(doi, timeout, logger)
        if europepmc_url and _try_download_pdf("europe-pmc", europepmc_url):
            return str(pdf_path), "pdf"

        # Source 6: CORE
        core_url = try_core_pdf(doi, title, timeout, logger)
        if core_url and _try_download_pdf("core", core_url):
            return str(pdf_path), "pdf"

        # Source 7: Unpaywall (a non-Cloudflare OA mirror may exist)
        unpaywall_url = try_unpaywall_pdf(doi, timeout, logger)
        if unpaywall_url and _try_download_pdf("unpaywall", unpaywall_url):
            return str(pdf_path), "pdf"

        # --- abstract-only fallbacks (only if no full text could be retrieved) ---

        # Source 7: bioRxiv API JSON metadata (abstract only)
        if doi:
            result = try_biorxiv_api_format(doi, "json", safe_name, output_dir, timeout, logger)
            if result:
                return result

        # Source 8: bioRxiv API XML
        if doi:
            result = try_biorxiv_api_format(doi, "xml", safe_name, output_dir, timeout, logger)
            if result:
                return result

        # Source 9: HTML-to-text fallback
        result = try_fetch_text(paper_url, safe_name, output_dir, timeout, headers, logger)
        if result:
            return result

    else:
        # Non-bioRxiv cascade

        # Source 1: Direct PDF URL if provided
        if paper.get("pdf_url"):
            if _try_download_pdf("direct", paper["pdf_url"]):
                return str(pdf_path), "pdf"
        else:
            logger.info(f"    No direct pdf_url for: {title_short}...")

        # Source 2: paperscraper
        if try_paperscraper_pdf(doi, pdf_path, logger):
            return str(pdf_path), "pdf"

        # Source 3: Semantic Scholar
        s2_url = try_semantic_scholar_pdf(doi, title, timeout, logger)
        if s2_url and _try_download_pdf("semantic-scholar", s2_url):
            return str(pdf_path), "pdf"

        # Source 4: Unpaywall OA PDF (broad cross-publisher coverage)
        unpaywall_url = try_unpaywall_pdf(doi, timeout, logger)
        if unpaywall_url and _try_download_pdf("unpaywall", unpaywall_url):
            return str(pdf_path), "pdf"

        # Source 5: Europe PMC PDF (and save PMCID for XML fallback)
        europepmc_url, pmcid = try_europepmc_pdf(doi, timeout, logger)
        if europepmc_url and _try_download_pdf("europe-pmc", europepmc_url):
            return str(pdf_path), "pdf"

        # Source 6: Europe PMC JATS XML (reuse PMCID from step 5)
        if pmcid:
            result = try_europepmc_xml(pmcid, safe_name, output_dir, timeout, logger)
            if result:
                return result

        # Source 7: CORE
        core_url = try_core_pdf(doi, title, timeout, logger)
        if core_url and _try_download_pdf("core", core_url):
            return str(pdf_path), "pdf"

        # Source 8: HTML-to-text fallback
        result = try_fetch_text(paper_url, safe_name, output_dir, timeout, headers, logger)
        if result:
            return result

    logger.warning(f"    All sources exhausted for: {title_short}...")
    return None, None


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
    # Source files go to a shared folder alongside the date-stamped output dir
    source_dir = output_dir.parent / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

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

    # Step 2: Filter out corrections/errata
    logger.info("\nStep 2: Filtering out corrections and errata...")
    all_papers = filter_non_research_articles(all_papers, logger)

    # Step 3: Filter to genomics
    logger.info("\nStep 3: Filtering to genomics...")
    genomics = filter_genomics(all_papers, cfg["genomics_keywords"])
    logger.info(f"  Filtered {len(all_papers)} -> {len(genomics)} genomics papers")

    max_eval = cfg.get("max_papers_to_evaluate", 30)
    if len(genomics) > max_eval:
        logger.info(f"  Capping at {max_eval} papers")
        genomics = genomics[:max_eval]

    if not genomics:
        logger.warning("  No genomics papers found. Exiting.")
        manifest = {"papers": [], "source_dir": str(source_dir), "date": datetime.now().strftime("%Y-%m-%d")}
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"\nMANIFEST: {manifest_path}")
        return

    # Step 4: Download source files
    if cfg.get("download_pdfs", True):
        logger.info("\nStep 4: Downloading source files...")
        timeout = cfg.get("pdf_timeout", 30)
        for i, paper in enumerate(genomics):
            logger.info(f"  [{i+1}/{len(genomics)}] {paper['title'][:60]}...")
            source_path, source_format = download_source(paper, source_dir, timeout, logger)
            paper["source_path"] = source_path or ""
            paper["source_format"] = source_format or ""
            if source_format == "pdf":
                paper["review_mode"] = "pdf"
            elif source_format in ("json", "xml", "txt"):
                paper["review_mode"] = "text"
            else:
                paper["review_mode"] = "abstract"
            time.sleep(0.3)

        source_count = sum(1 for p in genomics if p.get("source_path"))
        logger.info(f"  Downloaded {source_count}/{len(genomics)} source files")
    else:
        logger.info("\nStep 4: Skipping source file download (--no-pdf)")
        for p in genomics:
            p["source_path"] = ""
            p["source_format"] = ""
            p["review_mode"] = "abstract"

    # Step 5: Write manifest
    manifest = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "days_lookback": cfg["days_lookback"],
        "source_dir": str(source_dir),
        "total_fetched": len(all_papers),
        "total_genomics": len(genomics),
        "total_sources": sum(1 for p in genomics if p.get("source_path")),
        "papers": genomics,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    logger.info("\n" + "=" * 60)
    logger.info("FETCH COMPLETE")
    logger.info(f"  Papers: {len(genomics)}")
    logger.info(f"  Source files: {manifest['total_sources']}")
    logger.info(f"  Manifest: {manifest_path}")
    logger.info("=" * 60)

    # Print the manifest path on its own line for easy parsing
    print(f"\nMANIFEST: {manifest_path}")


# ---------------------------------------------------------------------------
# DOI-Specific Mode
# ---------------------------------------------------------------------------
def fetch_paper_by_doi(doi: str, logger: logging.Logger) -> Optional[dict]:
    """Fetch paper metadata from DOI using Semantic Scholar API."""
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,authors,abstract,year,venue,externalIds,openAccessPdf"
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            data = resp.json()

            # Extract authors
            authors_list = data.get("authors", [])
            authors = "; ".join([f"{a.get('name', '')}" for a in authors_list if a.get('name')])

            # Extract publication date
            year = data.get("year", "")
            pub_date = f"{year}-01-01" if year else datetime.now().strftime("%Y-%m-%d")

            # Extract source/venue
            venue = data.get("venue", "Unknown")

            # Extract OpenAccess PDF URL
            oa_pdf = data.get("openAccessPdf") or {}
            pdf_url = oa_pdf.get("url", "")

            paper = {
                "uid": hashlib.md5(doi.encode()).hexdigest()[:12],
                "title": data.get("title", ""),
                "authors": authors,
                "abstract": data.get("abstract", ""),
                "source": venue,
                "url": f"https://doi.org/{doi}",
                "doi": doi,
                "date": pub_date,
                "pdf_url": pdf_url,
            }

            logger.info(f"  Fetched metadata for DOI: {doi}")
            return paper
        elif resp.status_code == 404:
            logger.warning(f"  DOI not found in Semantic Scholar: {doi}")
        else:
            logger.warning(f"  Semantic Scholar HTTP {resp.status_code} for DOI: {doi}")
    except Exception as e:
        logger.warning(f"  Error fetching DOI {doi}: {e}")
    return None


def run_doi_mode(cfg: dict, dois: list[str]):
    """Process specific DOIs instead of batch fetching."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("fetch-papers-doi")

    output_dir = Path(cfg.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir.parent / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("FETCH & DOWNLOAD — DOI-Specific Mode")
    logger.info("=" * 60)
    logger.info(f"  Processing {len(dois)} DOI(s)")

    # Step 1: Fetch metadata for each DOI
    logger.info("\nStep 1: Fetching paper metadata from Semantic Scholar...")
    papers = []
    for doi in dois:
        paper = fetch_paper_by_doi(doi, logger)
        if paper:
            papers.append(paper)
        time.sleep(0.5)  # Rate limiting

    if not papers:
        logger.error("  No papers could be fetched. Exiting.")
        return

    logger.info(f"  Successfully fetched {len(papers)}/{len(dois)} papers")

    # Step 2: Extract genomics keywords
    logger.info("\nStep 2: Extracting genomics keywords...")
    genomics_keywords = cfg.get("genomics_keywords", [])
    for paper in papers:
        text = f"{paper['title']} {paper['abstract']}".lower()
        matched = [kw for kw in genomics_keywords if kw.lower() in text]
        paper["matched_keywords"] = matched if matched else ["genomics"]
        logger.info(f"  {paper['title'][:50]}... -> keywords: {', '.join(paper['matched_keywords'][:4])}")

    # Step 3: Download source files
    if cfg.get("download_pdfs", True):
        logger.info("\nStep 3: Downloading source files...")
        timeout = cfg.get("pdf_timeout", 30)
        for i, paper in enumerate(papers):
            logger.info(f"  [{i+1}/{len(papers)}] {paper['title'][:60]}...")
            source_path, source_format = download_source(paper, source_dir, timeout, logger)
            paper["source_path"] = source_path or ""
            paper["source_format"] = source_format or ""
            if source_format == "pdf":
                paper["review_mode"] = "pdf"
            elif source_format in ("json", "xml", "txt"):
                paper["review_mode"] = "text"
            else:
                paper["review_mode"] = "abstract"
            time.sleep(0.3)

        source_count = sum(1 for p in papers if p.get("source_path"))
        logger.info(f"  Downloaded {source_count}/{len(papers)} source files")
    else:
        logger.info("\nStep 3: Skipping source file download (--no-pdf)")
        for p in papers:
            p["source_path"] = ""
            p["source_format"] = ""
            p["review_mode"] = "abstract"

    # Step 4: Write manifest
    manifest = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mode": "doi-specific",
        "dois": dois,
        "source_dir": str(source_dir),
        "total_fetched": len(papers),
        "total_sources": sum(1 for p in papers if p.get("source_path")),
        "papers": papers,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    logger.info("\n" + "=" * 60)
    logger.info("DOI FETCH COMPLETE")
    logger.info(f"  Papers: {len(papers)}")
    logger.info(f"  Source files: {manifest['total_sources']}")
    logger.info(f"  Manifest: {manifest_path}")
    logger.info("=" * 60)

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
    parser.add_argument("--doi", action="append", help="DOI(s) to fetch and review (can specify multiple times)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.days:
        cfg["days_lookback"] = args.days
    if args.max_papers:
        cfg["max_papers_to_evaluate"] = args.max_papers
    if args.no_pdf:
        cfg["download_pdfs"] = False
    cfg["output_dir"] = str(Path(args.output_dir).expanduser())

    # If DOIs provided, run DOI-specific mode
    if args.doi:
        run_doi_mode(cfg, args.doi)
    else:
        run(cfg)


if __name__ == "__main__":
    main()
