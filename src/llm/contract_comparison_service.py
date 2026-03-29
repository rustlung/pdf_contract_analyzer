import json
import logging
from dataclasses import dataclass

from src.llm.llm_client import LLMClient, LLMClientError

logger = logging.getLogger(__name__)


class ContractComparisonError(Exception):
    """Raised when contract comparison fails."""


@dataclass(slots=True)
class ContractComparisonResult:
    summary: str | None
    major_differences: list[str]
    parties_changes: str | None
    subject_changes: str | None
    term_changes: str | None
    payment_changes: str | None
    obligations_changes: str | None
    risks: list[str]
    disclaimer: str


class ContractComparisonService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def _build_prompt(self, masked_text_1: str, masked_text_2: str) -> str:
        return (
            "Сравни два текста договоров и верни только существенные различия строго в JSON.\n"
            "Не добавляй markdown, комментарии и пояснения вне JSON.\n"
            "Не придумывай различия, которых нет в текстах.\n"
            "Если различий по блоку нет, используй null, пустой список или 'не выявлено'.\n"
            "Риски указывай как предварительные наблюдения, это не юридическое заключение.\n\n"
            "Верни JSON следующего вида:\n"
            "{\n"
            '  "summary": "...",\n'
            '  "major_differences": ["...", "..."],\n'
            '  "parties_changes": "...",\n'
            '  "subject_changes": "...",\n'
            '  "term_changes": "...",\n'
            '  "payment_changes": "...",\n'
            '  "obligations_changes": "...",\n'
            '  "risks": ["...", "..."],\n'
            '  "disclaimer": "..."\n'
            "}\n\n"
            f"Договор 1:\n{masked_text_1}\n\n"
            f"Договор 2:\n{masked_text_2}"
        )

    @staticmethod
    def _extract_json_payload(raw_response: str) -> dict:
        raw_response = raw_response.strip()
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError:
            pass

        start = raw_response.find("{")
        end = raw_response.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ContractComparisonError("Ответ модели не содержит корректный JSON-объект.")

        candidate = raw_response[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ContractComparisonError("Не удалось распарсить JSON из ответа модели.") from exc

    @staticmethod
    def _normalize_to_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def compare_contracts(self, masked_text_1: str, masked_text_2: str) -> ContractComparisonResult:
        logger.info("Contract comparison started")
        prompt = self._build_prompt(masked_text_1, masked_text_2)

        try:
            raw_response = self.llm_client.generate_from_prompt(
                prompt,
                system_prompt=(
                    "Ты помощник по сравнительному анализу договоров. "
                    "Возвращай только валидный JSON без дополнительного текста."
                ),
                temperature=0.1,
            )
        except LLMClientError as exc:
            logger.exception("LLM call failed during contract comparison")
            raise ContractComparisonError(f"Ошибка LLM при сравнении договоров: {exc}") from exc

        payload = self._extract_json_payload(raw_response)
        logger.info("Contract comparison JSON parsed successfully")

        try:
            result = ContractComparisonResult(
                summary=payload.get("summary"),
                major_differences=self._normalize_to_list(payload.get("major_differences")),
                parties_changes=payload.get("parties_changes"),
                subject_changes=payload.get("subject_changes"),
                term_changes=payload.get("term_changes"),
                payment_changes=payload.get("payment_changes"),
                obligations_changes=payload.get("obligations_changes"),
                risks=self._normalize_to_list(payload.get("risks")),
                disclaimer=str(payload.get("disclaimer") or "Сравнение носит справочный характер."),
            )
        except Exception as exc:
            logger.exception("Contract comparison result validation failed")
            raise ContractComparisonError(
                "Ответ модели получен, но структура результата некорректна."
            ) from exc

        return result
