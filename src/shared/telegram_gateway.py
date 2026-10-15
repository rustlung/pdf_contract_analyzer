"""Configuration helpers for the optional Cloudflare Telegram API Gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelegramGatewaySettings:
    """Non-logging settings used to route Bot API traffic through Cloudflare."""

    base_url: str
    gateway_key: str
    service_token: str | None = None

    @property
    def api_base(self) -> str:
        return f"{self.base_url}/documind/botgateway"

    @property
    def file_base(self) -> str:
        return f"{self.base_url}/documind/file"


def get_telegram_gateway_settings(*, require_service_token: bool = False) -> TelegramGatewaySettings | None:
    """Return Gateway settings, or ``None`` when direct Telegram mode is selected.

    The Gateway key is deliberately returned only to the caller that creates an
    HTTP client. Do not log this object or any of its fields.
    """

    base_url = os.getenv("TELEGRAM_GATEWAY_URL", "").strip().rstrip("/")
    if not base_url:
        return None

    gateway_key = os.getenv("TELEGRAM_GATEWAY_KEY", "").strip()
    if not gateway_key:
        raise RuntimeError("TELEGRAM_GATEWAY_KEY не задан для Telegram Gateway.")

    service_token = os.getenv("TELEGRAM_GATEWAY_SERVICE_TOKEN", "").strip() or None
    if require_service_token and not service_token:
        raise RuntimeError("TELEGRAM_GATEWAY_SERVICE_TOKEN не задан для Telegram Gateway.")

    return TelegramGatewaySettings(
        base_url=base_url,
        gateway_key=gateway_key,
        service_token=service_token,
    )
