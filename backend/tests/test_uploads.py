from __future__ import annotations

from pathlib import Path

from conftest import TOKEN, VS_TEXT, make_textbook
from test_library import docs, search

from app.config import get_settings
from app.services import jobs


def upload(client, name: str, data: bytes):
    r = client.put("/api/library/upload", params={"filename": name}, content=data, headers=TOKEN)
    if r.status_code == 201 and r.json().get("job_id"):
        assert jobs.wait(r.json()["job_id"], timeout=300)["status"] == "done"
    return r


def test_uploaded_book_is_indexed_immediately(client, library, tmp_path):
    data = Path(make_textbook(tmp_path / "g.pdf", extra_page_text={5: VS_TEXT})).read_bytes()
    r = upload(client, "Greenbergs Handbook of Neurosurgery 9th ed.pdf", data)
    assert r.status_code == 201, r.text
    (d,) = docs(client)
    assert d["status"] == "indexed" and d["edition"] == "9th"
    assert search(client, "retrosigmoid hearing preservation")["hits"][0]["citation"]["printed_page"] == "2"
    folders = client.get("/api/folders", headers=TOKEN).json()
    assert [f["label"] for f in folders] == ["Uploaded books"]
    full = client.get(f"/api/documents/{d['id']}", headers=TOKEN).json()
    assert full["uploaded"] is True


def test_same_name_kept_and_exact_copy_marked_duplicate(client, library, tmp_path):
    data = Path(make_textbook(tmp_path / "x.pdf")).read_bytes()
    upload(client, "Book.pdf", data)
    r = upload(client, "Book.pdf", data)
    assert r.json()["filename"] == "Book (2).pdf"
    assert sorted(d["status"] for d in docs(client)) == ["duplicate", "indexed"]


def test_rejects_wrong_type_fake_pdf_and_path_tricks(client, library):
    assert upload(client, "notes.exe", b"MZ....").status_code == 415
    r = upload(client, "book.pdf", b"<!doctype html><title>Google Drive</title>")
    assert r.status_code == 415 and "real .pdf" in r.json()["detail"]
    assert upload(client, "empty.pdf", b"").status_code == 400
    data = b"%PDF-1.7 minimal"
    r = upload(client, "../../etc/evil.pdf", data)
    assert r.status_code == 201 and r.json()["filename"] == "evil.pdf"
    up = get_settings().data_dir / get_settings().uploads_folder_name
    assert (up / "evil.pdf").exists() and not list(up.glob(".*.part"))


def test_arabic_filename(client, library, tmp_path):
    data = Path(make_textbook(tmp_path / "a.pdf")).read_bytes()
    r = upload(client, "اساليب البحث العلمي.pdf", data)
    assert r.status_code == 201 and r.json()["filename"] == "اساليب البحث العلمي.pdf"


def test_delete_uploaded_book_only(client, library, tmp_path):
    data = Path(make_textbook(tmp_path / "d.pdf", extra_page_text={5: VS_TEXT})).read_bytes()
    upload(client, "Del.pdf", data)
    (d,) = docs(client)
    r = client.delete(f"/api/library/upload/{d['id']}", headers=TOKEN)
    assert r.status_code == 200
    assert docs(client) == [] and search(client, "retrosigmoid hearing")["hits"] == []
    assert not (get_settings().data_dir / get_settings().uploads_folder_name / "Del.pdf").exists()


def test_delete_refuses_library_files(client, library, tmp_path):
    make_textbook(library / "local.pdf")
    client.post("/api/folders", json={"path": str(library)}, headers=TOKEN)
    jid = client.post("/api/scan", json={}, headers=TOKEN).json()["job_id"]
    jobs.wait(jid)
    (d,) = docs(client)
    assert client.delete(f"/api/library/upload/{d['id']}", headers=TOKEN).status_code == 403
    assert (library / "local.pdf").exists()


def test_uploads_can_be_disabled(client, library, monkeypatch):
    monkeypatch.setattr(get_settings(), "uploads_enabled", False)
    assert upload(client, "b.pdf", b"%PDF-1.7").status_code == 403


def test_chunked_upload_with_resume(client, library, tmp_path):
    data = Path(make_textbook(tmp_path / "c.pdf", extra_page_text={5: VS_TEXT})).read_bytes()
    uid = "a1b2c3d4e5f60718"
    parts = [data[i:i + 50_000] for i in range(0, len(data), 50_000)]
    off = 0
    for k, part in enumerate(parts):
        if k == 1:  # a retried/duplicated part is rejected with the size received so far
            r = client.put("/api/library/upload", params={"filename": "Chunked.pdf", "upload_id": uid,
                           "offset": 0, "final": False}, content=part, headers=TOKEN)
            assert r.status_code == 409 and r.json()["detail"]["received"] == off
        last = k == len(parts) - 1
        r = client.put("/api/library/upload", params={"filename": "Chunked.pdf", "upload_id": uid, "offset": off,
                       "final": last}, content=part, headers=TOKEN)
        assert r.status_code == 201, r.text
        off += len(part)
    assert r.json()["size"] == len(data)
    if r.json()["job_id"]:
        jobs.wait(r.json()["job_id"])
    assert search(client, "retrosigmoid hearing preservation")["hits"]
    up = get_settings().data_dir / get_settings().uploads_folder_name
    assert (up / "Chunked.pdf").read_bytes() == data and not list(up.glob(".*part"))


def test_bad_upload_id_rejected(client, library):
    r = client.put("/api/library/upload", params={"filename": "a.pdf", "upload_id": "../../x"}, content=b"%PDF-", headers=TOKEN)
    assert r.status_code == 400
