from unittest.mock import patch


def test_oauth_notification_uses_gateway_bearer_authorization(monkeypatch) -> None:
    from src.api.integrations.google_drive import oauth_service

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = request.data
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv("TELEGRAM_GATEWAY_URL", "https://gateway.example")
    monkeypatch.setenv("TELEGRAM_GATEWAY_KEY", "gateway-test-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with patch.object(oauth_service.urllib.request, "urlopen", fake_urlopen):
        oauth_service.notify_telegram_user_after_pending(telegram_user_id=42, message_text="Done")

    assert captured["url"] == "https://gateway.example/documind/botgateway/sendMessage"
    assert captured["authorization"] == "Bearer gateway-test-key"
    assert b"chat_id=42" in captured["payload"]
    assert captured["timeout"] == 20


def test_oauth_notification_keeps_direct_fallback(monkeypatch) -> None:
    from src.api.integrations.google_drive import oauth_service

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        return Response()

    monkeypatch.delenv("TELEGRAM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:direct-test-token")
    with patch.object(oauth_service.urllib.request, "urlopen", fake_urlopen):
        oauth_service.notify_telegram_user_after_pending(telegram_user_id=42, message_text="Done")

    assert captured["url"].endswith("/sendMessage")
    assert captured["authorization"] is None
