"""
Shared mutual exclusion for heavy document processing (MVP, no Redis/Celery).

The lock MUST work across processes/containers (dm-api + dm-bot), so it's stored
in SQLite on a shared volume (e.g. ./data -> /app/data).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Literal

from src.shared.logging_events import log_event

logger = logging.getLogger(__name__)

Channel = Literal["web", "telegram"]

WEB_BUSY_MESSAGE = (
    "Сервис временно занят обработкой другого запроса. Повторите попытку через 1–2 минуты."
)
TELEGRAM_BUSY_MESSAGE = (
    "⏳ Сервис сейчас обрабатывает другой документ. Попробуйте ещё раз чуть позже."
)

DEFAULT_LOCK_DB_PATH = os.getenv("DOCUMIND_PROCESSING_LOCK_DB", "data/processing_lock.sqlite3")
DEFAULT_STALE_SECONDS = int(os.getenv("DOCUMIND_PROCESSING_LOCK_STALE_SECONDS", "3600"))


def _db_path() -> Path:
    return Path(DEFAULT_LOCK_DB_PATH)


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=0.25, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processing_lock (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            is_busy INTEGER NOT NULL,
            lock_token TEXT,
            trace_id TEXT,
            scenario_type TEXT,
            interface_type TEXT,
            started_at REAL
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO processing_lock (id, is_busy)
        VALUES (1, 0)
        """
    )


def try_acquire_processing(
    *,
    channel: Channel,
    trace_id: str | None,
    user_id: int | None,
    scenario_type: str | None = None,
) -> str | None:
    """Try to acquire the global processing lock. Returns lock_token or None."""
    interface_type = channel
    now = time.time()
    lock_token = str(uuid.uuid4())

    log_event(
        logger,
        event="lock_check",
        stage="GATE",
        status="start",
        interface_type=interface_type,
        trace_id=trace_id,
        user_id=user_id,
        scenario_type=scenario_type,
    )

    try:
        with _connect() as conn:
            _ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT is_busy, started_at FROM processing_lock WHERE id = 1"
            ).fetchone()
            is_busy = int(row["is_busy"]) if row else 0
            started_at = float(row["started_at"]) if row and row["started_at"] is not None else None

            stale = False
            if is_busy and started_at is not None:
                stale = (now - started_at) > float(DEFAULT_STALE_SECONDS)

            if is_busy and not stale:
                conn.execute("ROLLBACK;")
                log_event(
                    logger,
                    event="lock_busy",
                    stage="GATE",
                    status="reject",
                    interface_type=interface_type,
                    trace_id=trace_id,
                    user_id=user_id,
                    scenario_type=scenario_type,
                )
                return None

            conn.execute(
                """
                UPDATE processing_lock
                SET is_busy = 1,
                    lock_token = ?,
                    trace_id = ?,
                    scenario_type = ?,
                    interface_type = ?,
                    started_at = ?
                WHERE id = 1
                """,
                (lock_token, trace_id, scenario_type, interface_type, now),
            )
            conn.execute("COMMIT;")
    except sqlite3.Error as exc:
        log_event(
            logger,
            event="lock_acquire_failed",
            stage="GATE",
            status="error",
            interface_type=interface_type,
            trace_id=trace_id,
            user_id=user_id,
            scenario_type=scenario_type,
            reason=str(exc),
        )
        return None

    log_event(
        logger,
        event="lock_acquired",
        stage="GATE",
        status="success",
        interface_type=interface_type,
        trace_id=trace_id,
        user_id=user_id,
        scenario_type=scenario_type,
        lock_token=lock_token,
    )
    return lock_token


def release_processing(
    *,
    channel: Channel,
    trace_id: str | None,
    user_id: int | None,
    lock_token: str | None,
    scenario_type: str | None = None,
) -> None:
    interface_type = channel
    if not lock_token:
        log_event(
            logger,
            event="lock_release_skipped",
            stage="GATE",
            status="error",
            interface_type=interface_type,
            trace_id=trace_id,
            user_id=user_id,
            scenario_type=scenario_type,
            reason="missing_token",
        )
        return

    try:
        with _connect() as conn:
            _ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT lock_token, is_busy FROM processing_lock WHERE id = 1"
            ).fetchone()
            current_token = row["lock_token"] if row else None
            is_busy = int(row["is_busy"]) if row else 0
            if not is_busy or not current_token or current_token != lock_token:
                conn.execute("ROLLBACK;")
                log_event(
                    logger,
                    event="lock_release_skipped",
                    stage="GATE",
                    status="error",
                    interface_type=interface_type,
                    trace_id=trace_id,
                    user_id=user_id,
                    scenario_type=scenario_type,
                    lock_token=lock_token,
                    reason="token_mismatch_or_not_locked",
                )
                return
            conn.execute(
                """
                UPDATE processing_lock
                SET is_busy = 0,
                    lock_token = NULL,
                    trace_id = NULL,
                    scenario_type = NULL,
                    interface_type = NULL,
                    started_at = NULL
                WHERE id = 1
                """,
            )
            conn.execute("COMMIT;")
    except sqlite3.Error as exc:
        log_event(
            logger,
            event="lock_release_failed",
            stage="GATE",
            status="error",
            interface_type=interface_type,
            trace_id=trace_id,
            user_id=user_id,
            scenario_type=scenario_type,
            lock_token=lock_token,
            reason=str(exc),
        )
        return

    log_event(
        logger,
        event="lock_released",
        stage="GATE",
        status="success",
        interface_type=interface_type,
        trace_id=trace_id,
        user_id=user_id,
        scenario_type=scenario_type,
        lock_token=lock_token,
    )


__all__ = [
    "Channel",
    "TELEGRAM_BUSY_MESSAGE",
    "WEB_BUSY_MESSAGE",
    "try_acquire_processing",
    "release_processing",
    "DEFAULT_LOCK_DB_PATH",
]
