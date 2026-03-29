"""
Filesystem-backed store for Web UI processing results (session token -> payload + optional docx file).
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _base_dir() -> Path:
    raw = os.getenv("DOCUMIND_WEB_RESULT_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path("data/web_ui_results")


def _token_path(token: str) -> Path:
    if not _SAFE_TOKEN_RE.match(token):
        raise ValueError("Invalid result token")
    return _base_dir() / token


def create_token() -> str:
    return secrets.token_urlsafe(32)


def save_meta(token: str, meta: dict[str, Any]) -> None:
    d = _token_path(token)
    d.mkdir(parents=True, exist_ok=True)
    meta_path = d / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Web result saved: token=%s type=%s", token, meta.get("kind"))


def save_docx_bytes(token: str, docx_bytes: bytes, filename: str = "output.docx") -> None:
    d = _token_path(token)
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(docx_bytes)


def update_drive_web_link(token: str, web_link: str | None) -> None:
    meta = load_meta(token)
    if not meta:
        logger.warning("Web result token not found for drive link update: %s", token)
        return
    meta["drive_web_link"] = web_link
    save_meta(token, meta)


def load_meta(token: str) -> dict[str, Any] | None:
    try:
        p = _token_path(token) / "meta.json"
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load web result meta")
        return None


def docx_path(token: str, filename: str = "output.docx") -> Path | None:
    p = _token_path(token) / filename
    return p if p.is_file() else None
