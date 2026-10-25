from __future__ import annotations

import os
import time

from conftest import TOKEN, VS_TEXT, make_textbook
from test_library import add_folder, docs, scan, search

from app.config import get_settings
from app.services import jobs, watcher


def test_new_book_is_indexed_automatically(client, library):
    add_folder(client, library)
    scan(client)
    assert watcher.check_once(None) is None            # nothing to do
    make_textbook(library / "Telegram Desktop new book.pdf", extra_page_text={5: VS_TEXT})
    sig = watcher.check_once(None)                      # first sighting: wait for the file to settle
    assert sig and not jobs.active_job()
    assert watcher.check_once(sig) is None              # stable on second check: scan starts
    jid = jobs.active_job()
    assert jid
    assert jobs.wait(jid)["status"] == "done"
    assert [d["status"] for d in docs(client)] == ["indexed"]
    assert search(client, "retrosigmoid hearing preservation")["hits"]


def test_growing_download_does_not_trigger(client, library):
    add_folder(client, library)
    p = make_textbook(library / "downloading.pdf")
    sig1 = watcher.check_once(None)
    with open(p, "ab") as f:                            # still being written
        f.write(b"%more bytes")
    os.utime(p, (time.time() + 3, time.time() + 3))
    sig2 = watcher.check_once(sig1)
    assert sig2 is not None and sig2 != sig1 and not jobs.active_job()


def test_files_still_downloading_are_skipped(client, library, monkeypatch):
    monkeypatch.setattr(get_settings(), "min_file_age_seconds", 3600)
    add_folder(client, library)
    make_textbook(library / "fresh.pdf")
    job = scan(client)
    assert job["progress"]["discovered"] == 0 and job["progress"]["still_downloading"] == 1


def test_status_reports_auto_indexing(client, library):
    s = client.get("/api/status", headers=TOKEN).json()
    assert "auto_indexing" in s and s["auto_indexing_interval"] == get_settings().watch_interval_seconds
