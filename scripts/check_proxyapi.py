import os
import sys


def main() -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("python-dotenv не установлен. Установите: pip install python-dotenv")
        return 1

    try:
        from openai import OpenAI
    except ImportError:
        print("openai SDK не установлен. Установите: pip install openai")
        return 1

    load_dotenv()
    api_key = os.getenv("PROXYAPI_API_KEY", "").strip()
    if not api_key:
        print("PROXYAPI_API_KEY не задан в .env")
        return 1

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.proxyapi.ru/openai/v1",
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты помощник."},
                {"role": "user", "content": "Ответь одним словом: ok"},
            ],
            temperature=0,
        )
    except Exception as exc:
        print(f"Ошибка запроса к proxyapi: {exc}")
        return 1

    answer = response.choices[0].message.content if response.choices else ""
    print("status: ok")
    print(f"model: {response.model}")
    print(f"answer: {answer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
