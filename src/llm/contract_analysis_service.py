import json
import logging
from dataclasses import dataclass

from src.llm.llm_client import LLMClient, LLMClientError

logger = logging.getLogger(__name__)

# Shown when the model omits disclaimer or returns an empty string.
ANALYSIS_DISCLAIMER_FALLBACK = "Это не является юридическим заключением."


def normalize_analysis_disclaimer(raw: object | None) -> str:
    """
    Model often fills unknown fields with «не указано» per prompt; treat that as missing for disclaimer.
    """
    t = str(raw).strip() if raw is not None else ""
    if not t:
        return ANALYSIS_DISCLAIMER_FALLBACK
    tl = t.lower().replace("ё", "е").rstrip(".")
    if tl in ("не указано", "-", "—", "n/a", "na", "нет", "unknown"):
        return ANALYSIS_DISCLAIMER_FALLBACK
    return t


class ContractAnalysisError(Exception):
    """Raised when contract analysis fails."""


@dataclass(slots=True)
class ContractAnalysisResult:
    document_type: str | None
    summary: str | None
    parties: list[str]
    subject: str | None
    term: str | None
    payment_terms: str | None
    obligations: list[str]
    risks: list[str]
    disclaimer: str


class ContractAnalysisService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def _build_prompt(self, masked_text: str) -> str:
        return (
            "Проанализируй текст договора и верни результат строго в JSON-формате.\n"
            "Не добавляй комментарии, markdown, пояснения до или после JSON.\n"
            "Не придумывай данные, которых нет в тексте.\n"
            "Если поле не найдено: используй null, пустую строку 'не указано' или пустой список.\n"
            "Поле disclaimer: кратко укажи, что анализ не является юридическим заключением; не заполняй его значением «не указано».\n"
            "Риски формулируй как предварительные наблюдения, это не юридическое заключение.\n\n"
            "Верни JSON следующего вида:\n"
            "{\n"
            '  "document_type": "...",\n'
            '  "summary": "...",\n'
            '  "parties": ["...", "..."],\n'
            '  "subject": "...",\n'
            '  "term": "...",\n'
            '  "payment_terms": "...",\n'
            '  "obligations": ["...", "..."],\n'
            '  "risks": ["...", "..."],\n'
            '  "disclaimer": "..."\n'
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

        # Fallback for responses wrapped in markdown or extra text.
        start = raw_response.find("{")
        end = raw_response.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ContractAnalysisError("Ответ модели не содержит корректный JSON-объект.")

        candidate = raw_response[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ContractAnalysisError("Не удалось распарсить JSON из ответа модели.") from exc

    @staticmethod
    def _normalize_to_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return []

    def analyze_contract(self, masked_text: str) -> ContractAnalysisResult:
        logger.info("Contract analysis started")
        prompt = self._build_prompt(masked_text)

        try:
            raw_response = self.llm_client.generate_response(prompt)
        except LLMClientError as exc:
            logger.exception("LLM call failed during contract analysis")
            raise ContractAnalysisError(f"Ошибка LLM при анализе договора: {exc}") from exc

        payload = self._extract_json_payload(raw_response)
        logger.info("Contract analysis JSON parsed successfully")

        try:
            disc_text = normalize_analysis_disclaimer(payload.get("disclaimer"))
            result = ContractAnalysisResult(
                document_type=payload.get("document_type"),
                summary=payload.get("summary"),
                parties=self._normalize_to_list(payload.get("parties")),
                subject=payload.get("subject"),
                term=payload.get("term"),
                payment_terms=payload.get("payment_terms"),
                obligations=self._normalize_to_list(payload.get("obligations")),
                risks=self._normalize_to_list(payload.get("risks")),
                disclaimer=disc_text,
            )
        except Exception as exc:
            logger.exception("Contract analysis result validation failed")
            raise ContractAnalysisError(
                "Ответ модели получен, но структура результата некорректна."
            ) from exc

        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_masked_text = (
        "Договор аренды между COMPANY_1 и COMPANY_2. "
        "Срок аренды 11 месяцев. Арендная плата 100000 рублей в месяц. "
        "Стороны обязуются соблюдать условия договора."
    )

    try:
        service = ContractAnalysisService()
        analysis = service.analyze_contract(sample_masked_text)
        print(json.dumps(analysis.__dict__, ensure_ascii=False, indent=2))
    except ContractAnalysisError as exc:
        print(f"Contract analysis error: {exc}")
