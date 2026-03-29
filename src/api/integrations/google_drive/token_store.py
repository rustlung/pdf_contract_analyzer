import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)


class TokenStoreError(Exception):
    """Raised when token storage fails."""


def _default_db_path() -> Path:
    path = os.getenv("DOCUMIND_DRIVE_TOKEN_DB", "").strip()
    if path:
        return Path(path)
    return Path("data/google_drive_tokens.sqlite3")


@dataclass(slots=True)
class StoredTokenRecord:
    telegram_user_id: int
    credentials_json: str
    updated_at: str


class SQLiteTokenStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS drive_tokens (
                    telegram_user_id INTEGER PRIMARY KEY,
                    credentials_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    telegram_user_id INTEGER NOT NULL,
                    code_verifier TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_drive_operations (
                    telegram_user_id INTEGER PRIMARY KEY,
                    scenario_type TEXT NOT NULL,
                    result_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_bytes BLOB NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def save_credentials(self, telegram_user_id: int, creds: Credentials) -> None:
        if not creds.refresh_token:
            # Without refresh_token we can't reliably use Drive later.
            raise TokenStoreError(
                "Refresh token не получен. Убедитесь, что выполнен consent (prompt=consent)."
            )
        payload = creds.to_json()
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO drive_tokens (telegram_user_id, credentials_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    credentials_json=excluded.credentials_json,
                    updated_at=excluded.updated_at
                """,
                (telegram_user_id, payload, updated_at),
            )
            conn.commit()
        logger.info("Drive token saved: telegram_user_id=%s", telegram_user_id)

    def load_credentials(self, telegram_user_id: int) -> Credentials | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT credentials_json FROM drive_tokens WHERE telegram_user_id=?",
                (telegram_user_id,),
            )
            row = cur.fetchone()

        if not row:
            return None
        credentials_json = row[0]
        try:
            data = json.loads(credentials_json)
            return Credentials.from_authorized_user_info(data)
        except Exception as exc:
            raise TokenStoreError("Не удалось прочитать сохраненные OAuth credentials.") from exc

    def is_connected(self, telegram_user_id: int) -> bool:
        creds = self.load_credentials(telegram_user_id)
        return creds is not None and bool(creds.refresh_token)

    def save_oauth_state(self, *, state: str, telegram_user_id: int, code_verifier: str) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO oauth_states (state, telegram_user_id, code_verifier, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(state) DO UPDATE SET
                    telegram_user_id=excluded.telegram_user_id,
                    code_verifier=excluded.code_verifier,
                    created_at=excluded.created_at
                """,
                (state, telegram_user_id, code_verifier, created_at),
            )
            conn.commit()
        logger.info("OAuth state saved: telegram_user_id=%s", telegram_user_id)

    def pop_oauth_code_verifier(self, *, state: str, telegram_user_id: int) -> str | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT code_verifier FROM oauth_states WHERE state=? AND telegram_user_id=?",
                (state, telegram_user_id),
            )
            row = cur.fetchone()
            if row:
                conn.execute(
                    "DELETE FROM oauth_states WHERE state=? AND telegram_user_id=?",
                    (state, telegram_user_id),
                )
                conn.commit()

        return row[0] if row else None

    def save_pending_operation(
        self,
        *,
        telegram_user_id: int,
        scenario_type: str,
        result_type: str,
        filename: str,
        mime_type: str,
        file_bytes: bytes,
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_drive_operations (
                    telegram_user_id, scenario_type, result_type, filename, mime_type, file_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    scenario_type=excluded.scenario_type,
                    result_type=excluded.result_type,
                    filename=excluded.filename,
                    mime_type=excluded.mime_type,
                    file_bytes=excluded.file_bytes,
                    created_at=excluded.created_at
                """,
                (
                    telegram_user_id,
                    scenario_type,
                    result_type,
                    filename,
                    mime_type,
                    file_bytes,
                    created_at,
                ),
            )
            conn.commit()
        logger.info("Pending drive operation saved: telegram_user_id=%s scenario=%s", telegram_user_id, scenario_type)

    def pop_pending_operation(self, telegram_user_id: int) -> dict | None:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT scenario_type, result_type, filename, mime_type, file_bytes, created_at
                FROM pending_drive_operations
                WHERE telegram_user_id=?
                """,
                (telegram_user_id,),
            )
            row = cur.fetchone()
            if row:
                conn.execute(
                    "DELETE FROM pending_drive_operations WHERE telegram_user_id=?",
                    (telegram_user_id,),
                )
                conn.commit()

        if not row:
            return None
        return {
            "scenario_type": row[0],
            "result_type": row[1],
            "filename": row[2],
            "mime_type": row[3],
            "file_bytes": row[4],
            "created_at": row[5],
        }

