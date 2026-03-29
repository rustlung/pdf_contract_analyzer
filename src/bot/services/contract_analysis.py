import logging

from src.llm.contract_analysis_service import (
    ContractAnalysisError,
    ContractAnalysisResult,
    ContractAnalysisService,
)

logger = logging.getLogger(__name__)


class BotContractAnalysisError(Exception):
    """Raised when bot contract analysis service fails."""


def analyze_masked_contract(masked_text: str) -> ContractAnalysisResult:
    logger.info("Starting bot-side contract analysis")
    try:
        service = ContractAnalysisService()
        result = service.analyze_contract(masked_text)
    except ContractAnalysisError as exc:
        raise BotContractAnalysisError(str(exc)) from exc

    logger.info("Bot-side contract analysis completed")
    return result
