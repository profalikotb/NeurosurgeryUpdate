"""Cross-process scan lock (UI backend and scheduled CLI scans must not index concurrently).
OS-level file locks are released automatically if the holding process dies."""
from __future__ import annotations

import os

from ..config import get_settings


class ScanLock:
    def __init__(self) -> None:
        self.path = get_settings().data_dir / "scan.lock"
        self._fh = None

    def acquire(self) -> bool:
        fh = open(self.path, "a+b")  # noqa: SIM115
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if not self._fh:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None
