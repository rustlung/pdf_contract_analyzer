import logging
from typing import Any


def log_event(
    logger: logging.Logger,
    *,
    event: str,
    stage: str,
    status: str,
    trace_id: str | None = None,
    user_id: int | None = None,
    **context: Any,
) -> None:
    """
    Minimal structured logging helper.

    Format: key=value pairs, easy to grep.
    Required keys: event, stage, status.
    """

    def _fmt_value(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value)
        # keep logs one-line and grep-friendly
        return text.replace("\n", "\\n").replace("\r", "\\r")

    base = {
        "event": event,
        "stage": stage,
        "status": status,
        "user_id": user_id,
        "trace_id": trace_id,
    }
    merged: dict[str, Any] = {**base, **context}

    ordered_keys = ["event", "user_id", "trace_id", "stage", "status"]
    parts: list[str] = []
    for key in ordered_keys:
        if key in merged:
            parts.append(f"{key}={_fmt_value(merged.pop(key))}")
    for key in sorted(merged.keys()):
        parts.append(f"{key}={_fmt_value(merged[key])}")

    logger.info(" ".join(parts))

