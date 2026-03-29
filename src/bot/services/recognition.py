import logging
import time
from dataclasses import dataclass, field
from io import BytesIO

from aiogram import Bot
from aiogram.types import Document

from src.api.documents.docx_reconstruction_service import (
    DocxReconstructionError,
    DocxReconstructionService,
)
from src.api.documents.document_types import DocumentProcessingError, DocumentProcessingResult
from src.api.documents.services.document_processing import process_document
from src.api.documents.text_normalizer import normalize_extracted_text_for_docx
from src.bot.services.document_processing import process_telegram_document
from src.shared.logging_events import log_event

logger = logging.getLogger(__name__)


class BotRecognitionError(Exception):
    """Raised when recognize-to-docx pipeline fails in bot layer."""


@dataclass(slots=True)
class RecognitionPipelineResult:
    document_result: DocumentProcessingResult
    normalized_paragraphs_count: int
    docx_bytes: bytes
    timings: dict[str, float] = field(default_factory=dict)


async def _download_document_bytes(bot: Bot, file_id: str) -> bytes:
    telegram_file = await bot.get_file(file_id)
    stream = BytesIO()
    await bot.download_file(telegram_file.file_path, stream)
    return stream.getvalue()


async def run_recognition_pipeline(bot: Bot, document: Document) -> RecognitionPipelineResult:
    trace_id = None
    log_event(
        logger,
        event="pipeline_started",
        stage="RECOGNIZE",
        status="start",
        filename=document.file_name,
    )
    try:
        document_result = await process_telegram_document(bot=bot, document=document, trace_id=trace_id)
        normalized = normalize_extracted_text_for_docx(document_result.raw_text)
        reconstruction_service = DocxReconstructionService()
        docx_bytes = reconstruction_service.generate_docx(document_result.raw_text)
    except (DocumentProcessingError, DocxReconstructionError) as exc:
        raise BotRecognitionError(str(exc)) from exc
    except Exception as exc:
        raise BotRecognitionError(f"Unexpected recognize pipeline error: {exc}") from exc

    logger.info(
        "Bot-side recognize pipeline completed: filename=%s method=%s used_ocr=%s pages=%s normalized_paragraphs=%s docx_bytes=%s",
        document_result.filename,
        document_result.extraction_method,
        document_result.used_ocr,
        document_result.pages_count,
        len(normalized),
        len(docx_bytes),
    )
    return RecognitionPipelineResult(
        document_result=document_result,
        normalized_paragraphs_count=len(normalized),
        docx_bytes=docx_bytes,
        timings={},
    )


async def run_recognition_pipeline_from_file_meta(
    bot: Bot,
    *,
    file_id: str,
    filename: str,
    mime_type: str | None = None,
    trace_id: str | None = None,
) -> RecognitionPipelineResult:
    logger.info("Starting bot-side recognize pipeline from file meta: filename=%s", filename)
    timings: dict[str, float] = {}
    try:
        file_bytes = await _download_document_bytes(bot=bot, file_id=file_id)
        document_result = process_document(
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
            trace_id=trace_id,
        )
        if document_result.ocr_seconds is not None:
            timings["ocr_time"] = document_result.ocr_seconds
        t1 = time.perf_counter()
        normalized = normalize_extracted_text_for_docx(document_result.raw_text)
        reconstruction_service = DocxReconstructionService()
        docx_bytes = reconstruction_service.generate_docx(document_result.raw_text)
        timings["docx_generation_time"] = time.perf_counter() - t1
    except (DocumentProcessingError, DocxReconstructionError) as exc:
        raise BotRecognitionError(str(exc)) from exc
    except Exception as exc:
        raise BotRecognitionError(f"Unexpected recognize pipeline error: {exc}") from exc

    logger.info(
        "Bot-side recognize pipeline from file meta completed: filename=%s method=%s used_ocr=%s pages=%s normalized_paragraphs=%s docx_bytes=%s",
        document_result.filename,
        document_result.extraction_method,
        document_result.used_ocr,
        document_result.pages_count,
        len(normalized),
        len(docx_bytes),
    )
    return RecognitionPipelineResult(
        document_result=document_result,
        normalized_paragraphs_count=len(normalized),
        docx_bytes=docx_bytes,
        timings=timings,
    )
