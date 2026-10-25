"""Hybrid retrieval with a deterministic fake embedder (no Ollama needed)."""
from __future__ import annotations

import hashlib
import math

import pytest
from conftest import TOKEN, VS_TEXT, make_textbook
from test_library import add_folder, scan, search

qdrant_client = pytest.importorskip("qdrant_client")

from app.services import semantic  # noqa: E402


class FakeEmbedder:
    """Bag-of-concepts embedding: paraphrases sharing concepts land close together."""
    CONCEPTS = [["hearing", "audition", "cochlear", "deafness"], ["facial", "seventh", "vii"],
                ["schwannoma", "neuroma", "tumour", "tumor"], ["meningioma", "dural"], ["spine", "lumbar"]]

    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            v = [float(sum(low.count(w) for w in group)) for group in self.CONCEPTS]
            v.append(int(hashlib.md5(low.encode()).hexdigest(), 16) % 7 / 100)
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


@pytest.fixture()
def sem():
    inst = semantic.SemanticIndex(FakeEmbedder(), client=qdrant_client.QdrantClient(":memory:"))
    semantic.set_instance(inst)
    yield inst
    semantic.set_instance(None)


def test_hybrid_search_fuses_semantic_hits(client, library, sem):
    make_textbook(library / "book.pdf", extra_page_text={5: VS_TEXT})
    add_folder(client, library)
    scan(client)
    # "audition deafness" never appears in the text; only the semantic layer can connect it.
    res = search(client, "audition deafness")
    assert res["semantic"] is True
    assert res["hits"] and res["hits"][0]["page_index"] == 5
    assert res["hits"][0]["match"] == "semantic"
    assert client.get("/api/status", headers=TOKEN).json()["semantic_enabled"] is True
