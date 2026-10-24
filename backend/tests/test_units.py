from app.services import chunker, metadata, pagelabels, search, synonyms


def test_edition_year_isbn_from_front_matter():
    m = metadata.detect("random_scan_001", {"title": "Microsoft Word - draft.doc"},
                        "Handbook of Neurosurgery\nNinth Edition\nCopyright © 2019 Thieme\nISBN 978-1-68420-057-3")
    assert m.values["edition"] == "9th" and m.sources["edition"] == "front_matter"
    assert m.values["year"] == 2019
    assert m.values["isbn"] == "9781684200573"
    assert m.values["publisher"] == "Thieme"
    # junk embedded title rejected -> filename used, with provenance
    assert m.sources["title"] == "filename"


def test_invalid_isbn_rejected():
    m = metadata.detect("x", {}, "ISBN 978-1-68420-057-9")
    assert "isbn" not in m.values


def test_filename_edition_and_cleaning():
    m = metadata.detect("Youmans_and_Winn_Neurological_Surgery_8th_ed_2022 (z-lib.org)", {}, "")
    assert m.values["edition"] == "8th"
    assert m.values["year"] == 2022
    assert "z-lib" not in m.values["title"]


def test_nothing_invented_when_absent():
    m = metadata.detect("Notes", {}, "Plain text with no bibliographic data.")
    for k in ("edition", "year", "isbn", "publisher", "authors"):
        assert k not in m.values


def _pages(n, offset, start_numbering=1, plate_at=None):
    out = []
    for i in range(n):
        printed = i + 1 + offset
        if plate_at is not None and i >= plate_at:
            printed -= 1  # an unnumbered plate inserted at plate_at
        if plate_at is not None and i == plate_at:
            out.append("Figure plate without number")
            continue
        out.append(f"Header line\nsome text\n{printed}" if printed >= start_numbering else "Preface\ntext")
    return out


def test_inferred_offset_front_matter():
    texts = _pages(40, -6)
    offsets = pagelabels.infer_offsets(texts)
    assert offsets[10] == -6          # physical p.11 -> printed 5
    assert offsets[0] is None         # front matter (printed < 1) gets no label


def test_inferred_offset_handles_inserted_plate():
    texts = _pages(60, 0, plate_at=30)
    labels, mode = pagelabels.resolve_labels([""] * 60, texts)
    assert mode == "inferred"
    assert labels[20] == ("21", "inferred")
    assert labels[45] == ("45", "inferred")


def test_no_labels_without_evidence():
    labels, mode = pagelabels.resolve_labels([""] * 20, ["no numbers here"] * 20)
    assert mode == "none" and all(lbl is None for lbl, _ in labels)


def test_chunks_respect_size_and_keep_text():
    text = ("Sentence number one is here. " * 200).strip()
    chunks = chunker.chunk_page(text, 500, 80)
    assert all(len(c) <= 600 for c in chunks)
    assert "Sentence number one" in chunks[0]


def test_chapter_map_uses_level2_when_level1_is_wrapper():
    toc = [(1, "Book", 0)] + [(2, f"Chapter {i}", i * 5) for i in range(1, 7)] + [(3, "Sub", 12)]
    cm = chunker.chapter_map(toc, 40)
    assert cm[7][0] == "Chapter 1"
    assert cm[12] == ("Chapter 2", "Sub")


def test_query_parse_synonyms_and_stopwords():
    pq = search.parse("What is the management of acoustic neuroma with brainstem compression?")
    flat = [t.lower() for g in pq.groups for t in g]
    assert "vestibular schwannoma" in flat
    assert "what" not in flat and "the" not in flat
    # 2-letter abbreviation not injected as an expansion of the full term
    assert "vs" not in flat


def test_abbreviation_typed_by_user_is_kept():
    assert "VS" in synonyms.expand("vs") and "vestibular schwannoma" in synonyms.expand("VS")


def test_fts_expression_is_safe():
    pq = search.parse('pterional "OR" approach; DROP TABLE x -- * ')
    expr = search.to_fts(pq, "AND")
    assert ";" not in expr and "--" not in expr


def test_running_headers_and_page_numbers_stripped():
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]
    pages = [f"Chapter 12 Vestibular Schwannoma\nBody {words[i]} about the facial nerve.\n{i + 100}" for i in range(10)]
    out = chunker.strip_running_lines(pages)
    assert all("Chapter 12" not in p and not p.rstrip().endswith(str(i + 100)) for i, p in enumerate(out))
    assert "facial nerve" in out[3]


def test_short_documents_keep_edge_lines():
    out = chunker.strip_running_lines(["Heading\nText", "Heading\nText"])
    assert out[0].startswith("Heading")
