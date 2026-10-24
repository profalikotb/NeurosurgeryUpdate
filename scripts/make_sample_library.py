"""Builds a small DEMONSTRATION library so the system can be tried before indexing real textbooks.

The text is original teaching-note material written for this demo; it is not copied from any textbook
and it is not a clinical reference. Usage:

    python scripts/make_sample_library.py  sample_library
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

TITLE = "Posterior Fossa Teaching Notes (Demonstration Content)"
FRONT = 3  # roman-numbered front matter pages

CHAPTERS = [
    ("Chapter 1. Cerebellopontine Angle Anatomy", [
        ("Neurovascular relationships",
         "The cerebellopontine angle is bounded by the petrous bone, the cerebellum and the pons. The facial and "
         "vestibulocochlear nerves cross it toward the internal auditory canal, with the anterior inferior cerebellar "
         "artery (AICA) frequently looping near the meatus. At the fundus of the canal the transverse crest separates "
         "superior and inferior compartments; Bill's bar separates the facial nerve anteriorly from the superior "
         "vestibular nerve posteriorly."),
        ("Venous anatomy",
         "The superior petrosal vein (Dandy's vein) drains into the superior petrosal sinus. Sacrificing it is usually "
         "tolerated, but venous infarction of the cerebellum or brainstem has been reported, so preservation is "
         "preferred when it does not compromise exposure."),
    ]),
    ("Chapter 2. Vestibular Schwannoma", [
        ("Grading and natural history",
         "Vestibular schwannomas arise from Schwann cells of the vestibular nerve. Size is described by the extrameatal "
         "diameter; the Koos grading system ranges from intracanalicular tumours (grade I) to tumours compressing the "
         "brainstem with displacement of the fourth ventricle (grade IV). Many small tumours do not grow, which "
         "supports serial MRI surveillance for selected patients."),
        ("Approach selection",
         "Approach selection weighs tumour size, hearing status and surgeon experience. The retrosigmoid approach "
         "allows attempts at hearing preservation and wide exposure of the cerebellopontine angle. The translabyrinthine "
         "approach sacrifices residual hearing but permits early identification of the facial nerve at the fundus with "
         "minimal cerebellar retraction. The middle fossa approach suits small intracanalicular tumours with useful "
         "hearing. Large tumours with brainstem compression generally favour microsurgical decompression, and planned "
         "subtotal resection followed by radiosurgery is an accepted strategy to protect facial nerve function."),
        ("Facial nerve outcome",
         "Facial nerve function is reported with the House-Brackmann scale. Continuous intraoperative facial nerve "
         "monitoring and a low stimulation threshold at the brainstem at the end of resection are associated with "
         "better postoperative function."),
    ]),
    ("Chapter 3. Petroclival Meningioma", [
        ("Clinical problem",
         "Petroclival meningiomas arise medial to the trigeminal nerve along the upper two thirds of the clivus. Cranial "
         "nerves III to XII, the basilar artery and its perforators are at risk. Treatment goals balance cranial nerve "
         "preservation against extent of resection; residual tumour adherent to the brainstem may be observed or treated "
         "with radiosurgery."),
        ("Approaches",
         "Options include the retrosigmoid approach, the anterior petrosal (Kawase) approach for upper clival tumours "
         "with supratentorial extension, and the posterior petrosal approaches. Combined or staged approaches are "
         "considered for extensive tumours crossing the tentorium."),
    ]),
]


def build(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    toc = []

    def new_page(lines: list[tuple[str, float]], printed: int | None, header: str = ""):
        page = doc.new_page(width=420, height=595)  # A5-ish
        if header:
            page.insert_text((40, 32), header, fontsize=7.5, color=(0.4, 0.45, 0.5))
        tw = pymupdf.TextWriter(page.rect)
        y = 60
        for text, size in lines:
            rect = pymupdf.Rect(40, y, 380, 560)
            rest = tw.fill_textbox(rect, text, fontsize=size, font=pymupdf.Font("tiro" if size < 12 else "tibo"))
            used = (len(text) - sum(len(r) for r in rest)) if rest else len(text)
            y += max(size * 2.2, (used / 75) * size * 1.45) + 10
        tw.write_text(page)
        if printed:
            page.insert_text((205, 575), str(printed), fontsize=8)
        return page

    new_page([(TITLE, 16), ("First Edition", 11), ("Demonstration material for software testing. "
              "Not a clinical reference. Copyright 2026 Prof. Ali Kotb Neurosurgery AI Academy.", 9)], None)
    new_page([("Preface", 13), ("These notes exist only to demonstrate indexing, page citation and search in the "
              "Neurosurgery AI Academy. Replace them with your own textbooks.", 10)], None)
    new_page([("Contents", 13)] + [(c[0], 10) for c in CHAPTERS], None)
    toc.append([1, "Front Matter", 1])
    printed = 1
    for ch_title, sections in CHAPTERS:
        toc.append([1, ch_title, doc.page_count + 1])
        for k, (sec, body) in enumerate(sections):
            toc.append([2, sec, doc.page_count + 1])
            lines = ([(ch_title, 14)] if k == 0 else []) + [(sec, 12), (body, 10)]
            new_page(lines, printed, header=f"{ch_title}")
            printed += 1
    doc.set_toc(toc)
    doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                         {"startpage": FRONT, "prefix": "", "style": "D", "firstpagenum": 1}])
    doc.set_metadata({"title": TITLE, "author": "Neurosurgery AI Academy (demo)"})
    path = out / "Posterior Fossa Teaching Notes - DEMO.pdf"
    doc.save(str(path), garbage=3, deflate=True)
    (out / "Cavernous sinus notes - DEMO.md").write_text(
        "# Cavernous sinus\n\nThe abducens nerve runs within the sinus lateral to the internal carotid artery, while "
        "the oculomotor, trochlear, ophthalmic and maxillary nerves lie in the lateral wall.\n\n"
        "# Parkinson's triangle\n\nThe triangle between the trochlear and ophthalmic nerves gives access to the "
        "cavernous segment of the internal carotid artery.\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_library")
    print(f"Sample library written to {build(target).parent.resolve()}")
