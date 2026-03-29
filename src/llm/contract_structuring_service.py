import json
import logging
from dataclasses import dataclass

from src.llm.llm_client import LLMClient, LLMClientError

logger = logging.getLogger(__name__)


class ContractStructuringError(Exception):
    """Raised when contract structuring fails."""


@dataclass(slots=True)
class ContractStructuredData:
    document_type: str | None
    contract_number: str | None
    contract_date: str | None
    parties: list[str]
    subject: str | None
    term: str | None
    payment_terms: str | None
    obligations: list[str]
    additional_conditions: list[str]
    notes: str | None


class ContractStructuringService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def _build_prompt(self, masked_text: str) -> str:
        return (
            "Преобразуй текст договора в структурированные данные и верни строго JSON.\n"
            "Запрещено добавлять markdown, комментарии и текст вне JSON.\n"
            "Не придумывай факты, которых нет в договоре.\n"
            "Если поле не найдено, используй null, 'не указано' или пустой список.\n\n"
            "Требуемый JSON:\n"
            "{\n"
            '  "document_type": "...",\n'
            '  "contract_number": "...",\n'
            '  "contract_date": "...",\n'
            '  "parties": ["...", "..."],\n'
            '  "subject": "...",\n'
            '  "term": "...",\n'
            '  "payment_terms": "...",\n'
            '  "obligations": ["...", "..."],\n'
            '  "additional_conditions": ["...", "..."],\n'
            '  "notes": "..."\n'
            "}\n\n"
            f"Текст договора:\n{masked_text}"
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
            raise ContractStructuringError("Ответ модели не содержит корректный JSON-объект.")

        candidate = raw_response[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ContractStructuringError("Не удалось распарсить JSON из ответа модели.") from exc

    @staticmethod
    def _normalize_to_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def structure_contract(self, masked_text: str) -> ContractStructuredData:
        logger.info("Contract structuring started")
        prompt = self._build_prompt(masked_text)

        try:
            raw_response = self.llm_client.generate_from_prompt(
                prompt,
                system_prompt=(
                    "Ты помощник по структурированию юридических документов. "
                    "Возвращай только валидный JSON."
                ),
                temperature=0.1,
            )
        except LLMClientError as exc:
            logger.exception("LLM call failed during contract structuring")
            raise ContractStructuringError(f"Ошибка LLM при структурировании договора: {exc}") from exc

        payload = self._extract_json_payload(raw_response)
        logger.info("Contract structuring JSON parsed successfully")

        try:
            result = ContractStructuredData(
                document_type=payload.get("document_type"),
                contract_number=payload.get("contract_number"),
                contract_date=payload.get("contract_date"),
                parties=self._normalize_to_list(payload.get("parties")),
                subject=payload.get("subject"),
                term=payload.get("term"),
                payment_terms=payload.get("payment_terms"),
                obligations=self._normalize_to_list(payload.get("obligations")),
                additional_conditions=self._normalize_to_list(payload.get("additional_conditions")),
                notes=payload.get("notes"),
            )
        except Exception as exc:
            logger.exception("Contract structuring validation failed")
            raise ContractStructuringError(
                "Ответ модели получен, но структура результата некорректна."
            ) from exc

        return result
