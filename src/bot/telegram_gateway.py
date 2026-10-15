"""aiogram transport for the Cloudflare Telegram API Gateway."""

from __future__ import annotations

from aiohttp.hdrs import AUTHORIZATION
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from src.shared.telegram_gateway import TelegramGatewaySettings


class GatewayAiohttpSession(AiohttpSession):
    """Aiohttp session which adds Gateway authorization to API and file calls."""

    def __init__(self, settings: TelegramGatewaySettings) -> None:
        api = TelegramAPIServer(
            base=f"{settings.api_base}/{{method}}",
            file=f"{settings.file_base}/{{path}}",
        )
        super().__init__(api=api)
        self._gateway_authorization = f"Bearer {settings.gateway_key}"

    async def create_session(self):  # type: ignore[no-untyped-def]
        session = await super().create_session()
        # aiohttp default headers are merged into both POST requests made by
        # make_request() and GET requests made by stream_content().
        session.headers[AUTHORIZATION] = self._gateway_authorization
        return session
