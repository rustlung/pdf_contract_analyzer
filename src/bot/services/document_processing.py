import logging
from io import BytesIO

from aiogram import Bot
from aiogram.types import Document

from src.api.documents.document_types import DocumentProcessingResult
from src.api.documents.services.document_processing import process_document
from src.shared.logging_events import log_event

logger = logging.getLogger(__name__)


async def _download_document_bytes(bot: Bot, document: Document) -> bytes:
    telegram_file = await bot.get_file(document.file_id)
    stream = BytesIO()
    await bot.download_file(telegram_file.file_path, stream)
    return stream.getvalue()


async def process_telegram_document(
    bot: Bot,
    document: Document,
    *,
    trace_id: str | None = None,
    user_id: int | None = None,
) -> DocumentProcessingResult:
    filename = document.file_name or "unknown_file"
    file_bytes = await _download_document_bytes(bot=bot, document=document)
    log_event(
        logger,
        event="document_downloaded",
        user_id=user_id,
        trace_id=trace_id,
        stage="PIPELINE",
        status="success",
        filename=filename,
        size=len(file_bytes),
    )
    return process_document(
        file_bytes=file_bytes,
        filename=filename,
        mime_type=document.mime_type,
        trace_id=trace_id,
    )
