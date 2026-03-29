"""
Shared helpers for processing_metrics / scenario timing logs (web + Telegram).
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.logging_events import log_event

logger = logging.getLogger(__name__)


def log_processing_metrics(
    log: logging.Logger,
    *,
    trace_id: str | None,
    user_id: int | None,
    scenario_type: str,
    stage: str,
    timings: dict[str, float],
    file_count: int | None = None,
    used_ocr: bool | None = None,
) -> None:
    """Emit processing_metrics with rounded seconds; omit None context keys."""
    rounded = {k: round(v, 4) for k, v in timings.items()}
    extra: dict[str, Any] = {**rounded}
    if file_count is not None:
        extra["file_count"] = file_count
    if used_ocr is not None:
        extra["used_ocr"] = used_ocr
    log_event(
        log,
        event="processing_metrics",
        user_id=user_id,
        trace_id=trace_id,
        stage=stage,
        status="success",
        scenario_type=scenario_type,
        **extra,
    )


def log_scenario_processing(
    log: logging.Logger,
    *,
    event: str,
    trace_id: str | None,
    user_id: int | None,
    scenario_type: str,
    status: str,
    stage: str = "BOT",
    total_processing_time: float | None = None,
    file_count: int | None = None,
    used_ocr: bool | None = None,
    reason: str | None = None,
) -> None:
    """scenario_started / scenario_completed for heavy processing (default stage=BOT)."""
    kw: dict[str, Any] = {
        "scenario_type": scenario_type,
    }
    if total_processing_time is not None:
        kw["total_processing_time"] = round(total_processing_time, 4)
    if file_count is not None:
        kw["file_count"] = file_count
    if used_ocr is not None:
        kw["used_ocr"] = used_ocr
    if reason is not None:
        kw["reason"] = reason
    log_event(
        log,
        event=event,
        user_id=user_id,
        trace_id=trace_id,
        stage=stage,
        status=status,
        **kw,
    )


__all__ = [
    "log_processing_metrics",
    "log_scenario_processing",
]
