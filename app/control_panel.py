"""Lit-Review control-panel window (pywebview, runs as its own process).

A visible window with Fetch / Select & Review / Open-summary buttons and an
engine picker. The resident menu-bar app (menubar_app.py) opens this on launch;
it is self-contained (drives the same actions.py + review_runner.py the menu
uses), so the two front-ends share behaviour but not a process run-loop
(rumps and pywebview can't share one).

Usage:  python3 control_panel.py
"""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from pathlib import Path

import webview  # pywebview

import actions
import review_runner
from paths import (
    ENGINE_LABELS,
    ENGINES,
    get_engine,
    manifest_path,
    set_engine,
    summary_path,
    today,
)

HTML_PATH = Path(__file__).resolve().parent / "control_panel.html"


def _log_tail(path: "Path | None", n: int = 12) -> str:
    if not path:
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


class Api:
    def __init__(self) -> None:
        self.window = None
        self.busy = False

    # ---- pushing state to the window --------------------------------------
    def _push(self, **state) -> None:
        if self.window is None:
            return
        try:
            self.window.evaluate_js(f"pushStatus({json.dumps(state)})")
        except Exception:
            pass

    def _engines(self) -> list[dict]:
        cur = get_engine()
        return [{"id": e, "label": ENGINE_LABELS.get(e, e), "selected": e == cur}
                for e in ENGINES]

    def _meta(self) -> str:
        n = actions.count_candidates()
        eng = ENGINE_LABELS.get(get_engine(), get_engine())
        when = actions.candidates_date() or today()
        base = f"<span class='stat'>{n}</span> candidates (fetched {when})" if n \
            else "no candidates yet — click <b>Fetch</b>"
        return f"{base} &middot; engine: <b>{eng}</b>"

    # ---- called from JS ---------------------------------------------------
    def get_state(self) -> dict:
        return {"text": "idle", "kind": "", "busy": False,
                "meta": self._meta(), "engines": self._engines()}

    def set_engine(self, engine: str) -> None:
        try:
            set_engine(engine)
        except ValueError:
            return
        self._push(text=f"engine set to {ENGINE_LABELS.get(engine, engine)}",
                   meta=self._meta(), engines=self._engines())

    def fetch(self) -> None:
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self) -> None:
        self._push(text="fetching candidates…", kind="busy", busy=True,
                   log="Fetching candidate papers (abstracts only)…")
        try:
            rc, log = actions.fetch_candidates()
        except Exception as exc:  # noqa: BLE001
            self.busy = False
            self._push(text="fetch failed", kind="err", busy=False, log=f"ERROR: {exc}")
            return
        self.busy = False
        n = actions.count_candidates()
        ok = rc == 0
        self._push(text=f"{n} candidates ready" if ok else f"fetch exited {rc}",
                   kind="ok" if ok else "err", busy=False, meta=self._meta(),
                   log=f"Done — {n} candidates. Log: {log.name}")

    def select_and_review(self) -> None:
        if self.busy:
            return
        if not manifest_path().exists():
            self._push(text="no candidates — fetching first…", kind="busy", busy=True,
                       log="No manifest yet; fetching candidates first…")
            threading.Thread(target=self._fetch_then_review, daemon=True).start()
            return
        self.busy = True
        threading.Thread(target=self._review_worker, daemon=True).start()

    def _fetch_then_review(self) -> None:
        self.busy = True
        self._fetch_worker_inner()
        if manifest_path().exists():
            self._review_worker(already_busy=True)
        else:
            self.busy = False

    def _fetch_worker_inner(self) -> None:
        try:
            rc, log = actions.fetch_candidates()
            n = actions.count_candidates()
            self._push(meta=self._meta(), log=f"Fetched {n} candidates (rc={rc}).")
        except Exception as exc:  # noqa: BLE001
            self._push(log=f"Fetch error: {exc}")

    def _review_worker(self, already_busy: bool = False) -> None:
        if not already_busy:
            self.busy = True
        self._push(text="opening selection window…", kind="busy", busy=True,
                   log="Opening the paper picker — choose papers, then Deep-review.")
        try:
            dois = actions.run_selection()
        except Exception as exc:  # noqa: BLE001
            self.busy = False
            self._push(text="selection error", kind="err", busy=False, log=f"ERROR: {exc}")
            return
        if not dois:
            self.busy = False
            self._push(text="idle", kind="", busy=False, log="No papers selected.")
            return

        engine = get_engine()
        label = ENGINE_LABELS.get(engine, engine)
        self._push(text=f"reviewing via {label}…", kind="busy", busy=True,
                   log=f"Starting deep review via {label}. Already-reviewed papers are skipped.")
        try:
            res = review_runner.run_review(dois, engine=engine)
        except Exception as exc:  # noqa: BLE001
            self.busy = False
            self._push(text="review failed", kind="err", busy=False, log=f"ERROR: {exc}")
            return
        self.busy = False

        for doi, path in res.skipped:
            self._push(log=f"Reusing stored review — {doi}\n  → {path.name}")

        if res.reviewed and res.returncode != 0:
            self._push(text=f"review failed (exit {res.returncode})", kind="err", busy=False,
                       log=f"Engine exited {res.returncode}.\n{_log_tail(res.log)}")
            return

        if res.summary.exists():
            nrev, nreuse = len(res.reviewed), len(res.skipped)
            parts = ([f"{nrev} reviewed"] if nrev else []) + ([f"{nreuse} reused"] if nreuse else [])
            self._push(text="summary ready", kind="ok", busy=False, meta=self._meta(),
                       log=f"Summary of {nrev + nreuse} selected paper(s) "
                           f"({', '.join(parts)}). Opening {res.summary.name}.")
            webbrowser.open(res.summary.as_uri())
        else:
            self._push(text="finished — no summary", kind="", busy=False,
                       log=f"No summary written.\n{_log_tail(res.log)}")

    def open_summary(self) -> None:
        s = summary_path()
        if s.exists():
            webbrowser.open(s.as_uri())
            self._push(log=f"Opened {s}")
        else:
            self._push(text="no summary yet", log="No summary for today — review some papers first.")


def main() -> int:
    api = Api()
    window = webview.create_window(
        "Lit Review",
        HTML_PATH.as_uri(),
        js_api=api,
        width=720,
        height=640,
    )
    api.window = window
    webview.start()
    # pywebview/Cocoa can leave non-daemon threads alive after start() returns.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
