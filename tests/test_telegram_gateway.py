import asyncio
from io import BytesIO

import pytest
from aiohttp import web
from aiogram import Bot
from aiogram.methods import GetMe
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramUnauthorizedError

from src.bot.telegram_gateway import GatewayAiohttpSession
from src.shared.telegram_gateway import TelegramGatewaySettings, get_telegram_gateway_settings


SERVICE_TOKEN = "123456:gateway-service-token"
GATEWAY_KEY = "gateway-test-key"


async def _start_gateway(handler):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def test_gateway_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_GATEWAY_URL", raising=False)
    assert get_telegram_gateway_settings(require_service_token=True) is None


def test_gateway_settings_require_key_and_service_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_GATEWAY_URL", "https://gateway.example/")
    monkeypatch.delenv("TELEGRAM_GATEWAY_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_GATEWAY_KEY"):
        get_telegram_gateway_settings(require_service_token=True)

    monkeypatch.setenv("TELEGRAM_GATEWAY_KEY", GATEWAY_KEY)
    with pytest.raises(RuntimeError, match="TELEGRAM_GATEWAY_SERVICE_TOKEN"):
        get_telegram_gateway_settings(require_service_token=True)

    monkeypatch.setenv("TELEGRAM_GATEWAY_SERVICE_TOKEN", SERVICE_TOKEN)
    settings = get_telegram_gateway_settings(require_service_token=True)
    assert settings is not None
    assert settings.api_base == "https://gateway.example/documind/botgateway"
    assert settings.file_base == "https://gateway.example/documind/file"


def test_gateway_session_routes_api_files_and_multipart_with_bearer_auth() -> None:
    async def scenario() -> None:
        observed: list[tuple[str, str, str]] = []

        async def handler(request: web.Request) -> web.StreamResponse:
            observed.append((request.method, request.path, request.headers.get("Authorization", "")))
            assert request.headers.get("Authorization") == f"Bearer {GATEWAY_KEY}"

            if request.path.endswith("/getMe"):
                return web.json_response(
                    {"ok": True, "result": {"id": 1, "is_bot": True, "first_name": "DocuMind"}}
                )
            if request.path.endswith("/getFile"):
                return web.json_response(
                    {"ok": True, "result": {"file_id": "source", "file_unique_id": "unique", "file_path": "docs/input.pdf"}}
                )
            if request.path == "/documind/file/docs/input.pdf":
                return web.Response(body=b"source-document")
            if request.path.endswith("/sendDocument"):
                form = await request.post()
                # aiogram sends the public field as attach://<random key> and
                # puts BufferedInputFile in a separate multipart field.
                assert str(form["document"]).startswith("attach://")
                assert any(
                    getattr(value, "filename", None) == "output.docx"
                    for value in form.values()
                )
                return web.json_response(
                    {
                        "ok": True,
                        "result": {
                            "message_id": 1,
                            "date": 0,
                            "chat": {"id": 1, "type": "private"},
                            "document": {
                                "file_id": "output",
                                "file_unique_id": "output-unique",
                                "file_name": "output.docx",
                            },
                        },
                    }
                )
            raise AssertionError(f"Unexpected Gateway request: {request.method} {request.path}")

        runner, base_url = await _start_gateway(handler)
        session = GatewayAiohttpSession(TelegramGatewaySettings(base_url, GATEWAY_KEY, SERVICE_TOKEN))
        bot = Bot(token=SERVICE_TOKEN, session=session)
        try:
            me = await bot.get_me()
            assert me.first_name == "DocuMind"

            telegram_file = await bot.get_file("source")
            destination = BytesIO()
            await bot.download_file(telegram_file.file_path, destination=destination)
            assert destination.getvalue() == b"source-document"

            await bot.send_document(1, BufferedInputFile(b"docx-content", filename="output.docx"))
        finally:
            await session.close()
            await runner.cleanup()

        assert ("POST", "/documind/botgateway/getMe", f"Bearer {GATEWAY_KEY}") in observed
        assert ("POST", "/documind/botgateway/getFile", f"Bearer {GATEWAY_KEY}") in observed
        assert ("GET", "/documind/file/docs/input.pdf", f"Bearer {GATEWAY_KEY}") in observed
        assert ("POST", "/documind/botgateway/sendDocument", f"Bearer {GATEWAY_KEY}") in observed

    asyncio.run(scenario())


def test_gateway_session_maps_gateway_errors_to_aiogram_errors() -> None:
    async def scenario() -> None:
        async def handler(request: web.Request) -> web.StreamResponse:
            assert request.headers.get("Authorization") == f"Bearer {GATEWAY_KEY}"
            return web.json_response({"ok": False, "description": "Unauthorized"}, status=401)

        runner, base_url = await _start_gateway(handler)
        session = GatewayAiohttpSession(TelegramGatewaySettings(base_url, GATEWAY_KEY, SERVICE_TOKEN))
        bot = Bot(token=SERVICE_TOKEN, session=session)
        try:
            with pytest.raises(TelegramUnauthorizedError):
                await session.make_request(bot, GetMe())
        finally:
            await session.close()
            await runner.cleanup()

    asyncio.run(scenario())
