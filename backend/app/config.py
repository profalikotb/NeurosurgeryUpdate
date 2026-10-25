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

    # Automatic indexing: the library folders are checked every `watch_interval_seconds`; new, changed or
    # removed books trigger an incremental scan. Files modified less than `min_file_age_seconds` ago are
    # treated as still downloading (Telegram Desktop writes directly to the final file name) and skipped.
    watch_enabled: bool = True
    watch_interval_seconds: int = 90
    min_file_age_seconds: int = 45

    # Scientific literature (Europe PMC = PubMed/MEDLINE + PubMed Central + NCBI Bookshelf; PubMed as fallback)
    literature_auto_update: bool = True        # daily discovery for enabled topics while the backend runs
    literature_update_hours: int = 24
    literature_initial_days: int = 30          # window for a topic's first run
    literature_timeout_seconds: int = 25
    contact_email: str | None = None           # optional; NCBI asks automated tools to identify themselves
    open_access_folder_name: str = "Open-access articles"

    # Google Drive (cloud mode). Give the service-account key either inline (JSON or base64 JSON) or as a file;
    # on Render a Secret File named google-service-account.json is found automatically.
    gdrive_service_account_json: str | None = None
    gdrive_service_account_file: str | None = None
    # Folders on the server's own disk. Disable on a cloud server, where only Google Drive folders make sense.
    local_folders_enabled: bool = True

    # Uploading books from the browser (phone) into <data_dir>/<uploads_folder_name>.
    uploads_enabled: bool = True
    uploads_folder_name: str = "Uploaded books"

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
