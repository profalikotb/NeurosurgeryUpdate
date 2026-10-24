from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .db import init_db
from .routers import documents, library, search, system
from .security import require_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.api_token.startswith("change-me"):
        logging.getLogger("academy").warning("ACADEMY_API_TOKEN is the default value - set a random token in backend/.env")
    init_db()
    yield


if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    # Serverless hosts have no access to the books on your PC, no persistent disk for the index and no
    # background workers. Fail loudly and clearly instead of crashing with FUNCTION_INVOCATION_FAILED.
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Neurosurgery AI Academy API (unsupported host)")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
    def unsupported(path: str):
        return JSONResponse(status_code=503, content={"detail": (
            "The backend cannot run on Vercel/serverless: it must run on the computer that holds the books. "
            "Deploy only the 'frontend' folder to Vercel and connect it to your PC through a tunnel (docs/VERCEL.md).")})
else:
    app = FastAPI(title="Prof. Ali Kotb Neurosurgery AI Academy API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.public)
    protected = [Depends(require_token)]
    for r in (system.router, library.router, documents.router, search.router):
        app.include_router(r, dependencies=protected)
