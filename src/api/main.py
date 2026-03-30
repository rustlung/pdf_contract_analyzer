import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from dotenv import load_dotenv

from src.api.routers.google_drive import router as google_drive_router
from src.api.routers.web_ui import STATIC_DIR, router as web_ui_router

load_dotenv()


def _configure_logging_from_env() -> None:
    """
    Ensure application INFO logs (e.g. processing_metrics) reach Docker/uvicorn output.

    If the root logger has no handlers, Python uses lastResort (WARNING only) — then
    `logger.info` from `src.*` is dropped. We attach a StreamHandler to logger `src`
    so app logs always have a path to stderr.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = logging.Formatter("%(levelname)s:%(name)s:%(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers:
        h.setLevel(level)

    src_log = logging.getLogger("src")
    src_log.setLevel(level)
    if not src_log.handlers:
        _h = logging.StreamHandler(sys.stderr)
        _h.setLevel(level)
        _h.setFormatter(fmt)
        src_log.addHandler(_h)
    else:
        for h in src_log.handlers:
            h.setLevel(level)
    # Avoid duplicate lines if root also prints the same record.
    src_log.propagate = False

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(level)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _configure_logging_from_env()
    yield


app = FastAPI(
    title="DocuMind API",
    version="0.1.0",
    lifespan=_lifespan,
    root_path=os.getenv("DOCUMIND_ROOT_PATH", ""),
)

_session_secret = os.getenv("SESSION_SECRET", "").strip() or "dev-change-me-set-SESSION_SECRET"
app.add_middleware(SessionMiddleware, secret_key=_session_secret, max_age=14 * 24 * 3600, same_site="lax")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(web_ui_router)
app.include_router(google_drive_router, prefix="/google-drive", tags=["google-drive"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ping")
def ping() -> dict[str, str]:
    return {"message": "pong"}
