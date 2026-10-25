"""Google Drive source against a fake Drive API (no network, no Google account)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from conftest import TOKEN, VS_TEXT, make_textbook
from test_library import docs, search

from app.config import get_settings
from app.services import gdrive
from app.services import jobs as jobs_mod

ROOT = "rootFolder0001"
SUB = "subFolder00002"


class FakeDrive:
    """Minimal Drive v3: files.list (by parent), files.get, alt=media download."""

    def __init__(self):
        self.items: dict[str, dict] = {
            ROOT: {"id": ROOT, "name": "Neurosurgery Books", "mimeType": gdrive.FOLDER_MIME, "parent": None},
        }
        self.blobs: dict[str, bytes] = {}
        self.downloads = 0
        self.shared = {ROOT}  # ids visible to the service account (everything below these too)

    def add_folder(self, fid, name, parent):
        self.items[fid] = {"id": fid, "name": name, "mimeType": gdrive.FOLDER_MIME, "parent": parent}

    def add_file(self, fid, name, data: bytes, parent=ROOT, mtime="2026-10-25T07:36:00.000Z"):
        self.items[fid] = {"id": fid, "name": name, "mimeType": "application/pdf", "parent": parent,
                           "size": str(len(data)), "md5Checksum": hashlib.md5(data).hexdigest(), "modifiedTime": mtime}
        self.blobs[fid] = data

    def add_shortcut(self, fid, name, target, parent=ROOT):
        self.items[fid] = {"id": fid, "name": name, "mimeType": gdrive.SHORTCUT_MIME, "parent": parent,
                           "shortcutDetails": {"targetId": target}}

    def visible(self, fid):
        cur = self.items.get(fid)
        while cur is not None:
            if cur["id"] in self.shared:
                return True
            cur = self.items.get(cur.get("parent"))
        return False

    def handler(self, req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer fake-token"
        path = req.url.path
        if path == "/drive/v3/files":
            q = req.url.params["q"]
            parent = q.split("'")[1]
            files = [self._pub(i) for i in self.items.values() if i.get("parent") == parent and self.visible(i["id"])]
            return httpx.Response(200, json={"files": files})
        fid = path.rsplit("/", 1)[-1]
        if fid not in self.items or not self.visible(fid):
            return httpx.Response(404, json={"error": {"code": 404}})
        if req.url.params.get("alt") == "media":
            self.downloads += 1
            return httpx.Response(200, content=self.blobs[fid])
        return httpx.Response(200, json=self._pub(self.items[fid]))

    @staticmethod
    def _pub(i):
        return {k: v for k, v in i.items() if k != "parent"}


@pytest.fixture()
def drive(monkeypatch):
    fake = FakeDrive()
    monkeypatch.setattr(gdrive, "_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    monkeypatch.setattr(gdrive, "token", lambda: "fake-token")
    monkeypatch.setattr(gdrive, "_load_key", lambda: {"client_email": "academy@demo-project.iam.gserviceaccount.com"})
    monkeypatch.setattr(gdrive.time, "sleep", lambda *_: None)
    return fake


def book_bytes(tmp_path: Path, name: str, **kw) -> bytes:
    return Path(make_textbook(tmp_path / name, **kw)).read_bytes()


def scan_all(client):
    r = client.post("/api/scan", json={}, headers=TOKEN)
    assert r.status_code == 202, r.text
    job = jobs_mod.wait(r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["log"]
    return job


def add_drive(client, link=f"https://drive.google.com/drive/folders/{ROOT}?usp=sharing"):
    r = client.post("/api/gdrive/folders", json={"link": link}, headers=TOKEN)
    if r.status_code == 201:
        jid = client.get("/api/jobs", headers=TOKEN).json()["active"]
        if jid:
            assert jobs_mod.wait(jid, timeout=300)["status"] == "done"
    return r


def test_parse_folder_links():
    assert gdrive.parse_folder_ref("https://drive.google.com/drive/folders/1AbCdEfGhIjK?usp=sharing") == "1AbCdEfGhIjK"
    assert gdrive.parse_folder_ref("https://drive.google.com/open?id=1AbCdEfGhIjK") == "1AbCdEfGhIjK"
    assert gdrive.parse_folder_ref(" 1AbCdEfGhIjK ") == "1AbCdEfGhIjK"
    with pytest.raises(gdrive.DriveError):
        gdrive.parse_folder_ref("https://example.com/x")


def test_status_shows_service_account(client, library, drive):
    s = client.get("/api/gdrive/status", headers=TOKEN).json()
    assert s["configured"] and s["service_account_email"].endswith(".iam.gserviceaccount.com")


def test_drive_book_indexed_and_cited(client, library, drive, tmp_path):
    drive.add_file("fileGreenberg01", "Greenbergs Handbook of Neurosurgery 9th ed.pdf",
                   book_bytes(tmp_path, "g.pdf", extra_page_text={5: VS_TEXT}))
    r = add_drive(client)
    assert r.status_code == 201, r.text
    assert r.json()["label"] == "Google Drive: Neurosurgery Books"
    (d,) = docs(client)
    assert d["status"] == "indexed" and d["path"] == "gdrive://fileGreenberg01"
    assert d["filename"] == "Greenbergs Handbook of Neurosurgery 9th ed.pdf" and d["edition"] == "9th"
    hit = search(client, "retrosigmoid hearing preservation")["hits"][0]
    assert hit["citation"]["printed_page"] == "2" and hit["citation"]["pdf_page"] == 6
    full = client.get(f"/api/documents/{d['id']}", headers=TOKEN).json()
    assert full["source"] == "gdrive" and full["web_link"] == "https://drive.google.com/file/d/fileGreenberg01/view"
    img = client.get(f"/api/documents/{d['id']}/pages/5/image", headers=TOKEN)
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert drive.downloads == 1                       # page images come from the cache


def test_incremental_change_rename_and_removal(client, library, drive, tmp_path):
    drive.add_folder(SUB, "Spine", ROOT)
    drive.add_file("fileA", "Book A.pdf", book_bytes(tmp_path, "a.pdf", title="Book A"))
    drive.add_file("fileB", "Book B.pdf", book_bytes(tmp_path, "b.pdf", title="Book B"), parent=SUB)
    add_drive(client)
    assert sorted(d["filename"] for d in docs(client)) == ["Book A.pdf", "Book B.pdf"]
    assert drive.downloads == 2

    job = scan_all(client)                           # nothing changed: no downloads, nothing indexed
    assert job["progress"]["files_unchanged"] == 2 and job["progress"]["to_index"] == 0 and drive.downloads == 2

    drive.items["fileA"]["name"] = "Book A renamed.pdf"
    scan_all(client)
    assert "Book A renamed.pdf" in [d["filename"] for d in docs(client)] and drive.downloads == 2

    drive.add_file("fileB", "Book B.pdf", book_bytes(tmp_path, "b2.pdf", title="Book B",
                   extra_page_text={3: "Telovelar approach to the fourth ventricle."}), parent=SUB,
                   mtime="2026-10-26T08:00:00.000Z")
    job = scan_all(client)
    assert job["progress"]["files_changed"] == 1 and drive.downloads == 3
    assert search(client, "telovelar ventricle")["hits"]

    del drive.items["fileA"]
    job = scan_all(client)
    assert job["progress"]["files_missing"] == 1
    assert not (get_settings().data_dir / "gdrive-cache" / "fileA.pdf").exists()


def test_duplicate_in_drive_not_indexed_twice(client, library, drive, tmp_path):
    data = book_bytes(tmp_path, "x.pdf")
    drive.add_file("f1", "Book.pdf", data)
    drive.add_file("f2", "Book (1).pdf", data)
    add_drive(client)
    statuses = sorted(d["status"] for d in docs(client))
    assert statuses == ["duplicate", "indexed"] and drive.downloads == 1


def test_shortcut_followed_only_when_shared(client, library, drive, tmp_path):
    drive.add_folder("elsewhere", "Not shared", None)
    drive.add_file("hidden", "Private.pdf", book_bytes(tmp_path, "p.pdf"), parent="elsewhere")
    drive.add_shortcut("sc1", "Private.pdf", "hidden")
    drive.add_folder("sharedOther", "Shared", None)
    drive.shared.add("sharedOther")
    drive.add_file("visible", "Visible.pdf", book_bytes(tmp_path, "v.pdf"), parent="sharedOther")
    drive.add_shortcut("sc2", "Visible.pdf", "visible")
    add_drive(client)
    assert [d["filename"] for d in docs(client)] == ["Visible.pdf"]
    log = jobs_mod.get(client.get("/api/jobs", headers=TOKEN).json()["jobs"][0]["id"])["log"]
    assert "not shared with the service account" in log


def test_unshared_folder_explains_fix(client, library, drive):
    r = add_drive(client, "https://drive.google.com/drive/folders/someoneElsesFolder")
    assert r.status_code == 400 and "academy@demo-project.iam.gserviceaccount.com" in r.json()["detail"]


def test_file_link_rejected(client, library, drive, tmp_path):
    drive.add_file("aFile0000001", "Book.pdf", book_bytes(tmp_path, "y.pdf"))
    r = add_drive(client, "aFile0000001")
    assert r.status_code == 400 and "not a folder" in r.json()["detail"]


def test_drive_outage_does_not_delete_index(client, library, drive, tmp_path, monkeypatch):
    drive.add_file("f1", "Book.pdf", book_bytes(tmp_path, "z.pdf", extra_page_text={5: VS_TEXT}))
    add_drive(client)

    def down(req):
        raise httpx.ConnectError("offline", request=req)
    monkeypatch.setattr(gdrive, "_client", lambda: httpx.Client(transport=httpx.MockTransport(down)))
    job = scan_all(client)
    assert job["progress"].get("files_missing", 0) == 0
    assert docs(client)[0]["status"] == "indexed" and search(client, "retrosigmoid hearing")["hits"]


def test_not_configured(client, library, monkeypatch):
    monkeypatch.setattr(gdrive, "_load_key", lambda: None)
    r = client.post("/api/gdrive/folders", json={"link": ROOT}, headers=TOKEN)
    assert r.status_code == 400 and "not configured" in r.json()["detail"]


def test_cloud_mode_blocks_local_disk(client, library, monkeypatch):
    monkeypatch.setattr(get_settings(), "local_folders_enabled", False)
    assert client.post("/api/folders", json={"path": str(library)}, headers=TOKEN).status_code == 403
    assert client.get("/api/fs/browse", headers=TOKEN).status_code == 403
