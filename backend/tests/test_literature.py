"""Literature module against recorded-format fixtures (no network): Europe PMC, PubMed fallback, offline."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from conftest import TOKEN, make_textbook
from test_library import docs, scan

from app.services import literature as lit

EPMC = {
    "hitCount": 3,
    "nextCursorMark": "AoE_end",
    "resultList": {"result": [
        {"id": "40000001", "source": "MED", "pmid": "40000001", "pmcid": "PMC9900001",
         "doi": "10.1000/rct.2026.1", "title": "Retrosigmoid versus translabyrinthine resection of large vestibular "
         "schwannoma: a <i>randomized</i> controlled trial.", "authorString": "Smith A, Kotb A, Lee C.",
         "journalInfo": {"journal": {"title": "Journal of Neurosurgery"}}, "pubYear": "2026",
         "firstPublicationDate": "2026-10-20", "isOpenAccess": "Y", "inEPMC": "Y", "hasPDF": "Y",
         "citedByCount": 3, "license": "cc by",
         "pubTypeList": {"pubType": ["Randomized Controlled Trial", "Journal Article"]},
         "abstractText": "<h4>Background</h4>Facial nerve outcome was the primary endpoint.",
         "fullTextUrlList": {"fullTextUrl": [
             {"availability": "Open access", "availabilityCode": "OA", "documentStyle": "pdf", "site": "Europe_PMC",
              "url": "https://europepmc.org/articles/PMC9900001?pdf=render"}]}},
        {"id": "40000002", "source": "MED", "pmid": "40000002", "doi": "10.1000/cr.2026.2",
         "title": "Retracted: Giant petroclival meningioma: a case report", "authorString": "Doe J.",
         "journalInfo": {"journal": {"title": "World Neurosurgery"}}, "firstPublicationDate": "2026-10-18",
         "isOpenAccess": "N", "pubTypeList": {"pubType": ["Case Reports", "Retracted Publication"]}},
        {"id": "PPR999", "source": "PPR", "doi": "10.1101/2026.10.01.123",
         "title": "Machine learning prediction of shunt failure", "authorString": "Roe R.",
         "firstPublicationDate": "2026-10-15", "isOpenAccess": "Y", "pubTypeList": {"pubType": ["Preprint"]}},
    ]},
}
PUBMED_SEARCH = {"esearchresult": {"idlist": ["40000001", "40000003"]}}
PUBMED_SUMMARY = {"result": {"uids": ["40000001", "40000003"],
                             "40000001": {"title": "Retrosigmoid versus translabyrinthine resection of large vestibular "
                                          "schwannoma: a randomized controlled trial.", "fulljournalname": "Journal of Neurosurgery",
                                          "sortpubdate": "2026/10/20 00:00", "authors": [{"name": "Smith A"}],
                                          "articleids": [{"idtype": "doi", "value": "10.1000/rct.2026.1"},
                                                         {"idtype": "pmc", "value": "PMC9900001"}],
                                          "pubtype": ["Randomized Controlled Trial"]},
                             "40000003": {"title": "Guidelines for the management of chronic subdural hematoma",
                                          "fulljournalname": "Neurosurgery", "sortpubdate": "2026/10/10 00:00",
                                          "authors": [{"name": "Ali B"}], "articleids": [],
                                          "pubtype": ["Practice Guideline"]}}}


@pytest.fixture()
def net(monkeypatch, tmp_path):
    """Programmable fake internet."""
    state = {"epmc": "ok", "pubmed": "ok", "pdf": None, "calls": []}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"].append(str(req.url))
        host = req.url.host
        if "ebi.ac.uk" in host:
            if state["epmc"] == "down":
                raise httpx.ConnectError("offline", request=req)
            if state["epmc"] == "503":
                return httpx.Response(503, text="maintenance")
            return httpx.Response(200, json=EPMC)
        if "ncbi.nlm.nih.gov" in host:
            if state["pubmed"] == "down":
                raise httpx.ConnectError("offline", request=req)
            return httpx.Response(200, json=PUBMED_SUMMARY if "esummary" in req.url.path else PUBMED_SEARCH)
        if "europepmc.org" in host and state["pdf"] is not None:
            return httpx.Response(200, content=state["pdf"], headers={"content-type": "application/pdf"})
        return httpx.Response(404)

    monkeypatch.setattr(lit, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    monkeypatch.setattr(lit.time, "sleep", lambda *_: None)
    return state


def test_design_rules_are_explicit():
    assert lit.classify(["Randomized Controlled Trial"], "x", "MED")[:2] == ("Randomized controlled trial", 2)
    assert lit.classify([], "A systematic review and meta-analysis of EVD infection", "MED")[0] == \
        "Systematic review / meta-analysis"
    assert lit.classify(["Journal Article"], "A retrospective cohort of 412 patients", "MED")[0] == "Observational study"
    assert lit.classify([], "Anything", "PPR")[0] == "Preprint (not peer reviewed)"
    d, lvl, basis = lit.classify(["Journal Article"], "Surgical anatomy of the cavernous sinus", "MED")
    assert d == "Other / unclassified" and lvl is None and "no design marker" in basis
    assert lit.is_retracted(["Retracted Publication"], "x") and lit.is_retracted([], "RETRACTED: title")


def test_query_translation():
    q = '"vestibular schwannoma" OR (neurosurg* AND trial)'
    assert lit.to_epmc(q) == ('(TITLE:"vestibular schwannoma" OR ABSTRACT:"vestibular schwannoma") OR ( '
                              '(TITLE:neurosurg* OR ABSTRACT:neurosurg*) AND (TITLE:trial OR ABSTRACT:trial) )')
    assert lit.to_pubmed(q) == '"vestibular schwannoma"[tiab] OR ( neurosurg*[tiab] AND trial[tiab] )'


def test_live_search_normalises_and_dedupes(client, library, net):
    r = client.get("/api/literature/search", params={"q": "vestibular schwannoma"}, headers=TOKEN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "Europe PMC" and body["total"] == 3
    rct = next(i for i in body["items"] if i["pmid"] == "40000001")
    assert rct["design"] == "Randomized controlled trial" and rct["level"] == 2
    assert rct["is_oa"] == 1 and rct["oa_pdf_url"].endswith("pdf=render")
    assert "<i>" not in rct["title"] and rct["abstract"].startswith("Background")
    assert rct["links"]["pubmed"] == "https://pubmed.ncbi.nlm.nih.gov/40000001/"
    assert rct["pub_date"] == "2026-10-20"
    retracted = next(i for i in body["items"] if i["pmid"] == "40000002")
    assert retracted["retracted"] == 1 and retracted["design"] == "Case report"
    pre = next(i for i in body["items"] if i["source"] == "PPR")
    assert pre["design"].startswith("Preprint")
    # Preprints are excluded from the query unless asked for
    assert "NOT SRC:PPR" in net["calls"][0].replace("+", " ").replace("%3A", ":")
    client.get("/api/literature/search", params={"q": "vestibular schwannoma"}, headers=TOKEN)
    from app.db import session
    with session() as c:
        assert c.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 3


def test_falls_back_to_pubmed(client, library, net):
    net["epmc"] = "503"
    body = client.get("/api/literature/search", params={"q": "subdural"}, headers=TOKEN).json()
    assert body["source"] == "PubMed" and "Europe PMC unavailable" in body["warning"]
    guideline = next(i for i in body["items"] if i["pmid"] == "40000003")
    assert guideline["design"] == "Guideline / consensus" and guideline["level"] == 1


def test_offline_reports_clearly(client, library, net):
    net["epmc"] = net["pubmed"] = "down"
    r = client.get("/api/literature/search", params={"q": "glioma"}, headers=TOKEN)
    assert r.status_code == 502 and "no internet connection" in r.json()["detail"]
    runs = client.get("/api/literature/runs", headers=TOKEN).json()
    assert runs[0]["status"] == "error"


def test_topic_runs_feed_review_and_stats(client, library, net):
    topics = client.get("/api/literature/topics", headers=TOKEN).json()
    assert len(topics) == 17 and all(t["builtin"] for t in topics)
    sb = next(t for t in topics if t["name"] == "Skull base surgery")
    res = client.post(f"/api/literature/topics/{sb['id']}/run", headers=TOKEN).json()
    assert res["status"] == "ok" and res["new"] == 3
    again = client.post(f"/api/literature/topics/{sb['id']}/run", headers=TOKEN).json()
    assert again["new"] == 0                                       # DOI/PMID de-duplication
    feed = client.get("/api/literature/feed", params={"days": 30, "topic_id": sb["id"]}, headers=TOKEN).json()
    assert feed["total"] == 3 and feed["items"][0]["pub_date"] == "2026-10-20"
    assert feed["items"][0]["topics"] == ["Skull base surgery"]
    trials = client.get("/api/literature/feed", params={"days": 30, "design": "trials"}, headers=TOKEN).json()
    assert [i["pmid"] for i in trials["items"]] == ["40000001"]
    assert client.get("/api/stats", headers=TOKEN).json()["new_publications"] == 3
    client.post("/api/literature/publications/mark-reviewed", json={"ids": [feed["items"][0]["id"]]}, headers=TOKEN)
    assert client.get("/api/stats", headers=TOKEN).json()["new_publications"] == 2
    unrev = client.get("/api/literature/feed", params={"days": 30, "unreviewed": True}, headers=TOKEN).json()
    assert unrev["total"] == 2


def test_topic_crud(client, library, net):
    t = client.post("/api/literature/topics", json={"name": "Chiari", "query": '"Chiari malformation"'}, headers=TOKEN).json()
    assert t["builtin"] == 0
    client.patch(f"/api/literature/topics/{t['id']}", json={"enabled": False}, headers=TOKEN)
    assert next(x for x in client.get("/api/literature/topics", headers=TOKEN).json() if x["id"] == t["id"])["enabled"] == 0
    client.delete(f"/api/literature/topics/{t['id']}", headers=TOKEN)
    assert all(x["id"] != t["id"] for x in client.get("/api/literature/topics", headers=TOKEN).json())


def test_open_access_article_joins_library_with_publisher_metadata(client, library, net, tmp_path):
    pdf = make_textbook(tmp_path / "oa.pdf", pages=6, embedded_labels=False, title="x", author="")
    net["pdf"] = Path(pdf).read_bytes()
    body = client.get("/api/literature/search", params={"q": "vestibular"}, headers=TOKEN).json()
    rct = next(i for i in body["items"] if i["pmid"] == "40000001")
    r = client.post(f"/api/literature/publications/{rct['id']}/add-to-library", headers=TOKEN)
    assert r.status_code == 200, r.text
    path = Path(r.json()["path"])
    assert path.exists() and path.name.startswith("2026 - Smith A - Retrosigmoid")
    folders = client.get("/api/folders", headers=TOKEN).json()
    assert any(f["label"] == "Open-access articles" for f in folders)
    scan(client)
    (d,) = docs(client)
    assert d["title"].startswith("Retrosigmoid versus translabyrinthine") and d["title_src"] == "europe_pmc"
    assert d["publisher"] == "Journal of Neurosurgery" and d["year"] == 2026 and d["metadata_verified"] == 1


def test_closed_access_cannot_be_downloaded(client, library, net):
    body = client.get("/api/literature/search", params={"q": "meningioma"}, headers=TOKEN).json()
    closed = next(i for i in body["items"] if i["pmid"] == "40000002")
    r = client.post(f"/api/literature/publications/{closed['id']}/add-to-library", headers=TOKEN)
    assert r.status_code == 422 and "not open access" in r.json()["detail"]


def test_html_instead_of_pdf_is_rejected(client, library, net):
    net["pdf"] = b"<!doctype html><title>Login</title>"
    body = client.get("/api/literature/search", params={"q": "vestibular"}, headers=TOKEN).json()
    rct = next(i for i in body["items"] if i["pmid"] == "40000001")
    r = client.post(f"/api/literature/publications/{rct['id']}/add-to-library", headers=TOKEN)
    assert r.status_code == 422 and "web page instead of a PDF" in r.json()["detail"]


def test_selftest(client, library, net):
    net["pubmed"] = "down"
    res = {x["source"]: x for x in client.get("/api/literature/selftest", headers=TOKEN).json()}
    assert res["Europe PMC"]["ok"] and not res["PubMed"]["ok"]
    assert json.dumps(res)  # serialisable
