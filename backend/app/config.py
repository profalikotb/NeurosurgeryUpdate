from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All settings are read from environment variables or backend/.env (prefix ACADEMY_)."""

    model_config = SettingsConfigDict(env_prefix="ACADEMY_", env_file=BACKEND_DIR / ".env", extra="ignore")

    # Storage
    data_dir: Path = BACKEND_DIR / "data"

    # Security: shared secret between the Next.js server and this API. Never sent to the browser.
    api_token: str = "change-me-to-a-long-random-string"
    # Bind address is set in the start scripts; keep 127.0.0.1 unless behind a reverse proxy / VPN.
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Ingestion
    supported_extensions: list[str] = [".pdf", ".epub", ".docx", ".txt", ".md", ".mobi", ".fb2"]
    max_file_mb: int = 1500
    chunk_chars: int = 1400
    chunk_overlap: int = 200
    # A page with fewer extracted characters than this is treated as image-only (candidate for OCR).
    min_text_chars_per_page: int = 40

    # OCR (requires Tesseract installed; see docs/WINDOWS_INSTALL.md)
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    ocr_dpi: int = 200
    tessdata_prefix: str | None = None
    # Safety valve: OCR is slow (~2-6 s/page). Books needing more than this are flagged, not OCRed.
    ocr_max_pages_per_document: int = 1200

    # Render
    page_image_dpi: int = 130

    # Optional semantic (vector) search, fused with BM25 via reciprocal-rank fusion.
    # Requires: pip install -r requirements-semantic.txt and a local Ollama with an embedding model.
    semantic_enabled: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_batch: int = 32
    qdrant_url: str | None = None          # e.g. http://127.0.0.1:6333 ; None = embedded local Qdrant in data_dir

    @property
    def db_path(self) -> Path:
        return self.data_dir / "academy.sqlite3"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
