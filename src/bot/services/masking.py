import logging

from src.shared.masking import MaskingResult, mask_document_text

logger = logging.getLogger(__name__)


class MaskingServiceError(Exception):
    """Raised when bot masking service fails."""


def process_masking(text: str) -> MaskingResult:
    logger.info("Starting bot-side masking pipeline")
    try:
        result = mask_document_text(text)
    except Exception as exc:
        raise MaskingServiceError(str(exc)) from exc
    logger.info(
        "Masking completed: replacements_count=%s replacement_stats=%s",
        result.replacements_count,
        result.replacement_stats,
    )
    return result
