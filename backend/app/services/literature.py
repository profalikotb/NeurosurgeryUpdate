"""Scientific literature: Europe PMC (primary) with PubMed E-utilities as fallback.

Europe PMC indexes all of PubMed/MEDLINE plus PubMed Central full text, preprints and NCBI Bookshelf, and
reports open-access status and publication types. Everything here is metadata and abstracts published by the
sources themselves; only open-access articles can be downloaded into the library.

Study-design labels are produced by explicit, reproducible rules over the publication types and title
(`classify`), never by an opaque score. They describe the *design* of a study, not whether its findings
are correct; appraising the findings is a separate step.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from .. import __version__
from ..config import get_settings
from ..db import audit, now_iso, session

log = logging.getLogger(__name__)

EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
MAX_PER_RUN = 300


class SourceError(RuntimeError):
    """A literature source could not be reached or returned an unusable answer."""


# ------------------------------------------------------------------------------------------ records
@dataclass
class Pub:
    title: str
    source: str
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    authors: str | None = None
    journal: str | None = None
    pub_date: str | None = None
    pub_types: list[str] = field(default_factory=list)
    is_oa: bool = False
    oa_pdf_url: str | None = None
    license: str | None = None
    abstract: str | None = None
    cited_by: int | None = None
    native_id: str | None = None

    @property
    def key(self) -> str:
        if self.pmid:
            return f"pmid:{self.pmid}"
        if self.doi:
            return f"doi:{self.doi.lower()}"
        return f"{self.source}:{self.native_id or self.title[:80].lower()}"


_TAG = re.compile(r"<[^>]+>")


def _clean(s: Any) -> str | None:
    if not s:
        return None
    s = _TAG.sub("", str(s))
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


# ------------------------------------------------------------------------------------------ classification
_DESIGN_RULES: list[tuple[str, int, list[str], list[str]]] = [
    # (design, level 1=highest .. 5, publication-type matches, title regexes)
    ("Retraction notice", 0, ["retraction of publication"], [r"^retraction( note)?:"]),
    ("Guideline / consensus", 1, ["practice guideline", "guideline", "consensus development conference"],
     [r"\bguideline", r"\bconsensus statement", r"\brecommendations? (of|from) the\b"]),
    ("Systematic review / meta-analysis", 1, ["systematic review", "meta-analysis"],
     [r"\bsystematic review", r"\bmeta-?analys", r"\bumbrella review"]),
    ("Randomized controlled trial", 2, ["randomized controlled trial"],
     [r"\brandomi[sz]ed (controlled |clinical )?trial", r"\brandomi[sz]ed,? (double|single)-blind"]),
    ("Prospective study / clinical trial", 3,
     ["clinical trial", "clinical trial, phase i", "clinical trial, phase ii", "clinical trial, phase iii",
      "controlled clinical trial", "multicenter study"],
     [r"\bprospective\b", r"\bphase (i|ii|iii|1|2|3)\b.*\btrial", r"\bnon-?inferiority\b"]),
    ("Observational study", 4, ["observational study", "comparative study"],
     [r"\bcohort\b", r"\bregistry\b", r"\bretrospective\b", r"\bcase-control\b", r"\bpropensity", r"\bnational database"]),
    ("Case series", 4, [], [r"\bcase series\b", r"\bseries of \d+", r"\b\d+ (consecutive )?(patients|cases)\b"]),
    ("Case report", 5, ["case reports"], [r"\bcase report\b", r"\ba case of\b", r":\s*case\b"]),
    ("Technical note", 5, ["technical report"], [r"\btechnical note\b", r"\bhow i do it\b", r"\boperative (video|technique)\b"]),
    ("Narrative review", 5, ["review"], [r"\breview\b", r"\boverview\b", r"\bstate of the art\b"]),
    ("Editorial / letter / comment", 5, ["editorial", "letter", "comment", "news", "published erratum"],
     [r"^(editorial|letter|comment|in reply|reply to)\b"]),
]


def classify(pub_types: list[str], title: str, source: str | None) -> tuple[str, int | None, str]:
    """Returns (design, level, basis). Publication types reported by the source outrank title keywords."""
    pts = {p.strip().lower() for p in pub_types}
    low = (title or "").lower()
    if source == "PPR" or "preprint" in pts:
        return "Preprint (not peer reviewed)", 5, "source: preprint server"
    for design, level, types, _ in _DESIGN_RULES:
        hit = next((t for t in types if t in pts), None)
        if hit:
            return design, level or None, f"publication type: {hit}"
    for design, level, _, pats in _DESIGN_RULES:
        for p in pats:
            if re.search(p, low):
                return design, level or None, f"title contains '{re.search(p, low).group(0).strip()}'"
    return "Other / unclassified", None, "no design marker in publication type or title"


def is_retracted(pub_types: list[str], title: str) -> bool:
    pts = {p.strip().lower() for p in pub_types}
    return "retracted publication" in pts or bool(re.match(r"^\s*(retracted|withdrawn)\b", title or "", re.I))


# ------------------------------------------------------------------------------------------ query syntax
_TOKEN = re.compile(r'"[^"]+"|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()"]+')


def _tokens(q: str) -> list[str]:
    return _TOKEN.findall(q.strip())


def to_epmc(q: str, fields: str = "tiab") -> str:
    """User query (terms, "phrases", AND/OR/NOT, parentheses, trailing *) -> Europe PMC syntax.
    fields='tiab' restricts every term to title or abstract; 'all' leaves it as is."""
    if fields == "all":
        return q
    out = []
    for t in _tokens(q):
        if t in ("(", ")", "AND", "OR", "NOT"):
            out.append(t)
        else:
            out.append(f"(TITLE:{t} OR ABSTRACT:{t})")
    return " ".join(out)


def to_pubmed(q: str, fields: str = "tiab") -> str:
    if fields == "all":
        return q
    out = []
    for t in _tokens(q):
        out.append(t if t in ("(", ")", "AND", "OR", "NOT") else f"{t}[tiab]")
    return " ".join(out)


# ------------------------------------------------------------------------------------------ HTTP
def _client() -> httpx.Client:
    s = get_settings()
    ua = f"NeurosurgeryAIAcademy/{__version__} (private academic use" + (f"; {s.contact_email}" if s.contact_email else "") + ")"
    return httpx.Client(timeout=s.literature_timeout_seconds, headers={"User-Agent": ua}, follow_redirects=True)


def _get_json(client: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = client.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                last = SourceError(f"HTTP {r.status_code}")
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise SourceError(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        except (httpx.TransportError, ValueError) as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise SourceError(_friendly(last))


def _friendly(e: Exception | None) -> str:
    if isinstance(e, httpx.ProxyError):
        return f"blocked by a proxy or firewall ({e})"
    if isinstance(e, httpx.ConnectError):
        return "no internet connection (or the source is blocked by a firewall)"
    if isinstance(e, httpx.TimeoutException):
        return "the source did not answer in time"
    return str(e) if e else "unknown error"


# ------------------------------------------------------------------------------------------ Europe PMC
def _epmc_record(r: dict[str, Any]) -> Pub:
    pts = r.get("pubTypeList", {}).get("pubType", []) or []
    if isinstance(pts, str):
        pts = [pts]
    journal = (r.get("journalInfo") or {}).get("journal", {}) or {}
    pdf = None
    for u in (r.get("fullTextUrlList") or {}).get("fullTextUrl", []) or []:
        if u.get("documentStyle") == "pdf" and u.get("availabilityCode") in ("OA", "F"):
            pdf = u.get("url")
            break
    is_oa = r.get("isOpenAccess") == "Y"
    if not pdf and is_oa and r.get("pmcid"):
        pdf = f"https://europepmc.org/articles/{r['pmcid']}?pdf=render"
    title = _clean(r.get("title")) or "(untitled)"
    cited = r.get("citedByCount")
    return Pub(
        title=title.rstrip("."),
        source=r.get("source") or "EPMC",
        native_id=str(r.get("id")) if r.get("id") else None,
        pmid=r.get("pmid") or None,
        pmcid=r.get("pmcid") or None,
        doi=(r.get("doi") or None),
        authors=_clean(r.get("authorString")),
        journal=_clean(journal.get("title")) or _clean(r.get("bookOrReportDetails", {}).get("publisher")
                                                       if isinstance(r.get("bookOrReportDetails"), dict) else None),
        pub_date=r.get("firstPublicationDate") or (f"{r['pubYear']}-01-01" if r.get("pubYear") else None),
        pub_types=list(pts),
        is_oa=is_oa,
        oa_pdf_url=pdf if is_oa else None,
        license=r.get("license") or None,
        abstract=_clean(r.get("abstractText")),
        cited_by=int(cited) if str(cited or "").isdigit() else None,
    )


def search_epmc(query: str, date_from: str | None, date_to: str | None, *, oa_only: bool = False,
                include_preprints: bool = False, fields: str = "tiab", limit: int = 100) -> list[Pub]:
    q = f"({to_epmc(query, fields)})"
    if date_from or date_to:
        q += f" AND (FIRST_PDATE:[{date_from or '1900-01-01'} TO {date_to or date.today().isoformat()}])"
    if oa_only:
        q += " AND OPEN_ACCESS:y"
    if not include_preprints:
        q += " NOT SRC:PPR"
    out: list[Pub] = []
    cursor = "*"
    with _client() as c:
        while len(out) < limit:
            params = {"query": q, "format": "json", "resultType": "core", "pageSize": min(100, limit - len(out)),
                      "cursorMark": cursor, "sort": "FIRST_PDATE_D desc"}
            try:
                data = _get_json(c, EPMC_SEARCH, params)
            except SourceError as e:
                if "HTTP 400" in str(e) and "sort" in params:  # tolerate a sort-syntax change upstream
                    params.pop("sort")
                    data = _get_json(c, EPMC_SEARCH, params)
                else:
                    raise
            results = (data.get("resultList") or {}).get("result") or []
            out.extend(_epmc_record(r) for r in results)
            nxt = data.get("nextCursorMark")
            if not results or not nxt or nxt == cursor:
                break
            cursor = nxt
    return out[:limit]


# ------------------------------------------------------------------------------------------ PubMed fallback
def _pubmed_date(s: str | None) -> str | None:
    if not s:
        return None
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{4})", s)
    return f"{m.group(1)}-01-01" if m else None


def search_pubmed(query: str, date_from: str | None, date_to: str | None, *, fields: str = "tiab",
                  limit: int = 100, **_: Any) -> list[Pub]:
    s = get_settings()
    term = f"({to_pubmed(query, fields)})"
    if date_from or date_to:
        f = (date_from or "1900-01-01").replace("-", "/")
        t = (date_to or date.today().isoformat()).replace("-", "/")
        term += f' AND ("{f}"[dp] : "{t}"[dp])'
    common = {"db": "pubmed", "retmode": "json", "tool": "NeurosurgeryAIAcademy"}
    if s.contact_email:
        common["email"] = s.contact_email
    with _client() as c:
        ids = _get_json(c, PUBMED_ESEARCH, {**common, "term": term, "retmax": limit, "sort": "pub_date"})
        idlist = (ids.get("esearchresult") or {}).get("idlist") or []
        if not idlist:
            return []
        summ = _get_json(c, PUBMED_ESUMMARY, {**common, "id": ",".join(idlist)})
    res = summ.get("result") or {}
    out = []
    for uid in res.get("uids", idlist):
        r = res.get(uid) or {}
        ids_ = {a.get("idtype"): a.get("value") for a in r.get("articleids", []) if isinstance(a, dict)}
        pmc = ids_.get("pmc")
        out.append(Pub(
            title=(_clean(r.get("title")) or "(untitled)").rstrip("."),
            source="pubmed", native_id=uid, pmid=uid, pmcid=pmc, doi=ids_.get("doi"),
            authors=", ".join(a.get("name", "") for a in r.get("authors", [])[:6] if isinstance(a, dict))
            + (" et al." if len(r.get("authors", [])) > 6 else "") or None,
            journal=_clean(r.get("fulljournalname") or r.get("source")),
            pub_date=_pubmed_date(r.get("sortpubdate") or r.get("pubdate")),
            pub_types=[p for p in r.get("pubtype", []) if isinstance(p, str)],
            is_oa=bool(pmc),
            oa_pdf_url=f"https://europepmc.org/articles/{pmc}?pdf=render" if pmc else None,
        ))
    return out


def search(query: str, date_from: str | None = None, date_to: str | None = None, **kw: Any) -> tuple[list[Pub], str, str | None]:
    """Europe PMC first; PubMed if Europe PMC fails. Returns (records, source used, warning)."""
    try:
        return search_epmc(query, date_from, date_to, **kw), "Europe PMC", None
    except SourceError as e:
        warning = f"Europe PMC unavailable ({e}); results from PubMed (no abstracts)."
        try:
            return search_pubmed(query, date_from, date_to, **kw), "PubMed", warning
        except SourceError as e2:
            raise SourceError(f"Europe PMC: {e}; PubMed: {e2}") from e2


# ------------------------------------------------------------------------------------------ storage
def upsert(conn, pubs: list[Pub]) -> list[tuple[int, bool]]:
    """Store records with DOI/PMID de-duplication. Returns [(publication_id, is_new)]."""
    out = []
    now = now_iso()
    for p in pubs:
        design, level, basis = classify(p.pub_types, p.title, p.source)
        row = None
        if p.pmid:
            row = conn.execute("SELECT id FROM publications WHERE pmid=?", (p.pmid,)).fetchone()
        if row is None and p.doi:
            row = conn.execute("SELECT id FROM publications WHERE lower(doi)=lower(?)", (p.doi,)).fetchone()
        if row is None:
            row = conn.execute("SELECT id FROM publications WHERE key=?", (p.key,)).fetchone()
        vals = dict(pmid=p.pmid, pmcid=p.pmcid, doi=p.doi, source=p.source, title=p.title, authors=p.authors,
                    journal=p.journal, pub_date=p.pub_date, pub_types=json.dumps(p.pub_types), design=design,
                    level=level, design_basis=basis, is_oa=int(p.is_oa), oa_pdf_url=p.oa_pdf_url, license=p.license,
                    abstract=p.abstract, cited_by=p.cited_by, retracted=int(is_retracted(p.pub_types, p.title)))
        if row is None:
            cols = ", ".join(["key", *vals, "first_seen_at", "last_seen_at"])
            cur = conn.execute(f"INSERT INTO publications({cols}) VALUES ({','.join('?' * (len(vals) + 3))})",
                               (p.key, *vals.values(), now, now))
            out.append((cur.lastrowid, True))
        else:
            # Never blank out richer data (e.g. an abstract from Europe PMC) with a sparser PubMed record.
            sets = ", ".join(f"{k}=COALESCE(?, {k})" for k in vals)
            conn.execute(f"UPDATE publications SET {sets}, last_seen_at=? WHERE id=?",
                         (*vals.values(), now, row["id"]))
            out.append((row["id"], False))
    return out


def pub_row(r) -> dict[str, Any]:
    d = dict(r)
    d["pub_types"] = json.loads(d.get("pub_types") or "[]")
    d["links"] = {
        "pubmed": f"https://pubmed.ncbi.nlm.nih.gov/{d['pmid']}/" if d.get("pmid") else None,
        "doi": f"https://doi.org/{d['doi']}" if d.get("doi") else None,
        "pmc": f"https://pmc.ncbi.nlm.nih.gov/articles/{d['pmcid']}/" if d.get("pmcid") else None,
        "europepmc": (f"https://europepmc.org/article/MED/{d['pmid']}" if d.get("pmid") else None),
    }
    return d


# ------------------------------------------------------------------------------------------ topics
def _terms(*t: str) -> str:
    return " OR ".join(f'"{x}"' if " " in x or "-" in x else x for x in t)


DEFAULT_TOPICS: list[tuple[str, str]] = [
    ("Brain tumors and neuro-oncology", f"({_terms('glioma', 'glioblastoma', 'brain metastases', 'meningioma', 'brain tumor', 'brain tumour')}) AND ({_terms('surgery', 'resection', 'neurosurgical', 'survival')})"),
    ("Skull base surgery", _terms("skull base", "vestibular schwannoma", "pituitary adenoma", "pituitary neuroendocrine tumor", "craniopharyngioma", "chordoma", "petroclival")),
    ("Cerebrovascular neurosurgery", _terms("intracranial aneurysm", "subarachnoid hemorrhage", "arteriovenous malformation", "cavernous malformation", "moyamoya", "intracerebral hemorrhage")),
    ("Functional neurosurgery", _terms("deep brain stimulation", "focused ultrasound thalamotomy", "trigeminal neuralgia", "microvascular decompression")),
    ("Epilepsy surgery", _terms("epilepsy surgery", "temporal lobectomy", "laser interstitial thermal therapy", "responsive neurostimulation", "stereoelectroencephalography")),
    ("Spine surgery", _terms("spine surgery", "spinal fusion", "cervical myelopathy", "lumbar spinal stenosis", "lumbar disc herniation", "minimally invasive spine", "endoscopic spine")),
    ("Pediatric neurosurgery", _terms("pediatric neurosurgery", "craniosynostosis", "myelomeningocele", "medulloblastoma", "Chiari malformation", "pediatric hydrocephalus")),
    ("Neurotrauma", _terms("traumatic brain injury", "decompressive craniectomy", "chronic subdural hematoma", "acute subdural hematoma", "spinal cord injury")),
    ("Neurocritical care", f"({_terms('neurocritical care', 'intracranial pressure', 'delayed cerebral ischemia', 'cerebral vasospasm', 'brain tissue oxygen')})"),
    ("Hydrocephalus and CSF disorders", _terms("hydrocephalus", "normal pressure hydrocephalus", "ventriculoperitoneal shunt", "endoscopic third ventriculostomy", "idiopathic intracranial hypertension", "CSF leak")),
    ("Neuroendoscopy", _terms("neuroendoscopy", "endoscopic endonasal", "endoscopic neurosurgery", "endoscopic intraventricular")),
    ("Peripheral nerve surgery", _terms("peripheral nerve surgery", "brachial plexus", "nerve transfer", "peripheral nerve injury", "carpal tunnel release")),
    ("Neurovascular imaging", f"({_terms('vessel wall imaging', 'CT perfusion', 'digital subtraction angiography', 'cerebral angiography', 'aneurysm imaging')}) AND (neurosurg* OR aneurysm OR stroke)"),
    ("Surgical navigation and robotics", f"({_terms('neuronavigation', 'robotic', 'robot-assisted', 'intraoperative MRI', 'augmented reality', 'exoscope')}) AND (neurosurg* OR spine OR cranial)"),
    ("AI in neurosurgery", f"({_terms('artificial intelligence', 'machine learning', 'deep learning', 'large language model')}) AND (neurosurg* OR spine surgery OR glioma OR aneurysm)"),
    ("Radiosurgery", _terms("stereotactic radiosurgery", "gamma knife", "CyberKnife", "fractionated stereotactic radiotherapy")),
    ("Brain-computer interfaces and neuromodulation", _terms("brain-computer interface", "brain-machine interface", "neuromodulation", "spinal cord stimulation", "vagus nerve stimulation")),
]


def ensure_default_topics() -> None:
    with session() as c:
        if c.execute("SELECT COUNT(*) FROM topics").fetchone()[0]:
            return
        for name, q in DEFAULT_TOPICS:
            c.execute("INSERT INTO topics(name, query, enabled, builtin, created_at) VALUES (?,?,1,1,?)",
                      (name, q, now_iso()))


def run_topic(topic_id: int, *, days: int | None = None) -> dict[str, Any]:
    s = get_settings()
    with session() as c:
        t = c.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    if t is None:
        raise KeyError(topic_id)
    today = date.today()
    if days is not None:
        start = today - timedelta(days=days)
    elif t["last_run_at"]:
        start = datetime.fromisoformat(t["last_run_at"]).date() - timedelta(days=3)  # overlap for late indexing
    else:
        start = today - timedelta(days=s.literature_initial_days)
    started = now_iso()
    with session() as c:
        run_id = c.execute("INSERT INTO search_runs(topic_id, query, window_from, window_to, started_at, status) "
                           "VALUES (?,?,?,?,?, 'running')",
                           (topic_id, t["query"], start.isoformat(), today.isoformat(), started)).lastrowid
    try:
        pubs, source, warning = search(t["query"], start.isoformat(), today.isoformat(), limit=MAX_PER_RUN)
    except SourceError as e:
        with session() as c:
            c.execute("UPDATE search_runs SET status='error', error=?, finished_at=? WHERE id=?", (str(e), now_iso(), run_id))
        return {"topic_id": topic_id, "status": "error", "error": str(e)}
    with session() as c:
        res = upsert(c, pubs)
        new_hits = 0
        for pid, _is_new in res:
            cur = c.execute("INSERT OR IGNORE INTO topic_hits(topic_id, publication_id, first_seen_at) VALUES (?,?,?)",
                            (topic_id, pid, now_iso()))
            new_hits += cur.rowcount
        c.execute("UPDATE search_runs SET status='ok', source=?, found=?, new=?, error=?, finished_at=? WHERE id=?",
                  (source, len(pubs), new_hits, warning, now_iso(), run_id))
        c.execute("UPDATE topics SET last_run_at=? WHERE id=?", (now_iso(), topic_id))
    return {"topic_id": topic_id, "status": "ok", "source": source, "found": len(pubs), "new": new_hits,
            "warning": warning}


_run_lock = threading.Lock()
run_state: dict[str, Any] = {"running": False, "current": None, "done": 0, "total": 0, "last_finished": None}


def run_all(only_due: bool = False) -> list[dict[str, Any]]:
    if not _run_lock.acquire(blocking=False):
        return []
    try:
        s = get_settings()
        with session() as c:
            topics = c.execute("SELECT * FROM topics WHERE enabled=1 ORDER BY id").fetchall()
        if only_due:
            cutoff = datetime.now(UTC) - timedelta(hours=s.literature_update_hours)
            topics = [t for t in topics if not t["last_run_at"] or datetime.fromisoformat(t["last_run_at"]) < cutoff]
        run_state.update(running=True, done=0, total=len(topics))
        results = []
        for t in topics:
            run_state["current"] = t["name"]
            r = run_topic(t["id"])
            results.append(r)
            run_state["done"] += 1
            if r["status"] == "error" and "no internet" in r.get("error", ""):
                break  # offline: do not hammer every topic
            time.sleep(0.4)  # be polite to the public APIs
        return results
    finally:
        run_state.update(running=False, current=None, last_finished=now_iso())
        _run_lock.release()


def run_all_async(only_due: bool = False) -> bool:
    if run_state["running"]:
        return False
    threading.Thread(target=run_all, kwargs={"only_due": only_due}, name="literature-run", daemon=True).start()
    return True


_sched: threading.Thread | None = None
_stop = threading.Event()


def start_scheduler() -> None:
    global _sched
    if not get_settings().literature_auto_update or (_sched and _sched.is_alive()):
        return
    _stop.clear()

    def loop() -> None:
        if _stop.wait(20):  # let the backend finish starting
            return
        while True:
            try:
                run_all(only_due=True)
            except Exception as e:  # noqa: BLE001
                log.warning("Literature update failed: %s", e)
            if _stop.wait(1800):
                return
    _sched = threading.Thread(target=loop, name="literature-scheduler", daemon=True)
    _sched.start()


def stop_scheduler() -> None:
    _stop.set()


# ------------------------------------------------------------------------------------------ connection check
def selftest() -> list[dict[str, Any]]:
    out = []
    checks = [("Europe PMC", lambda: search_epmc("neurosurgery", None, None, limit=1, fields="all")),
              ("PubMed", lambda: search_pubmed("neurosurgery", None, None, limit=1, fields="all"))]
    for name, fn in checks:
        t0 = time.monotonic()
        try:
            n = len(fn())
            out.append({"source": name, "ok": n > 0, "ms": round((time.monotonic() - t0) * 1000),
                        "detail": "reachable" if n else "reachable, but returned no records"})
        except SourceError as e:
            out.append({"source": name, "ok": False, "ms": round((time.monotonic() - t0) * 1000), "detail": str(e)})
    return out


# ------------------------------------------------------------------------------------------ open access -> library
def _safe_name(s: str, n: int = 120) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:n].rstrip(" .") or "article"


def open_access_folder() -> Path:
    p = get_settings().data_dir / get_settings().open_access_folder_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def add_to_library(pub_id: int) -> dict[str, Any]:
    """Download an open-access PDF into the 'Open-access articles' library folder and register that folder."""
    from .paths import normalize

    with session() as c:
        r = c.execute("SELECT * FROM publications WHERE id=?", (pub_id,)).fetchone()
    if r is None:
        raise KeyError(pub_id)
    if not r["is_oa"] or not r["oa_pdf_url"]:
        raise SourceError("This article is not open access; only open-access PDFs can be added automatically.")
    if r["library_path"] and Path(r["library_path"]).exists():
        return {"path": r["library_path"], "already": True}
    folder = open_access_folder()
    year = (r["pub_date"] or "")[:4]
    first_author = (r["authors"] or "").split(",")[0].strip()
    name = _safe_name(" - ".join(x for x in [year, first_author, r["title"]] if x)) + ".pdf"
    dest = folder / name
    with _client() as c, c.stream("GET", r["oa_pdf_url"]) as resp:
        if resp.status_code >= 400:
            raise SourceError(f"download failed: HTTP {resp.status_code}")
        tmp = dest.with_suffix(".part")
        size = 0
        try:
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > 150 * 1024 * 1024:
                        raise SourceError("file larger than 150 MB")
                    fh.write(chunk)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    head = tmp.read_bytes()[:5]
    if head != b"%PDF-":
        tmp.unlink(missing_ok=True)
        raise SourceError("the source returned a web page instead of a PDF; open the article link instead")
    tmp.replace(dest)
    with session() as c:
        c.execute("UPDATE publications SET library_path=?, saved=1 WHERE id=?", (normalize(dest), pub_id))
        fp = normalize(folder)
        if not c.execute("SELECT 1 FROM folders WHERE path=?", (fp,)).fetchone():
            c.execute("INSERT INTO folders(path, label, added_at) VALUES (?,?,?)",
                      (fp, get_settings().open_access_folder_name, now_iso()))
        audit(c, "literature.added_to_library", f"{r['doi'] or r['pmid']} -> {dest}")
    return {"path": normalize(dest), "already": False}


def metadata_for_path(conn, path: str) -> dict[str, Any] | None:
    """Bibliographic metadata for a library file that came from the literature module."""
    r = conn.execute("SELECT * FROM publications WHERE library_path=?", (path,)).fetchone()
    if r is None:
        return None
    return {"title": r["title"], "authors": r["authors"], "year": int(r["pub_date"][:4]) if r["pub_date"] else None,
            "publisher": r["journal"], "isbn": None}
