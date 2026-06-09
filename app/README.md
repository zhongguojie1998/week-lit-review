# Lit-Review menu-bar app (macOS, personal)

A native menu-bar front-end for the `weekly-lit-review` pipeline. Fetch candidate
papers (titles/abstracts only), pick the ones worth reading in a clickable table,
and deep-review just those via Claude Code — no API key (uses your Claude Code
session through `claude -p … --plugin-dir <repo>`).

## How it fits the pipeline

```
fetch_papers.py --no-pdf  →  manifest.json  →  [selection table]  →  DOIs
   →  claude -p "/weekly-lit-review --doi …" --plugin-dir <repo>  →  reviews/*.html + summary.html
```

`--plugin-dir` points Claude at the **working tree**, so the app always runs the
current skill (it does not depend on the installed plugin cache).

## UI: control window + menu bar

Launching the app opens a **control-panel window** (the visible front-end) and leaves a
**📚 menu-bar icon** resident in the background. They're two processes — `rumps` (menu bar)
and `pywebview` (window) can't share one run-loop — but drive the same `actions.py` +
`review_runner.py`, so behaviour matches. Close the window and the menu-bar app keeps running
the daily 12:00 auto-fetch; reopen it from the menu's **Open window** item.

## Files
- `control_panel.py` + `control_panel.html` — the main window: *Fetch candidates*, *Select & review…*, *Open summary*, engine picker, live status/log. Opened on launch by the menu-bar app.
- `menubar_app.py` — resident tray app: *Open window*, *Fetch now*, *Open selection…*, *Open today's summary*; daily 12:00 auto-fetch + notification.
- `actions.py` — shared pipeline steps (fetch candidates, open the picker) used by both front-ends.
- `selection_ui.py` + `selection.html` — the picker window (sort, filter, hide-reviewed, checkboxes). Runs as its own process.
- `review_runner.py` — wraps the `claude -p … --doi …` call (mirrors `scripts/run_review.sh`).
- `paths.py` — repo/results paths + config reads.
- `run_app.sh` — bootstraps a framework-Python venv (`rumps` + `pywebview`) and runs the app.
- `build_app.sh` — builds the double-clickable `LitReview.app` wrapper; `--install` copies it to `/Applications` and adds a Login Item.
- `com.zhongguojie.litreview-app.plist` — legacy login-item LaunchAgent (retired by `build_app.sh --install`).

## Run

Build and install the clickable app (recommended):
```bash
bash app/build_app.sh --install
```
This creates `LitReview.app`, copies it to `/Applications`, and registers it as a hidden Login
Item (so it starts at login). Launch it now with `open -a LitReview` or by double-clicking
`/Applications/LitReview.app`. A 📚 icon appears in the menu bar. First launch may pause briefly
while `run_app.sh` builds the venv (silent — no terminal).

To build the bundle without installing, run `bash app/build_app.sh` (produces `app/LitReview.app`).

Dev/debug fallback (runs in the foreground with visible logs):
```bash
bash app/run_app.sh
```

## Review engine (Claude Code or Codex)

The deep review runs through a pluggable engine, chosen from the **Review engine** submenu
(persisted to `…/week-lit-review-results/.engine`) or the `review_engine` key in
`assets/config.yaml`:

- **Claude Code** (default) — `claude -p "/weekly-lit-review … --doi …" --plugin-dir <repo>`.
  Reads PDFs natively. No setup beyond Claude Code.
- **Codex** — `codex exec` run from the repo root with a prompt that tells Codex to read
  `skills/weekly-lit-review/SKILL.md` and follow DOI-Specific Review Mode. Requires the Codex
  CLI: `npm i -g @openai/codex` (or `brew install codex`). Set `codex_model` in config to pin a
  model (blank = Codex default).

Both engines share the same review logic (it lives in SKILL.md) and produce the same
`reviews/*.html` + `summary.html`.

> **Codex + PDFs:** Claude reads PDFs natively; Codex cannot, so its prompt instructs it to
> extract text (via `pymupdf`) before reviewing. Quality of PDF-based reviews may differ
> between engines.

## Auto-start at login

`bash app/build_app.sh --install` already adds `LitReview.app` as a hidden Login Item and
retires the legacy LaunchAgent (`~/Library/LaunchAgents/com.zhongguojie.litreview-app.plist`
→ `.retired`). The app owns the daily 12:00 schedule, so also retire the old prefetch job once:
```bash
launchctl unload ~/Library/LaunchAgents/com.zhongguojie.weekly-lit-review.plist 2>/dev/null
```

## Notes / limitations
- Hardcoded repo path: `run_app.sh` and the launcher inside `LitReview.app` embed the repo
  location. If you move the repo, re-run `bash app/build_app.sh --install`.
- `LitReview.app` is a thin wrapper that `exec`s `run_app.sh`, which in turn `exec`s the venv
  `python`. The running process image is therefore Python, so macOS attributes notifications to
  "Python" rather than "LitReview". Packaging with `py2app` (proper bundle id) is the upgrade
  path for native-attributed notifications.
- Papers without a DOI can't be deep-reviewed by DOI; the table disables their
  checkbox (the skill's interactive mode handles abstract-only fallback separately).
