from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pymupdf
import pytest

_TMP = Path(tempfile.mkdtemp(prefix="academy-test-"))
os.environ["ACADEMY_DATA_DIR"] = str(_TMP / "data")
os.environ["ACADEMY_API_TOKEN"] = "test-token"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

TOKEN = {"X-Academy-Token": "test-token"}

VS_TEXT = (
    "Vestibular schwannomas arise from the vestibular division of the eighth cranial nerve. "
    "In tumours with brainstem compression, the retrosigmoid approach allows hearing preservation attempts, "
    "whereas the translabyrinthine approach sacrifices hearing but gives early identification of the facial nerve "
    "at the fundus of the internal auditory canal."
)
MENINGIOMA_TEXT = (
    "Petroclival meningiomas extending above the tentorium may require a combined petrosal approach. "
    "Cranial nerves III to XII and the basilar artery perforators are at risk during resection."
)


def make_textbook(path: Path, *, pages: int = 30, front_matter: int = 4, embedded_labels: bool = True,
                  footer_numbers: bool = True, edition_text: str = "Ninth Edition", title: str = "Handbook of Test Neurosurgery",
                  author: str = "Test A, Author B", extra_page_text: dict[int, str] | None = None) -> Path:
    doc = pymupdf.open()
    extra_page_text = extra_page_text or {}
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        y = 72
        if i == 0:
            page.insert_text((72, y), title, fontsize=20)
            page.insert_text((72, y + 40), edition_text, fontsize=14)
            page.insert_text((72, y + 70), "Copyright 2019 Thieme. ISBN 978-1-68420-057-3", fontsize=10)
        printed = i - front_matter + 1
        body = extra_page_text.get(i) or (
            f"Body text of chapter content on physical page {i + 1}. Neurosurgical principles are discussed here "
            f"with anatomical detail about the posterior fossa and supratentorial compartments. Item {i}.")
        tw = pymupdf.TextWriter(page.rect)
        rect = pymupdf.Rect(72, y + 100, 523, 760)
        tw.fill_textbox(rect, body, fontsize=11)
        tw.write_text(page)
        if footer_numbers and printed >= 1:
            page.insert_text((290, 810), str(printed), fontsize=10)
    toc = [[1, "Front Matter", 1],
           [1, "Chapter 1. Skull Base Tumors", front_matter + 1],
           [2, "Vestibular Schwannoma", front_matter + 2],
           [1, "Chapter 2. Meningiomas", front_matter + 11],
           [2, "Petroclival Meningioma", front_matter + 12],
           [1, "Chapter 3. Spine", front_matter + 21]]
    doc.set_toc([t for t in toc if t[2] <= pages])
    if embedded_labels:
        doc.set_page_labels([
            {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
            {"startpage": front_matter, "prefix": "", "style": "D", "firstpagenum": 1},
        ])
    doc.set_metadata({"title": title, "author": author})
    doc.save(str(path))
    doc.close()
    return path


def make_scanned_pdf(path: Path, text: str) -> Path:
    """Image-only PDF (simulates a scanned page)."""
    src = pymupdf.open()
    p = src.new_page(width=595, height=842)
    tw = pymupdf.TextWriter(p.rect)
    tw.fill_textbox(pymupdf.Rect(60, 60, 535, 780), text, fontsize=16)
    tw.write_text(p)
    pix = p.get_pixmap(dpi=200)
    out = pymupdf.open()
    op = out.new_page(width=595, height=842)
    op.insert_image(op.rect, pixmap=pix)
    out.save(str(path))
    return path


@pytest.fixture()
def library(tmp_path: Path):
    """Fresh database + a folder of synthetic books for each test."""
    db = get_settings().db_path
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    from app.db import init_db
    init_db()
    books = tmp_path / "Telegram books" / "Notebooklm books"
    books.mkdir(parents=True)
    return books


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
