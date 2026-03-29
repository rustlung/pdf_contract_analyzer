import base64
import hmac
import json
import os
from dataclasses import dataclass
from hashlib import sha256


class OAuthStateError(Exception):
    """Raised when OAuth state verification fails."""


def _get_state_secret() -> bytes:
    secret = os.getenv("DRIVE_OAUTH_STATE_SECRET", "").strip()
    if not secret:
        raise OAuthStateError("DRIVE_OAUTH_STATE_SECRET не задан в .env")
    return secret.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


@dataclass(frozen=True, slots=True)
class OAuthState:
    telegram_user_id: int
    trace_id: str | None = None
    client: str = "telegram"
    web_result_token: str | None = None


def build_oauth_state(
    telegram_user_id: int,
    *,
    trace_id: str | None = None,
    client: str = "telegram",
    web_result_token: str | None = None,
) -> str:
    payload_dict: dict[str, object] = {"telegram_user_id": telegram_user_id, "client": client}
    if trace_id:
        payload_dict["trace_id"] = trace_id
    if web_result_token:
        payload_dict["web_result_token"] = web_result_token
    payload = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload)
    sig = hmac.new(_get_state_secret(), payload_b64.encode("ascii"), sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return f"{payload_b64}.{sig_b64}"


def parse_and_verify_oauth_state(state: str) -> OAuthState:
    try:
        payload_b64, sig_b64 = state.split(".", 1)
    except ValueError as exc:
        raise OAuthStateError("Некорректный параметр state.") from exc

    expected_sig = hmac.new(_get_state_secret(), payload_b64.encode("ascii"), sha256).digest()
    actual_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise OAuthStateError("Проверка state не пройдена.")

    payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    telegram_user_id = int(payload["telegram_user_id"])
    trace_id = payload.get("trace_id")
    client = str(payload.get("client") or "telegram")
    wrt = payload.get("web_result_token")
    return OAuthState(
        telegram_user_id=telegram_user_id,
        trace_id=str(trace_id) if trace_id else None,
        client=client,
        web_result_token=str(wrt) if wrt else None,
    )

