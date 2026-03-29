import logging
from dataclasses import dataclass
from io import BytesIO

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

logger = logging.getLogger(__name__)


class GoogleDriveServiceError(Exception):
    """Raised when Google Drive operations fail."""


@dataclass(slots=True)
class DriveSaveResult:
    file_id: str
    file_name: str
    web_link: str | None


def _ensure_valid_creds(creds: Credentials) -> Credentials:
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        logger.info("Drive creds expired; refreshing")
        creds.refresh(Request())
        return creds
    raise GoogleDriveServiceError("OAuth credentials недействительны. Требуется повторное подключение.")


def save_file_to_user_drive(
    creds: Credentials,
    *,
    filename: str,
    file_bytes: bytes,
    mime_type: str,
) -> DriveSaveResult:
    creds = _ensure_valid_creds(creds)
    logger.info("Drive upload started: filename=%s mime_type=%s size=%s", filename, mime_type, len(file_bytes))
    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        media = MediaIoBaseUpload(BytesIO(file_bytes), mimetype=mime_type, resumable=False)
        body = {"name": filename}
        created = (
            service.files()
            .create(body=body, media_body=media, fields="id,name,webViewLink")
            .execute()
        )
        file_id = created.get("id")
        file_name = created.get("name") or filename
        web_link = created.get("webViewLink")
    except Exception as exc:
        logger.exception("Drive upload failed")
        raise GoogleDriveServiceError(f"Не удалось сохранить файл в Google Drive: {exc}") from exc

    logger.info("Drive upload completed: file_id=%s", file_id)
    return DriveSaveResult(file_id=file_id, file_name=file_name, web_link=web_link)

