import logging

from src.llm.contract_comparison_service import (
    ContractComparisonError,
    ContractComparisonResult,
    ContractComparisonService,
)

logger = logging.getLogger(__name__)


class BotContractComparisonError(Exception):
    """Raised when bot contract comparison service fails."""


def compare_masked_contracts(masked_text_1: str, masked_text_2: str) -> ContractComparisonResult:
    logger.info("Starting bot-side contract comparison")
    try:
        service = ContractComparisonService()
        result = service.compare_contracts(masked_text_1, masked_text_2)
    except ContractComparisonError as exc:
        raise BotContractComparisonError(str(exc)) from exc

    logger.info("Bot-side contract comparison completed")
    return result
