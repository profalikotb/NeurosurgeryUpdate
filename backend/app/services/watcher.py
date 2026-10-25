"""Automatic indexing: polls the library folders and starts an incremental scan when books are added,
changed or removed. A change must be stable across two consecutive checks before a scan starts, so a
book that is still downloading does not trigger repeated work."""
from __future__ import annotations

import logging
import threading

from ..config import get_settings
from ..db import session
from . import indexer, jobs

log = logging.getLogger(__name__)
_thread: threading.Thread | None = None
_stop = threading.Event()
state = {"last_check": None, "last_trigger": None, "pending_changes": 0}


def detect_changes() -> tuple[int, frozenset]:
    """Returns (number of differences between disk and index, a signature of those differences)."""
    with session() as c:
        folders = c.execute("SELECT * FROM folders WHERE enabled=1").fetchall()
        docs = c.execute("SELECT path, size, mtime, status, folder_id FROM documents").fetchall()
    if not folders:
        return 0, frozenset()
    files, reachable = indexer.discover_ex(folders, None)
    known = {d["path"]: d for d in docs}
    diff: set[tuple] = set()
    for f in files:
        d = known.get(f.path)
        if d is None or d["status"] == "missing" or d["size"] != f.size or abs(d["mtime"] - f.mtime) > 1:
            diff.add(("file", f.path, f.size, int(f.mtime)))
    seen = {f.path for f in files}
    for p, d in known.items():
        if d["status"] != "missing" and p not in seen and indexer.in_reachable(d, folders, reachable):
            diff.add(("gone", p))
    return len(diff), frozenset(diff)


def check_once(previous: frozenset | None) -> frozenset | None:
    """One watcher cycle. Returns the signature to compare against next time."""
    from ..db import now_iso

    state["last_check"] = now_iso()
    if jobs.active_job():
        return None
    n, sig = detect_changes()
    state["pending_changes"] = n
    if n == 0:
        return None
    if sig != previous:
        return sig  # changes still settling; confirm on the next cycle
    try:
        jobs.start("auto-scan", lambda ctx: indexer.run_scan(ctx))
        state["last_trigger"] = now_iso()
        log.info("Auto-indexing: %d change(s) detected, scan started", n)
    except RuntimeError:
        pass  # another process holds the scan lock; try again next cycle
    return None


def _loop() -> None:
    previous: frozenset | None = None
    interval = max(10, get_settings().watch_interval_seconds)
    while not _stop.wait(interval):
        try:
            previous = check_once(previous)
        except Exception as e:  # noqa: BLE001 - the watcher must never die
            log.warning("Auto-indexing check failed: %s", e)


def start() -> None:
    global _thread
    if not get_settings().watch_enabled or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="library-watcher", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


def running() -> bool:
    return bool(_thread and _thread.is_alive())
