"""Persistent background jobs (one indexing job at a time). State survives in SQLite."""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from ..db import now_iso, session
from .lock import ScanLock

log = logging.getLogger(__name__)
_lock = threading.Lock()
_active: dict[int, JobContext] = {}


class JobContext:
    def __init__(self, job_id: int):
        self.id = job_id
        self.progress: dict[str, Any] = {}
        self._cancel = threading.Event()
        self._last_flush = 0.0
        self._log: list[str] = []

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def update(self, force: bool = False, **kv: Any) -> None:
        self.progress.update(kv)
        if force or time.monotonic() - self._last_flush > 0.7:
            self.flush()

    def log(self, line: str) -> None:
        stamped = f"[{now_iso()}] {line}"
        log.info(line)
        self._log.append(stamped)
        if len(self._log) >= 20:
            self.flush()

    def flush(self) -> None:
        self._last_flush = time.monotonic()
        lines, self._log = self._log, []
        with session() as c:
            c.execute(
                "UPDATE jobs SET progress=?, log = log || ? WHERE id=?",
                (json.dumps(self.progress), ("\n".join(lines) + "\n") if lines else "", self.id),
            )


def active_job() -> int | None:
    return next(iter(_active), None)


def start(kind: str, fn: Callable[[JobContext], None]) -> int:
    with _lock:
        if _active:
            raise RuntimeError(f"job {next(iter(_active))} is already running")
        lock = ScanLock()
        if not lock.acquire():
            raise RuntimeError("another indexing process (e.g. a scheduled scan) is running")
        with session() as c:
            cur = c.execute("INSERT INTO jobs(kind, status, created_at, progress) VALUES (?,?,?,?)",
                            (kind, "running", now_iso(), "{}"))
            job_id = cur.lastrowid
            c.execute("UPDATE jobs SET started_at=? WHERE id=?", (now_iso(), job_id))
        ctx = JobContext(job_id)
        _active[job_id] = ctx

    def run() -> None:
        status = "done"
        try:
            fn(ctx)
            if ctx.cancelled():
                status = "cancelled"
        except InterruptedError:
            status = "cancelled"
        except Exception as e:  # noqa: BLE001
            status = "failed"
            ctx.log(f"FATAL: {e}\n{traceback.format_exc()}")
        finally:
            ctx.update(force=True, phase="finished")
            with session() as c:
                c.execute("UPDATE jobs SET status=?, finished_at=? WHERE id=?", (status, now_iso(), job_id))
            _active.pop(job_id, None)
            lock.release()

    threading.Thread(target=run, name=f"job-{job_id}", daemon=True).start()
    return job_id


def cancel(job_id: int) -> bool:
    ctx = _active.get(job_id)
    if not ctx:
        return False
    ctx.cancel()
    return True


def get(job_id: int) -> dict[str, Any] | None:
    with session() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["progress"] = json.loads(d["progress"] or "{}")
    d["log"] = d["log"][-20000:]
    return d


def wait(job_id: int, timeout: float = 600) -> dict[str, Any] | None:
    """Used by tests and CLI."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if job_id not in _active:
            return get(job_id)
        time.sleep(0.05)
    return get(job_id)
