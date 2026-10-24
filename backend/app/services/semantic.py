"""Optional semantic layer: local embeddings (Ollama) + Qdrant (embedded or server).

Everything stays on the machine: Ollama runs locally and embedded Qdrant writes to data_dir/qdrant.
If disabled or unavailable, search silently uses BM25 only and the API reports semantic=false.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Protocol

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)
COLLECTION = "chunks"


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(self, url: str, model: str):
        self.url, self.model = url.rstrip("/"), model

    def embed(self, texts: list[str]) -> list[list[float]]:
        # nomic-embed-text expects task prefixes; harmless for other models.
        r = httpx.post(f"{self.url}/api/embed", json={"model": self.model, "input": texts}, timeout=120)
        r.raise_for_status()
        return r.json()["embeddings"]


class SemanticIndex:
    def __init__(self, embedder: Embedder, client=None):
        from qdrant_client import QdrantClient

        s = get_settings()
        self.embedder = embedder
        if client is not None:
            self.client = client
        elif s.qdrant_url:
            self.client = QdrantClient(url=s.qdrant_url)
        else:
            self.client = QdrantClient(path=str(s.data_dir / "qdrant"))
        self._dim: int | None = None
        self._remote = client is None and bool(s.qdrant_url)

    def _ensure(self, dim: int) -> None:
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        if self._dim == dim:
            return
        if not self.client.collection_exists(COLLECTION):
            self.client.create_collection(COLLECTION, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
            if self._remote:  # embedded Qdrant ignores payload indexes
                self.client.create_payload_index(COLLECTION, "document_id", PayloadSchemaType.INTEGER)
        self._dim = dim

    def delete_document(self, doc_id: int) -> None:
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        if not self.client.collection_exists(COLLECTION):
            return
        self.client.delete(COLLECTION, points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))])))

    def index_document(self, conn: sqlite3.Connection, doc_id: int, batch: int = 32) -> int:
        from qdrant_client.models import PointStruct

        self.delete_document(doc_id)
        rows = conn.execute("SELECT id, text FROM chunks WHERE document_id=? ORDER BY id", (doc_id,)).fetchall()
        n = 0
        for i in range(0, len(rows), batch):
            part = rows[i:i + batch]
            vecs = self.embedder.embed(["search_document: " + r["text"] for r in part])
            self._ensure(len(vecs[0]))
            self.client.upsert(COLLECTION, points=[
                PointStruct(id=r["id"], vector=v, payload={"document_id": doc_id}) for r, v in zip(part, vecs, strict=True)])
            n += len(part)
        return n

    def query(self, q: str, limit: int = 40, doc_ids: list[int] | None = None) -> list[int]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        if not self.client.collection_exists(COLLECTION):
            return []
        vec = self.embedder.embed(["search_query: " + q])[0]
        flt = Filter(must=[FieldCondition(key="document_id", match=MatchAny(any=doc_ids))]) if doc_ids else None
        res = self.client.query_points(COLLECTION, query=vec, limit=limit, query_filter=flt)
        return [int(p.id) for p in res.points]


_instance: SemanticIndex | None = None
_failed = False


def get() -> SemanticIndex | None:
    global _instance, _failed
    s = get_settings()
    if _instance is not None:
        return _instance
    if not s.semantic_enabled or _failed:
        return None
    if _instance is None:
        try:
            _instance = SemanticIndex(OllamaEmbedder(s.ollama_url, s.embedding_model))
        except Exception as e:  # qdrant-client missing, etc.
            log.warning("Semantic search unavailable: %s", e)
            _failed = True
            return None
    return _instance


def set_instance(inst: SemanticIndex | None) -> None:
    """Test hook."""
    global _instance, _failed
    _instance, _failed = inst, False
