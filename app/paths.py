"""Single source of paths and config values for the menu-bar app.

All other app modules import from here so the repo location is computed once.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

# app/ lives directly under the repo root.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SCRIPTS_DIR: Path = REPO_ROOT / "scripts"
CONFIG_PATH: Path = REPO_ROOT / "assets" / "config.yaml"
FETCH_SCRIPT: Path = SCRIPTS_DIR / "fetch_papers.py"

RESULTS_DIR: Path = Path.home() / "Desktop" / "Claude" / "week-lit-review-results"
REVIEWS_DIR: Path = RESULTS_DIR / "reviews"
SOURCE_DIR: Path = RESULTS_DIR / "source"
# Candidate papers persist here (stable across launches/days), separate from the
# per-date review manifest the DOI flow overwrites. Parent is RESULTS_DIR so
# fetch_papers.py still resolves its source/ dir to RESULTS_DIR/source.
CANDIDATES_DIR: Path = RESULTS_DIR / "candidates"

SKILL_PATH: Path = REPO_ROOT / "skills" / "weekly-lit-review" / "SKILL.md"
# Where the app persists the user's chosen review engine.
ENGINE_STATE: Path = RESULTS_DIR / ".engine"

# Interpreter used to spawn child scripts (fetch, selection window).
PYTHON: str = sys.executable
# Venv python (has playwright/requests) — preferred for child fetch scripts.
VENV_PYTHON: Path = REPO_ROOT / "app" / ".venv" / "bin" / "python"

PLUGIN_SKILL: str = "/weekly-lit-review:weekly-lit-review"
ALLOWED_TOOLS: str = "Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch"

# Supported review engines.
ENGINES: tuple[str, ...] = ("claude", "codex")
ENGINE_LABELS: dict[str, str] = {"claude": "Claude Code", "codex": "Codex"}


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def today_dir() -> Path:
    return RESULTS_DIR / today()


def manifest_path() -> Path:
    """The app's persistent candidate manifest (reused across launches)."""
    return CANDIDATES_DIR / "manifest.json"


def summary_path() -> Path:
    return today_dir() / "summary.html"


def _read_config_scalar(key: str, default: str) -> str:
    """Minimal YAML scalar read (mirrors run_review.sh's grep+awk approach)."""
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return default
    m = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    if not m:
        return default
    return m.group(1).strip().strip('"').strip("'") or default


def config_model() -> str:
    return _read_config_scalar("claude_code_model", "sonnet")


def config_codex_model() -> str:
    """Codex model from config; empty string means 'use Codex's own default'."""
    return _read_config_scalar("codex_model", "")


def config_review_engine() -> str:
    eng = _read_config_scalar("review_engine", "claude").lower()
    return eng if eng in ENGINES else "claude"


def get_engine() -> str:
    """Selected engine: the app's persisted choice, else the config default."""
    try:
        eng = ENGINE_STATE.read_text(encoding="utf-8").strip().lower()
        if eng in ENGINES:
            return eng
    except OSError:
        pass
    return config_review_engine()


def set_engine(engine: str) -> None:
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine: {engine}")
    ENGINE_STATE.parent.mkdir(parents=True, exist_ok=True)
    ENGINE_STATE.write_text(engine, encoding="utf-8")
