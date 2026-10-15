import os

from dotenv import load_dotenv

from src.shared.telegram_gateway import TelegramGatewaySettings, get_telegram_gateway_settings


load_dotenv()


def get_bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. "
            "Добавьте токен в .env и перезапустите сервис dm-bot."
        )
    return token


def get_bot_gateway_settings() -> TelegramGatewaySettings | None:
    """Return configured Cloudflare Gateway settings for dm-bot, if enabled."""

    return get_telegram_gateway_settings(require_service_token=True)


def get_api_internal_base_url() -> str:
    """
    Base URL used by dm-bot container to call dm-api.
    In docker-compose network it should be http://dm-api:8000
    """
    return os.getenv("DM_API_INTERNAL_BASE_URL", "http://dm-api:8000").strip()


def get_api_public_base_url() -> str:
    """
    Base URL shown to user for OAuth connect links.
    For local dev it is usually http://127.0.0.1:8000 or http://localhost:8000
    """
    return os.getenv("DM_API_PUBLIC_BASE_URL", "http://127.0.0.1:8000").strip()
