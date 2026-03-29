import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Raised when LLM request fails."""


class LLMClient:
    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.proxyapi.ru/openai/v1",
    ) -> None:
        load_dotenv()
        api_key = os.getenv("PROXYAPI_API_KEY", "").strip()
        if not api_key:
            raise LLMClientError("PROXYAPI_API_KEY не задан в .env")

        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def generate_from_prompt(
        self,
        prompt: str,
        *,
        system_prompt: str = "Ты помощник по анализу договоров.",
        temperature: float = 0.2,
    ) -> str:
        logger.info("LLM request started")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
        except Exception as exc:
            logger.exception("LLM request failed")
            raise LLMClientError(f"Ошибка обращения к LLM: {exc}") from exc

        content = response.choices[0].message.content if response.choices else ""
        if not content:
            raise LLMClientError("LLM вернула пустой ответ")

        logger.info("LLM request completed successfully")
        return content

    def generate_response(self, text: str) -> str:
        prompt = (
            "Сделай краткое резюме текста на русском языке в 3-5 предложениях.\n\n"
            f"Текст:\n{text}"
        )
        return self.generate_from_prompt(prompt)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_text = (
        "Настоящий договор аренды заключен между Заказчиком и Исполнителем. "
        "Срок аренды составляет 11 месяцев. Оплата производится ежемесячно."
    )

    try:
        client = LLMClient()
        print(client.generate_response(sample_text))
    except LLMClientError as exc:
        print(f"LLM client error: {exc}")
