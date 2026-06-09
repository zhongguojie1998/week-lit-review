"""Deep-review selected papers via a pluggable agent engine.

Two engines are supported (selectable from the app menu / config `review_engine`):

- "claude"  → Claude Code headless: `claude -p "/weekly-lit-review … --doi …"
              --plugin-dir <repo>`. Mirrors scripts/run_review.sh:76-82. --plugin-dir
              loads the skill from the working tree (bypasses the installed cache).
- "codex"   → OpenAI Codex CLI: `codex exec <prompt>` run from the repo root. Codex has
              no plugin/skill, so the prompt tells it to read the repo's SKILL.md and
              follow the DOI-Specific Review Mode for the given DOIs.

Both produce the same artifacts (reviews/*.html + summary.html). The review logic lives
in SKILL.md so both engines stay in sync.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

import json

import actions
from paths import (
    ALLOWED_TOOLS,
    ENGINES,
    PLUGIN_SKILL,
    PYTHON,
    REPO_ROOT,
    REVIEWS_DIR,
    SCRIPTS_DIR,
    SKILL_PATH,
    SOURCE_DIR,
    VENV_PYTHON,
    config_codex_model,
    config_model,
    get_engine,
    summary_path,
    today,
    today_dir,
)

RENDER_SUMMARY = SCRIPTS_DIR / "render_summary.py"


class ReviewResult(NamedTuple):
    returncode: int                       # engine exit code (0 if nothing was run)
    summary: Path                         # today's summary.html (may not exist)
    log: Optional[Path]                   # engine log (None if nothing was run)
    reviewed: list[str]                   # DOIs actually sent to the engine
    skipped: list[tuple[str, Path]]       # (doi, existing review) skipped as already-reviewed


def _ensure_dirs() -> None:
    for d in (SOURCE_DIR, REVIEWS_DIR, today_dir()):
        d.mkdir(parents=True, exist_ok=True)


def _build_run_summary(skipped: list[tuple[str, Path]]) -> None:
    """(Re)build today's summary over ALL selected papers (new + reused). Pure Python.

    render_review.py records freshly-rendered stems in <today>/_index.json; here we add
    the already-reviewed papers' stems and run render_summary.py, which reads each
    reviews/{stem}.json sidecar. This guarantees the summary covers every selected paper,
    not just the ones reviewed this run.
    """
    index_path = today_dir() / "_index.json"
    try:
        stems = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(stems, list):
            stems = []
    except (OSError, ValueError):
        stems = []
    for _, path in skipped:
        if path.stem not in stems:
            stems.append(path.stem)
    if not stems:
        return
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(stems, indent=2), encoding="utf-8")
    subprocess.run([PYTHON, str(RENDER_SUMMARY), "--date", today()],
                   cwd=str(REPO_ROOT), stdout=subprocess.DEVNULL,
                   stderr=subprocess.STDOUT, text=True)


def _augmented_env() -> dict[str, str]:
    """Env with a PATH that includes where the agent CLIs + node + venv live.

    The app launches with a minimal PATH, but `claude`/`codex` (`~/.local/bin`),
    node (nvm), and the app venv sit outside it. Prepend them so the engine binary
    resolves and the skill's `python3 fetch_papers.py` runs the venv interpreter
    (which has playwright for the browser-based bioRxiv PDF download).
    """
    home = os.path.expanduser("~")
    extra = [f"{home}/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    node_bins = sorted(glob.glob(f"{home}/.nvm/versions/node/*/bin"))
    if node_bins:
        extra.insert(1, node_bins[-1])  # newest installed node
    venv_bin = VENV_PYTHON.parent
    if venv_bin.is_dir():
        extra.insert(0, str(venv_bin))
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def _resolve_bin(name: str, env: dict[str, str]) -> str:
    found = shutil.which(name, path=env["PATH"])
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / name
    if fallback.exists():
        return str(fallback)
    hint = {
        "claude": "Install Claude Code (https://claude.com/claude-code).",
        "codex": "Install Codex: `npm i -g @openai/codex` or `brew install codex`.",
    }.get(name, "")
    raise FileNotFoundError(f"Could not find the `{name}` CLI on PATH. {hint}")


def _python_for_skill() -> str:
    """Python the engine should use for fetch_papers.py (venv has playwright)."""
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"


def _codex_prompt(dois: Sequence[str]) -> str:
    """Engine-neutral instructions for Codex (which has no skill/plugin)."""
    py = _python_for_skill()
    doi_list = " ".join(dois)
    skill_rel = SKILL_PATH.relative_to(REPO_ROOT)
    ref_dir = skill_rel.parent / "references"
    return (
        "You are running a genomics literature DEEP-REVIEW in this repository.\n\n"
        f"1. Read `{skill_rel}` (a small router), then read and follow "
        f"`{ref_dir}/mode-doi.md` and the shared `{ref_dir}/review-and-score.md` EXACTLY.\n"
        "2. Wherever the files say `${CLAUDE_PLUGIN_ROOT}`, use this repo root "
        "(your current working directory): e.g. `scripts/fetch_papers.py`, "
        "`assets/config.yaml`, `scripts/render_review.py`.\n"
        f"3. Run the fetch script with this interpreter so the browser-based PDF "
        f"download works: `{py} scripts/fetch_papers.py --config assets/config.yaml "
        "--output-dir ~/Desktop/Claude/week-lit-review-results/$(date +%Y-%m-%d) "
        f"--doi {doi_list}` (one --doi per DOI).\n"
        "4. If a downloaded source is a PDF, extract its text before reviewing "
        f"(e.g. `{py} -c \"import pymupdf,sys; print(chr(10).join(p.get_text() "
        "for p in pymupdf.open(sys.argv[1])))\" <file.pdf>`; pip install pymupdf if "
        "needed). Claude reads PDFs natively but you must extract text.\n"
        f"5. DOIs to review: {doi_list}\n"
        "6. Write reviews/summary by emitting compact JSON and running "
        f"`{py} scripts/render_review.py` / `scripts/render_summary.py` as described in "
        "review-and-score.md. Do NOT write HTML by hand.\n"
    )


def build_command(dois: Sequence[str], engine: str, model: Optional[str] = None) -> list[str]:
    """Construct the agent argv for `engine` to deep-review the given DOIs."""
    if engine == "claude":
        doi_args = " ".join(f"--doi {d}" for d in dois)
        prompt = f"{PLUGIN_SKILL} {doi_args}".strip()
        return [
            "claude", "-p", prompt,
            "--model", model or config_model(),
            "--plugin-dir", str(REPO_ROOT),
            "--allowedTools", ALLOWED_TOOLS,
            "--output-format", "text",
        ]
    if engine == "codex":
        # `codex exec` runs non-interactively. Bypass approvals + sandbox so it can
        # run python and write into ~/Desktop/... (outside the repo workspace).
        cmd = ["codex", "exec", "--cd", str(REPO_ROOT),
               "--dangerously-bypass-approvals-and-sandbox"]
        m = model or config_codex_model()
        if m:  # omit so Codex uses its own default when unset
            cmd += ["--model", m]
        cmd.append(_codex_prompt(dois))
        return cmd
    raise ValueError(f"Unknown engine: {engine!r} (expected one of {ENGINES})")


def run_review(dois: Sequence[str], engine: Optional[str] = None,
               model: Optional[str] = None) -> ReviewResult:
    """Run the deep review for `dois` with the chosen engine.

    Already-reviewed papers (a matching review HTML in any date folder) are skipped
    up front, so the engine is only invoked for genuinely new DOIs. Output is tee'd
    to a timestamped log under today's results dir. Blocking — call from a thread.
    """
    dois = [d for d in dois if d]
    if not dois:
        raise ValueError("No DOIs provided for review.")
    engine = (engine or get_engine()).lower()
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine: {engine!r}")
    _ensure_dirs()

    to_review, skipped = actions.partition_reviewed(list(dois))

    rc, log_path = 0, None
    if to_review:  # only invoke the engine for genuinely new papers
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        log_path = today_dir() / f"app_review_{engine}_{stamp}.log"
        env = _augmented_env()
        cmd = build_command(to_review, engine, model)
        cmd[0] = _resolve_bin(cmd[0], env)  # absolute path to claude/codex

        with log_path.open("w", encoding="utf-8") as log:
            if skipped:
                log.write("[reusing stored reviews] "
                          + ", ".join(d for d, _ in skipped) + "\n")
            log.write(f"[engine={engine}]\n$ {' '.join(cmd)}\n\n")
            log.flush()
            proc = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
        rc = proc.returncode

    # Build the run summary over ALL selected papers (newly reviewed + reused).
    _build_run_summary(skipped)
    return ReviewResult(rc, summary_path(), log_path, to_review, skipped)
