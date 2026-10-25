"""Windows-friendly path handling (drive letters, UNC shares, long paths, Arabic/Unicode names)."""
from __future__ import annotations

import os
from pathlib import Path


def normalize(path: str | os.PathLike[str]) -> str:
    """Canonical stored form: absolute, resolved, OS-native separators, no long-path prefix."""
    p = str(path).strip().strip('"')
    if p.startswith("\\\\?\\UNC\\"):
        p = "\\\\" + p[8:]
    elif p.startswith("\\\\?\\"):
        p = p[4:]
    return str(Path(p).expanduser().resolve())


def os_path(path: str) -> str:
    """Path usable for opening files. On Windows, paths over MAX_PATH need the \\\\?\\ prefix
    unless LongPathsEnabled is set system-wide; Telegram download folders routinely exceed 260 chars."""
    if os.name != "nt" or len(path) < 240 or path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def is_within(child: str, parent: str) -> bool:
    c, p = os.path.normcase(child), os.path.normcase(parent)
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives on Windows
        return False
