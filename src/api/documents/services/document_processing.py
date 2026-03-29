import logging
import time

from src.api.documents.document_types import (
    DocumentProcessingError,
    DocumentProcessingResult,
)
from src.api.documents.extractors import (
    extract_docx_text,
    extract_pdf_text_direct,
    extract_pdf_text_with_ocr,
)
from src.shared.logging_events import log_event

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIN_DIRECT_TEXT_LENGTH = 80


def _detect_source_type(filename: str, mime_type: str | None) -> str:
    normalized_name = filename.lower()
    normalized_mime = (mime_type or "").lower()

    if normalized_mime == PDF_MIME or normalized_name.endswith(".pdf"):
        return "pdf"
    if normalized_mime == DOCX_MIME or normalized_name.endswith(".docx"):
        return "docx"
    raise DocumentProcessingError(
        "Неподдерживаемый формат документа. Допустимы только PDF и DOCX."
    )


def _ensure_text_not_empty(text: str) -> None:
    if not text.strip():
        raise DocumentProcessingError(
            "Не удалось извлечь текст из документа. Проверьте качество файла."
        )


def process_document(
    file_bytes: bytes,
    filename: str,
    mime_type: str | None = None,
    *,
    trace_id: str | None = None,
) -> DocumentProcessingResult:
    source_type = _detect_source_type(filename=filename, mime_type=mime_type)
    log_event(
        logger,
        event="document_validated",
        trace_id=trace_id,
        stage="PIPELINE",
        status="success",
        filename=filename,
        source_type=source_type,
        mime_type=mime_type,
        size=len(file_bytes),
    )

    try:
        if source_type == "docx":
            log_event(
                logger,
                event="extraction_started",
                trace_id=trace_id,
                stage="PIPELINE",
                status="start",
                extraction_method="docx",
                filename=filename,
            )
            text, pages_count = extract_docx_text(file_bytes)
            _ensure_text_not_empty(text)
            log_event(
                logger,
                event="extraction_completed",
                trace_id=trace_id,
                stage="PIPELINE",
                status="success",
                extraction_method="docx",
                filename=filename,
                pages_count=pages_count,
                text_length=len(text),
                used_ocr=False,
            )
            return DocumentProcessingResult(
                filename=filename,
                source_type=source_type,
                extraction_method="docx",
                raw_text=text,
                pages_count=pages_count,
                used_ocr=False,
                ocr_seconds=None,
            )

        log_event(
            logger,
            event="extraction_started",
            trace_id=trace_id,
            stage="PIPELINE",
            status="start",
            extraction_method="direct_pdf",
            filename=filename,
        )
        direct_text, pages_count = extract_pdf_text_direct(file_bytes)
        log_event(
            logger,
            event="extraction_completed",
            trace_id=trace_id,
            stage="PIPELINE",
            status="success",
            extraction_method="direct_pdf",
            filename=filename,
            pages_count=pages_count,
            text_length=len(direct_text),
            used_ocr=False,
        )

        if len(direct_text.strip()) >= MIN_DIRECT_TEXT_LENGTH:
            return DocumentProcessingResult(
                filename=filename,
                source_type=source_type,
                extraction_method="direct_pdf",
                raw_text=direct_text,
                pages_count=pages_count,
                used_ocr=False,
                ocr_seconds=None,
            )

        log_event(
            logger,
            event="ocr_started",
            trace_id=trace_id,
            stage="OCR",
            status="start",
            filename=filename,
        )
        _ocr_t0 = time.perf_counter()
        ocr_text, ocr_pages_count = extract_pdf_text_with_ocr(file_bytes)
        ocr_seconds = time.perf_counter() - _ocr_t0
        _ensure_text_not_empty(ocr_text)
        log_event(
            logger,
            event="ocr_completed",
            trace_id=trace_id,
            stage="OCR",
            status="success",
            filename=filename,
            pages_count=ocr_pages_count,
            text_length=len(ocr_text),
            ocr_seconds=round(ocr_seconds, 4),
        )
        log_event(
            logger,
            event="extraction_completed",
            trace_id=trace_id,
            stage="PIPELINE",
            status="success",
            extraction_method="ocr_pdf",
            filename=filename,
            pages_count=ocr_pages_count,
            text_length=len(ocr_text),
            used_ocr=True,
        )
        return DocumentProcessingResult(
            filename=filename,
            source_type=source_type,
            extraction_method="ocr_pdf",
            raw_text=ocr_text,
            pages_count=ocr_pages_count,
            used_ocr=True,
            ocr_seconds=ocr_seconds,
        )
    except DocumentProcessingError:
        raise
    except Exception as exc:
        log_event(
            logger,
            event="pipeline_failed",
            trace_id=trace_id,
            stage="PIPELINE",
            status="error",
            filename=filename,
            reason=str(exc),
        )
        raise DocumentProcessingError(
            f"Ошибка обработки документа '{filename}': {exc}"
        ) from exc
