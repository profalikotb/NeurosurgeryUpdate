"""Bibliographic metadata detection with explicit provenance.

Rule: a field is filled only when it is literally present in a source (embedded PDF metadata, the
file name, or the book's front matter). Nothing is guessed. Every field records where it came from,
and a document is only marked `metadata_verified` after the user confirms it in the UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ORDINALS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "eleventh": "11th", "twelfth": "12th",
}
_ORD_WORDS = "|".join(ORDINALS)

RE_EDITION_NUM = re.compile(r"\b(\d{1,2})\s?(?:st|nd|rd|th)\s*(?:ed\b\.?|edn\b\.?|edition\b)", re.I)
RE_EDITION_WORD = re.compile(rf"\b({_ORD_WORDS})\s+edition\b", re.I)
RE_EDITION_SHORT = re.compile(r"(?:^|[\s_\-(\[])(?:ed|edn)[\s._-]?(\d{1,2})(?:$|[\s_\-)\]])", re.I)
RE_YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)")
RE_COPYRIGHT_YEAR = re.compile(r"(?:©|\(c\)|copyright)\s*(?:[^\n\d]{0,40})?(19[5-9]\d|20[0-4]\d)", re.I)
RE_ISBN = re.compile(r"ISBN(?:-1[03])?[:\s]*((?:97[89][\s-]?)?(?:\d[\s-]?){9}[\dXx])")
PUBLISHERS = [
    "Thieme", "Elsevier", "Springer", "Wolters Kluwer", "Lippincott", "Oxford University Press",
    "Cambridge University Press", "McGraw", "Wiley", "CRC Press", "Taylor & Francis", "Jaypee",
    "Saunders", "Mosby", "Churchill Livingstone", "Academic Press", "AANS", "CNS",
]
JUNK_TITLES = re.compile(r"^(untitled|microsoft word|document\d*|\d+|scan\d*|print|pdf|book)\b", re.I)


@dataclass
class Meta:
    values: dict[str, str | int | None] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def put(self, key: str, value: str | int | None, src: str) -> None:
        if value in (None, "") or self.values.get(key):
            return
        self.values[key] = value
        self.sources[key] = src


def clean_filename_title(stem: str) -> str:
    s = re.sub(r"[_]+", " ", stem)
    s = re.sub(r"\s*[\[(](?:z-lib[^)\]]*|libgen[^)\]]*|ebook|pdf|www\.[^)\]]+|@\w+)[)\]]", "", s, flags=re.I)
    s = re.sub(r"\s*-\s*(?:z-lib\.org|libgen\.\w+)$", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" -.")
    return s


def _edition_from(text: str) -> str | None:
    m = RE_EDITION_NUM.search(text)
    if m:
        n = int(m.group(1))
        return _ordinal(n)
    m = RE_EDITION_WORD.search(text)
    if m:
        return ORDINALS[m.group(1).lower()]
    return None


def _ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _isbn(text: str) -> str | None:
    m = RE_ISBN.search(text)
    if not m:
        return None
    digits = re.sub(r"[\s-]", "", m.group(1)).upper()
    return digits if len(digits) in (10, 13) and _isbn_valid(digits) else None


def _isbn_valid(d: str) -> bool:
    if len(d) == 10:
        if not d[:9].isdigit():
            return False
        total = sum((10 - i) * int(c) for i, c in enumerate(d[:9]))
        total += 10 if d[9] == "X" else int(d[9]) if d[9].isdigit() else 999
        return total % 11 == 0
    if not d.isdigit():
        return False
    return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d)) % 10 == 0


def detect(stem: str, embedded: dict[str, str] | None, front_matter: str) -> Meta:
    """Order of trust: embedded metadata (if not junk) > front matter > filename."""
    meta = Meta()
    embedded = embedded or {}

    t = (embedded.get("title") or "").strip()
    if t and not JUNK_TITLES.match(t) and len(t) > 3:
        meta.put("title", t, "pdf_metadata")
    a = (embedded.get("author") or "").strip()
    if a and len(a) > 2 and not re.match(r"^(admin|user|owner|unknown)", a, re.I):
        meta.put("authors", a, "pdf_metadata")

    fm = front_matter[:20000]
    meta.put("edition", _edition_from(fm), "front_matter")
    meta.put("isbn", _isbn(fm), "front_matter")
    m = RE_COPYRIGHT_YEAR.search(fm)
    if m:
        meta.put("year", int(m.group(1)), "front_matter")
    for pub in PUBLISHERS:
        if re.search(rf"\b{re.escape(pub)}\b", fm):
            meta.put("publisher", pub, "front_matter")
            break

    cleaned = clean_filename_title(stem)
    meta.put("title", cleaned, "filename")
    meta.put("edition", _edition_from(stem.replace("_", " ")), "filename")
    m = RE_EDITION_SHORT.search(stem)
    if m:
        meta.put("edition", _ordinal(int(m.group(1))), "filename")
    years = RE_YEAR.findall(stem)
    if years:
        meta.put("year", int(years[-1]), "filename")
    return meta


def normalized_title_key(title: str | None, edition: str | None) -> str | None:
    if not title:
        return None
    t = re.sub(r"\b\d{1,2}(st|nd|rd|th)\b|\bedition\b|\bed\b|\d{4}", " ", title.lower())
    t = re.sub(r"[^a-z؀-ۿ]+", " ", t).strip()
    if len(t) < 6:
        return None
    return f"{t}|{edition or ''}"
