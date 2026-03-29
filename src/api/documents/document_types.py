from dataclasses import dataclass


@dataclass(slots=True)
class DocumentProcessingResult:
    filename: str
    source_type: str
    extraction_method: str
    raw_text: str
    pages_count: int
    used_ocr: bool
    #: Wall time spent in OCR extraction only; set when OCR path is used.
    ocr_seconds: float | None = None


class DocumentProcessingError(Exception):
    """Raised when document validation or text extraction fails."""
