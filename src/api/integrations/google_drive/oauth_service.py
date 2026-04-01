import logging
import os
import urllib.request
from urllib.parse import quote_plus
from urllib.error import URLError
from dataclasses import dataclass

from google_auth_oauthlib.flow import Flow

from src.api.integrations.google_drive.drive_service import (
    DriveSaveResult,
    GoogleDriveServiceError,
    save_file_to_user_drive,
)
from src.api.integrations.google_drive.state import OAuthState, OAuthStateError, build_oauth_state, parse_and_verify_oauth_state
from src.api.integrations.google_drive.token_store import SQLiteTokenStore, TokenStoreError
from src.shared.logging_events import log_event

logger = logging.getLogger(__name__)

DEFAULT_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GoogleDriveOAuthError(Exception):
    """Raised when Google Drive OAuth flow fails."""


@dataclass(slots=True)
class OAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str]


@dataclass(slots=True)
class PendingDriveOperation:
    telegram_user_id: int
    scenario_type: str
    result_type: str
    filename: str
    mime_type: str
    file_bytes: bytes


def _load_oauth_config(*, client: str | None = None) -> OAuthConfig:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    # Backward compatible: if new vars are missing, fall back to GOOGLE_OAUTH_REDIRECT_URI.
    legacy_redirect = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    redirect_web = os.getenv("GOOGLE_OAUTH_REDIRECT_URI_WEB", "").strip()
    redirect_bot = os.getenv("GOOGLE_OAUTH_REDIRECT_URI_BOT", "").strip()

    is_web = str(client or "").strip().lower() == "web"
    if is_web:
        redirect_uri = redirect_web or legacy_redirect
    else:
        redirect_uri = redirect_bot or legacy_redirect
    scopes = os.getenv("GOOGLE_OAUTH_SCOPES", "").strip()

    if not client_id or not client_secret or not redirect_uri:
        raise GoogleDriveOAuthError(
            "Не заданы env-переменные Google OAuth: "
            "GOOGLE_OAUTH_CLIENT_ID/SECRET и redirect URI "
            "(GOOGLE_OAUTH_REDIRECT_URI_WEB/BOT или GOOGLE_OAUTH_REDIRECT_URI)."
        )
    scope_list = DEFAULT_SCOPES if not scopes else [s.strip() for s in scopes.split(",") if s.strip()]
    return OAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scope_list,
    )


def _build_flow(config: OAuthConfig, state: str | None = None) -> Flow:
    client_config = {
        "web": {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=config.scopes,
        state=state,
    )
    flow.redirect_uri = config.redirect_uri
    return flow


def build_authorization_url(
    telegram_user_id: int,
    *,
    trace_id: str | None = None,
    client: str = "telegram",
    web_result_token: str | None = None,
) -> str:
    config = _load_oauth_config(client=client)
    state = build_oauth_state(
        telegram_user_id,
        trace_id=trace_id,
        client=client,
        web_result_token=web_result_token,
    )
    flow = _build_flow(config=config, state=state)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    # Persist PKCE verifier for this state; required to exchange code.
    if getattr(flow, "code_verifier", None):
        SQLiteTokenStore().save_oauth_state(
            state=state,
            telegram_user_id=telegram_user_id,
            code_verifier=flow.code_verifier,
        )
    log_event(
        logger,
        event="oauth_started",
        user_id=telegram_user_id,
        trace_id=trace_id,
        stage="OAUTH",
        status="start",
    )
    return auth_url


def exchange_code_and_store_tokens(*, code: str, state: str) -> OAuthState:
    try:
        state_data = parse_and_verify_oauth_state(state)
    except OAuthStateError as exc:
        raise GoogleDriveOAuthError(str(exc)) from exc

    config = _load_oauth_config(client=state_data.client)
    flow = _build_flow(config=config, state=state)
    store = SQLiteTokenStore()
    code_verifier = store.pop_oauth_code_verifier(state=state, telegram_user_id=state_data.telegram_user_id)
    try:
        if code_verifier:
            flow.fetch_token(code=code, code_verifier=code_verifier)
        else:
            flow.fetch_token(code=code)
    except Exception as exc:
        log_event(
            logger,
            event="oauth_callback_failed",
            user_id=state_data.telegram_user_id,
            trace_id=state_data.trace_id,
            stage="OAUTH",
            status="error",
            reason=str(exc),
        )
        logger.exception("Drive OAuth token exchange failed")
        raise GoogleDriveOAuthError(f"Не удалось обменять code на токен: {exc}") from exc

    creds = flow.credentials
    try:
        store.save_credentials(state_data.telegram_user_id, creds)
    except TokenStoreError as exc:
        raise GoogleDriveOAuthError(str(exc)) from exc

    log_event(
        logger,
        event="oauth_callback_success",
        user_id=state_data.telegram_user_id,
        trace_id=state_data.trace_id,
        stage="OAUTH",
        status="success",
    )
    return state_data


def is_drive_connected(telegram_user_id: int) -> bool:
    try:
        store = SQLiteTokenStore()
        connected = store.is_connected(telegram_user_id)
    except Exception as exc:
        raise GoogleDriveOAuthError(f"Не удалось проверить статус Google Drive: {exc}") from exc
    logger.info("Drive status checked: telegram_user_id=%s connected=%s", telegram_user_id, connected)
    return connected


def save_file_for_user(
    *,
    telegram_user_id: int,
    filename: str,
    file_bytes: bytes,
    mime_type: str,
) -> DriveSaveResult:
    store = SQLiteTokenStore()
    creds = store.load_credentials(telegram_user_id)
    if not creds:
        raise GoogleDriveOAuthError("Google Drive не подключен для этого пользователя.")

    try:
        result = save_file_to_user_drive(
            creds,
            filename=filename,
            file_bytes=file_bytes,
            mime_type=mime_type,
        )
    except GoogleDriveServiceError as exc:
        raise GoogleDriveOAuthError(str(exc)) from exc

    logger.info("Drive file saved: telegram_user_id=%s file_id=%s", telegram_user_id, result.file_id)
    return result


def create_pending_save_operation(
    *,
    telegram_user_id: int,
    scenario_type: str,
    result_type: str,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
) -> None:
    try:
        SQLiteTokenStore().save_pending_operation(
            telegram_user_id=telegram_user_id,
            scenario_type=scenario_type,
            result_type=result_type,
            filename=filename,
            mime_type=mime_type,
            file_bytes=file_bytes,
        )
    except Exception as exc:
        raise GoogleDriveOAuthError(f"Не удалось сохранить pending operation: {exc}") from exc


def process_pending_operation_after_oauth(telegram_user_id: int) -> DriveSaveResult | None:
    store = SQLiteTokenStore()
    pending = store.pop_pending_operation(telegram_user_id)
    if not pending:
        logger.info("No pending drive operation for telegram_user_id=%s", telegram_user_id)
        return None

    logger.info(
        "Restoring pending drive operation: telegram_user_id=%s scenario=%s",
        telegram_user_id,
        pending["scenario_type"],
    )
    return save_file_for_user(
        telegram_user_id=telegram_user_id,
        filename=pending["filename"],
        file_bytes=pending["file_bytes"],
        mime_type=pending["mime_type"],
    )


def notify_telegram_user_after_pending(
    *,
    telegram_user_id: int,
    message_text: str,
) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN is missing; skip notify telegram user")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = (
        f"chat_id={telegram_user_id}&text={quote_plus(message_text)}"
    )
    request = urllib.request.Request(
        url,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as _:
            pass
    except URLError:
        logger.exception("Failed to notify telegram user after pending operation")

