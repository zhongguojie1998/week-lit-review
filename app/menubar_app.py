#!/usr/bin/env python3
"""Lit-Review menu-bar app (macOS).

Phase 1 + 2: tray menu to fetch candidates, pick papers in a window, deep-review
the picks via Claude Code, plus a daily 12:00 auto-fetch with a "Review now"
notification.

Run (dev):  bash app/run_app.sh      (uses uv to provide rumps + pywebview)
Deps:       rumps, pywebview  (PyObjC pulled in transitively)
"""
from __future__ import annotations

import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import rumps

from paths import (
    ENGINE_LABELS,
    ENGINES,
    PYTHON,
    REPO_ROOT,
    RESULTS_DIR,
    REVIEWS_DIR,
    SOURCE_DIR,
    get_engine,
    manifest_path,
    set_engine,
    summary_path,
    today,
    today_dir,
)
import actions
import review_runner

CONTROL_PANEL = Path(__file__).resolve().parent / "control_panel.py"
NOON_HOUR = 12

# Set once the app is constructed; used by the module-level notification handler.
_APP: "LitReviewApp | None" = None


class LitReviewApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("📚", quit_button=None)
        self.busy = False
        self._last_auto_date = ""
        self._window_proc: "subprocess.Popen | None" = None
        self.status_item = rumps.MenuItem("Status: idle")

        # Review-engine selector (Claude Code / Codex) with checkmarks.
        engine_menu = rumps.MenuItem("Review engine")
        self.engine_items: dict[str, rumps.MenuItem] = {}
        for eng in ENGINES:
            item = rumps.MenuItem(ENGINE_LABELS[eng], callback=self._on_engine_click)
            self.engine_items[eng] = item
            engine_menu.add(item)

        self.menu = [
            "Open window",
            "Fetch now",
            "Open selection…",
            "Open today's summary",
            None,
            engine_menu,
            self.status_item,
            None,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]
        self._refresh_engine_checks()
        self._refresh_status()
        # Daily 12:00 check (robust to sleep/wake): tick every 60s.
        self._scheduler = rumps.Timer(self._tick, 60)
        self._scheduler.start()
        # Show the control-panel window on launch (the visible front-end).
        self._open_window()

    # ---- helpers -----------------------------------------------------------
    def _set_status(self, text: str) -> None:
        self.status_item.title = f"Status: {text}"

    def _refresh_status(self) -> None:
        n = actions.count_candidates()
        eng = ENGINE_LABELS.get(get_engine(), get_engine())
        when = actions.candidates_date() or today()
        base = f"{n} candidates (fetched {when})" if n else "no candidates yet"
        self._set_status(f"{base} · engine: {eng}")

    def _refresh_engine_checks(self) -> None:
        current = get_engine()
        for eng, item in self.engine_items.items():
            item.state = 1 if eng == current else 0

    def _on_engine_click(self, sender) -> None:
        label_to_eng = {v: k for k, v in ENGINE_LABELS.items()}
        eng = label_to_eng.get(sender.title)
        if eng:
            set_engine(eng)
            self._refresh_engine_checks()
            self._refresh_status()
            self._notify("Lit Review", "Review engine", f"Set to {ENGINE_LABELS[eng]}.")

    def _ensure_dirs(self) -> None:
        for d in (SOURCE_DIR, REVIEWS_DIR, today_dir()):
            d.mkdir(parents=True, exist_ok=True)

    def _notify(self, title: str, subtitle: str, message: str) -> None:
        try:
            rumps.notification(title, subtitle, message)
        except Exception:
            pass

    # ---- control-panel window ----------------------------------------------
    @rumps.clicked("Open window")
    def open_window(self, _=None) -> None:
        self._open_window()

    def _open_window(self) -> None:
        """Open the control-panel window (skip if one is already open)."""
        if self._window_proc is not None and self._window_proc.poll() is None:
            return
        try:
            self._window_proc = subprocess.Popen(
                [PYTHON, str(CONTROL_PANEL)], cwd=str(REPO_ROOT),
            )
        except Exception as exc:  # noqa: BLE001
            self._notify("Lit Review", "Could not open window", str(exc))

    # ---- fetch -------------------------------------------------------------
    @rumps.clicked("Fetch now")
    def fetch_now(self, _=None) -> None:
        self._start_fetch(open_after=False)

    def _start_fetch(self, open_after: bool) -> None:
        if self.busy:
            self._notify("Lit Review", "", "Busy — try again shortly.")
            return
        self.busy = True
        self._set_status("fetching candidates…")
        threading.Thread(target=self._fetch_worker, args=(open_after,), daemon=True).start()

    def _fetch_worker(self, open_after: bool) -> None:
        self._ensure_dirs()
        try:
            actions.fetch_candidates()
        except Exception as exc:  # noqa: BLE001
            self.busy = False
            self._set_status("fetch failed")
            self._notify("Lit Review", "Fetch failed", str(exc))
            return
        self.busy = False
        n = actions.count_candidates()
        self._refresh_status()
        self._notify("Lit Review", f"{n} papers ready", "Click to pick papers, or use Open selection.")
        if open_after:
            self._start_selection()

    # ---- selection ---------------------------------------------------------
    @rumps.clicked("Open selection…")
    def open_selection(self, _=None) -> None:
        if not manifest_path().exists():
            self._notify("Lit Review", "No candidates yet", "Fetching first…")
            self._start_fetch(open_after=True)
            return
        self._start_selection()

    def _start_selection(self) -> None:
        threading.Thread(target=self._selection_worker, daemon=True).start()

    def _selection_worker(self) -> None:
        try:
            dois = actions.run_selection()
        except Exception as exc:  # noqa: BLE001
            self._notify("Lit Review", "Selection error", str(exc))
            return

        if not dois:
            self._refresh_status()
            return
        self._start_review(dois)

    # ---- review ------------------------------------------------------------
    def _start_review(self, dois: list[str]) -> None:
        if self.busy:
            self._notify("Lit Review", "", "Busy — try again shortly.")
            return
        engine = get_engine()
        self.busy = True
        self._set_status(f"reviewing {len(dois)} paper(s) via {ENGINE_LABELS.get(engine, engine)}…")
        self._notify("Lit Review", f"Deep review started ({ENGINE_LABELS.get(engine, engine)})",
                     f"{len(dois)} paper(s). This can take a while.")
        threading.Thread(target=self._review_worker, args=(dois, engine), daemon=True).start()

    def _review_worker(self, dois: list[str], engine: str) -> None:
        try:
            res = review_runner.run_review(dois, engine=engine)
        except Exception as exc:  # noqa: BLE001
            self.busy = False
            self._set_status("review failed")
            self._notify("Lit Review", "Review failed", str(exc))
            return
        self.busy = False
        self._refresh_status()
        if res.reviewed and res.returncode != 0:
            self._notify("Lit Review", "Review finished with errors",
                         f"exit {res.returncode} — see logs.")
            return
        if res.summary.exists():
            self._notify("Lit Review", "Summary ready",
                         f"{len(res.reviewed)} reviewed, {len(res.skipped)} reused — opening summary…")
            webbrowser.open(res.summary.as_uri())
        else:
            self._notify("Lit Review", "Finished", "No summary written — see logs.")

    @rumps.clicked("Open today's summary")
    def open_summary(self, _=None) -> None:
        s = summary_path()
        if s.exists():
            webbrowser.open(s.as_uri())
        else:
            self._notify("Lit Review", "No summary yet", "Review some papers first.")

    # ---- daily schedule ----------------------------------------------------
    def _tick(self, _timer) -> None:
        now = datetime.now()
        if now.hour == NOON_HOUR and now.minute < 5 and self._last_auto_date != today():
            self._last_auto_date = today()
            self._start_fetch(open_after=False)

    # ---- notification click (invoked by module-level handler) --------------
    def handle_notification_click(self) -> None:
        if manifest_path().exists() and not self.busy:
            self._start_selection()


@rumps.notifications
def _notification_center(_info) -> None:
    if _APP is not None:
        _APP.handle_notification_click()


if __name__ == "__main__":
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _APP = LitReviewApp()
    _APP.run()
