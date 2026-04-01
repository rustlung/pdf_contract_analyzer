import logging
from dataclasses import dataclass

import httpx

from src.bot.config import get_api_internal_base_url, get_api_public_base_url
from src.shared.logging_events import log_event

logger = logging.getLogger(__name__)


class GoogleDriveBotServiceError(Exception):
    """Raised when dm-bot fails calling dm-api Google Drive endpoints."""


@dataclass(slots=True)
class DriveUploadResult:
    file_id: str
    file_name: str
    web_link: str | None


def build_drive_connect_url(telegram_user_id: int, *, trace_id: str | None = None) -> str:
    base = get_api_public_base_url().rstrip("/")
    url = f"{base}/google-drive-bot/connect/{telegram_user_id}"
    if trace_id:
        url = f"{url}?trace_id={trace_id}"
    return url


async def is_drive_connected(telegram_user_id: int, *, trace_id: str | None = None) -> bool:
    base = get_api_internal_base_url().rstrip("/")
    url = f"{base}/google-drive/status/{telegram_user_id}"
    try:
        log_event(
            logger,
            event="drive_check_started",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="start",
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers={"X-Trace-Id": trace_id} if trace_id else None)
            resp.raise_for_status()
            data = resp.json()
            log_event(
                logger,
                event="drive_check_completed",
                user_id=telegram_user_id,
                trace_id=trace_id,
                stage="DRIVE",
                status="success",
                connected=bool(data.get("connected")),
            )
            return bool(data.get("connected"))
    except Exception as exc:
        log_event(
            logger,
            event="drive_check_failed",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="error",
            reason=str(exc),
        )
        logger.exception("Drive status request failed")
        raise GoogleDriveBotServiceError(str(exc)) from exc


async def upload_file_to_drive(
    telegram_user_id: int,
    *,
    filename: str,
    file_bytes: bytes,
    mime_type: str,
    trace_id: str | None = None,
) -> DriveUploadResult:
    base = get_api_internal_base_url().rstrip("/")
    url = f"{base}/google-drive/upload/{telegram_user_id}"

    files = {"file": (filename, file_bytes, mime_type)}
    try:
        log_event(
            logger,
            event="drive_save_started",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="start",
            filename=filename,
            mime_type=mime_type,
            size=len(file_bytes),
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, files=files, headers={"X-Trace-Id": trace_id} if trace_id else None)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log_event(
            logger,
            event="drive_save_failed",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="error",
            filename=filename,
            reason=str(exc),
        )
        logger.exception("Drive upload request failed")
        raise GoogleDriveBotServiceError(str(exc)) from exc

    log_event(
        logger,
        event="drive_save_success",
        user_id=telegram_user_id,
        trace_id=trace_id,
        stage="DRIVE",
        status="success",
        filename=filename,
        file_id=data.get("file_id"),
    )
    return DriveUploadResult(
        file_id=str(data.get("file_id") or ""),
        file_name=str(data.get("file_name") or filename),
        web_link=data.get("web_link"),
    )


async def create_pending_drive_operation(
    telegram_user_id: int,
    *,
    scenario_type: str,
    result_type: str,
    filename: str,
    file_bytes: bytes,
    mime_type: str,
    trace_id: str | None = None,
) -> None:
    base = get_api_internal_base_url().rstrip("/")
    url = f"{base}/google-drive/pending/{telegram_user_id}"
    params = {
        "scenario_type": scenario_type,
        "result_type": result_type,
    }
    files = {"file": (filename, file_bytes, mime_type)}
    try:
        log_event(
            logger,
            event="drive_pending_save_started",
            user_id=telegram_user_id,
            trace_id=trace_id,
            stage="DRIVE",
            status="start",
            scenario_type=scenario_type,
            result_type=result_type,
            filename=filename,
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                params=params,
                files=files,
                headers={"X-Trace-Id": trace_id} if trace_id else None,
            )
            resp.raise_for_status()
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
            filename=filename,
            reason=str(exc),
        )
        logger.exception("Drive pending operation request failed")
        raise GoogleDriveBotServiceError(str(exc)) from exc

    log_event(
        logger,
        event="drive_pending_save_success",
        user_id=telegram_user_id,
        trace_id=trace_id,
        stage="DRIVE",
        status="success",
        scenario_type=scenario_type,
        result_type=result_type,
        filename=filename,
    )

