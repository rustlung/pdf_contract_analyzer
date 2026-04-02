import logging
import os

from fastapi import APIRouter, File, HTTPException, UploadFile, Request
from fastapi.responses import HTMLResponse

from src.api.integrations.google_drive.oauth_service import (
    GoogleDriveOAuthError,
    build_authorization_url,
    create_pending_save_operation,
    exchange_code_and_store_tokens,
    is_drive_connected,
    notify_telegram_user_after_pending,
    process_pending_operation_after_oauth,
    save_file_for_user,
)
from src.api.services.web_result_store import update_drive_web_link
from src.shared.logging_events import log_event

logger = logging.getLogger(__name__)
router = APIRouter()

_TELEGRAM_BOT_URL_DEFAULT = "https://t.me/vs_DocuMind_bot"


def _render_drive_page(
    *,
    title: str,
    message: str,
    status: str = "success",
    primary_label: str | None = None,
    primary_href: str | None = None,
    secondary_label: str | None = None,
    secondary_href: str | None = None,
    web_back_label: str | None = None,
    web_back_href: str | None = None,
    small_note: str | None = "Это окно можно закрыть.",
) -> HTMLResponse:
    is_success = status == "success"
    accent = "#16a34a" if is_success else "#dc2626"
    icon = "✓" if is_success else "!"
    telegram_bot_url = os.getenv("TELEGRAM_BOT_URL", _TELEGRAM_BOT_URL_DEFAULT).strip() or _TELEGRAM_BOT_URL_DEFAULT

    primary_html = (
        f'<a class="btn btn-primary" href="{primary_href}" target="_blank" rel="noopener noreferrer">{primary_label}</a>'
        if primary_label and primary_href
        else ""
    )
    secondary_html = (
        f'<a class="btn" href="{secondary_href}">{secondary_label}</a>'
        if secondary_label and secondary_href
        else ""
    )
    web_back_html = (
        f'<a class="btn" href="{web_back_href}">{web_back_label}</a>'
        if web_back_label and web_back_href
        else ""
    )
    note_html = f'<div class="note">{small_note}</div>' if small_note else ""

    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f6f7fb;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #475569;
      --border: rgba(15, 23, 42, 0.08);
      --shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      --accent: {accent};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
      background: radial-gradient(1200px 700px at 20% 0%, rgba(22, 163, 74, 0.10), transparent 60%),
                  radial-gradient(900px 500px at 90% 20%, rgba(59, 130, 246, 0.08), transparent 55%),
                  var(--bg);
      color: var(--text);
      display: grid;
      place-items: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      width: 100%;
      max-width: 560px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: var(--shadow);
      padding: 24px;
    }}
    .brand {{
      font-weight: 650;
      letter-spacing: 0.2px;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 14px;
    }}
    .head {{
      display: flex;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 12px;
    }}
    .icon {{
      width: 40px;
      height: 40px;
      border-radius: 12px;
      display: grid;
      place-items: center;
      background: color-mix(in srgb, var(--accent) 14%, white);
      color: var(--accent);
      font-weight: 800;
      border: 1px solid color-mix(in srgb, var(--accent) 18%, white);
      flex: 0 0 auto;
    }}
    h1 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.3;
    }}
    p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 14px;
      border-radius: 12px;
      text-decoration: none;
      font-weight: 650;
      font-size: 14px;
      border: 1px solid transparent;
      background: #fff;
      color: var(--text);
      border-color: var(--border);
      user-select: none;
    }}
    .btn-primary {{
      background: var(--accent);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 10px 18px color-mix(in srgb, var(--accent) 24%, transparent);
    }}
    .note {{
      margin-top: 18px;
      font-size: 12px;
      color: #64748b;
    }}
  </style>
  <script>
    function backToTelegram() {{
      try {{
        window.location.href = "tg://";
        setTimeout(() => {{ window.location.href = "{telegram_bot_url}"; }}, 450);
      }} catch (e) {{
        window.location.href = "{telegram_bot_url}";
      }}
    }}
  </script>
</head>
<body>
  <div class="card">
    <div class="brand">DocuMind</div>
    <div class="head">
      <div class="icon">{icon}</div>
      <div>
        <h1>{title}</h1>
        <p>{message}</p>
      </div>
    </div>
    <div class="actions">
      {primary_html}
      {secondary_html}
      {web_back_html}
      <button class="btn" type="button" onclick="backToTelegram()">Вернуться в Telegram</button>
    </div>
    {note_html}
  </div>
</body>
</html>"""
    return HTMLResponse(html, status_code=200 if is_success else 400)


@router.get("/connect/{telegram_user_id}")
def google_drive_connect(
    telegram_user_id: int,
    request: Request,
    trace_id: str | None = None,
    client: str = "telegram",
    web_result_token: str | None = None,
) -> HTMLResponse:
    """
    Redirects user to Google OAuth consent screen.
    The resulting token will be linked to the telegram_user_id.
    """
    try:
        log_event(
            logger,
            event="oauth_started",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="OAUTH",
            status="start",
        )
        auth_url = build_authorization_url(
            telegram_user_id=telegram_user_id,
            trace_id=trace_id,
            client=client,
            web_result_token=web_result_token,
        )
    except GoogleDriveOAuthError as exc:
        logger.exception("Google Drive connect failed")
        return _render_drive_page(
            title="Не удалось начать подключение Google Drive",
            message="Попробуйте ещё раз позже или вернитесь в Telegram и повторите действие.",
            status="error",
            small_note=None,
        )
    # Some environments (embedded browsers/proxies) may not follow redirects reliably.
    # Return a tiny HTML page with an explicit link and auto-redirect.
    web_back_href = str(request.url_for("web_upload"))
    return _render_drive_page(
        title="Подключение Google Drive",
        message="Сейчас откроется страница Google для авторизации. Если переход не произошёл — нажмите кнопку ниже.",
        status="success",
        primary_label="Открыть страницу авторизации",
        primary_href=auth_url,
        web_back_label="Вернуться в DocuMind",
        web_back_href=web_back_href,
        small_note="Если вы уже авторизовались, можно закрыть это окно.",
    )


@router.get("/callback")
def google_drive_callback(code: str, state: str, request: Request) -> HTMLResponse:
    """
    OAuth callback endpoint configured in Google Cloud Console.
    """
    try:
        state_oauth = exchange_code_and_store_tokens(code=code, state=state)
    except GoogleDriveOAuthError as exc:
        logger.exception("Google Drive callback failed")
        return _render_drive_page(
            title="Не удалось завершить подключение Google Drive",
            message="Попробуйте ещё раз позже или вернитесь в Telegram и повторите действие.",
            status="error",
            small_note=None,
        )

    telegram_user_id = state_oauth.telegram_user_id
    is_web = state_oauth.client == "web"
    drive_file_link: str | None = None
    try:
        pending_result = process_pending_operation_after_oauth(telegram_user_id)
        if pending_result:
            drive_file_link = pending_result.web_link
            if state_oauth.web_result_token:
                update_drive_web_link(state_oauth.web_result_token, pending_result.web_link)
            pending_result_text = (
                "✅ Google Drive подключён. Продолжаю сохранение результата...\n"
                "✅ Результат сохранён в Google Drive."
                + (f"\nСсылка: {pending_result.web_link}" if pending_result.web_link else "")
            )
            if not is_web:
                notify_telegram_user_after_pending(
                    telegram_user_id=telegram_user_id,
                    message_text=pending_result_text,
                )
    except Exception:
        logger.exception("Pending operation restore failed after OAuth")
        if not is_web:
            notify_telegram_user_after_pending(
                telegram_user_id=telegram_user_id,
                message_text=(
                    "Google Drive подключён, но автоматическое сохранение результата не удалось.\n"
                    "Попробуйте повторить действие сохранения в боте."
                ),
            )

    web_continue = (
        str(request.url_for("web_result")) + f"?t={state_oauth.web_result_token}"
        if is_web and state_oauth.web_result_token
        else None
    )

    if drive_file_link:
        return _render_drive_page(
            title="Google Drive подключён",
            message=(
                "Результат успешно сохранён в ваш Google Drive. "
                + ("Можно открыть результат в веб-интерфейсе DocuMind или вернуться в Telegram."
                   if is_web
                   else "Можно вернуться в Telegram и продолжить работу.")
            ),
            status="success",
            primary_label="Открыть файл в Google Drive",
            primary_href=drive_file_link,
            secondary_label="Открыть результат в DocuMind (веб)" if web_continue else None,
            secondary_href=web_continue,
        )

    return _render_drive_page(
        title="Google Drive подключён",
        message=(
            "Google Drive подключён. Сохранение результата завершится в веб-интерфейсе."
            if is_web
            else "Google Drive подключён. Сохранение результата завершится в Telegram."
        ),
        status="success",
        secondary_label="Открыть DocuMind (веб)" if web_continue else None,
        secondary_href=web_continue,
    )


@router.get("/status/{telegram_user_id}")
def google_drive_status(telegram_user_id: int, request: Request) -> dict:
    trace_id = request.headers.get("X-Trace-Id") or None
    try:
        log_event(
            logger,
            event="drive_check_started",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="start",
        )
        connected = is_drive_connected(telegram_user_id=telegram_user_id)
    except GoogleDriveOAuthError as exc:
        logger.exception("Google Drive status check failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event(
        logger,
        event="drive_check_completed",
        user_id=telegram_user_id,
        trace_id=trace_id,
        stage="DRIVE",
        status="success",
        connected=connected,
    )
    return {"telegram_user_id": telegram_user_id, "connected": connected}


@router.post("/upload/{telegram_user_id}")
async def google_drive_upload(
    telegram_user_id: int,
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """
    MVP endpoint to verify upload to user's Google Drive after OAuth.
    """
    trace_id = request.headers.get("X-Trace-Id") or None
    try:
        file_bytes = await file.read()
        log_event(
            logger,
            event="drive_save_started",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="start",
            filename=file.filename,
            mime_type=file.content_type,
            size=len(file_bytes),
        )
        result = save_file_for_user(
            telegram_user_id=telegram_user_id,
            filename=file.filename or "output.bin",
            file_bytes=file_bytes,
            mime_type=file.content_type or "application/octet-stream",
        )
    except GoogleDriveOAuthError as exc:
        log_event(
            logger,
            event="drive_save_failed",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="error",
            filename=file.filename,
            reason=str(exc),
        )
        logger.exception("Google Drive upload failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_event(
            logger,
            event="drive_save_failed",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="error",
            filename=file.filename,
            reason=str(exc),
        )
        logger.exception("Unexpected upload error")
        raise HTTPException(status_code=500, detail="Upload failed") from exc

    log_event(
        logger,
        event="drive_save_success",
        user_id=telegram_user_id,
        trace_id=trace_id,
        stage="DRIVE",
        status="success",
        file_id=result.file_id,
        filename=result.file_name,
    )
    return {
        "file_id": result.file_id,
        "file_name": result.file_name,
        "web_link": result.web_link,
    }


@router.post("/pending/{telegram_user_id}")
async def google_drive_pending(
    telegram_user_id: int,
    request: Request,
    file: UploadFile = File(...),
    scenario_type: str = "unknown",
    result_type: str = "report",
) -> dict:
    trace_id = request.headers.get("X-Trace-Id") or None
    try:
        file_bytes = await file.read()
        log_event(
            logger,
            event="drive_pending_save_started",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="start",
            scenario_type=scenario_type,
            result_type=result_type,
            filename=file.filename,
            size=len(file_bytes),
        )
        create_pending_save_operation(
            telegram_user_id=telegram_user_id,
            scenario_type=scenario_type,
            result_type=result_type,
            filename=file.filename or "output.bin",
            mime_type=file.content_type or "application/octet-stream",
            file_bytes=file_bytes,
        )
    except GoogleDriveOAuthError as exc:
        log_event(
            logger,
            event="drive_pending_save_failed",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="error",
            scenario_type=scenario_type,
            result_type=result_type,
            filename=file.filename,
            reason=str(exc),
        )
        logger.exception("Google Drive pending save failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_event(
            logger,
            event="drive_pending_save_failed",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="error",
            scenario_type=scenario_type,
            result_type=result_type,
            filename=file.filename,
            reason=str(exc),
        )
        logger.exception("Unexpected pending save error")
        raise HTTPException(status_code=500, detail="Pending save failed") from exc

    log_event(
        logger,
        event="drive_pending_save_success",
        user_id=telegram_user_id,
        trace_id=trace_id,
        stage="DRIVE",
        status="success",
        scenario_type=scenario_type,
        result_type=result_type,
    )
    return {"ok": True, "telegram_user_id": telegram_user_id, "status": "pending_saved"}

