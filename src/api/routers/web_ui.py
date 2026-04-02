"""
Jinja2 web UI: landing, upload, processing via existing pipelines, result pages.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from src.api.integrations.google_drive.oauth_service import (
    GoogleDriveOAuthError,
    create_pending_save_operation,
    is_drive_connected,
    save_file_for_user,
)
from src.api.services import web_result_store
from src.api.services.web_pipeline import (
    ContractAnalysisError,
    ContractComparisonError,
    DocumentProcessingError,
    DocxReconstructionError,
    run_analyze,
    run_compare,
    run_recognize_pdf,
)
from src.llm.contract_analysis_service import normalize_analysis_disclaimer
from src.shared.logging_events import log_event
from src.shared.processing_gate import (
    WEB_BUSY_MESSAGE,
    release_processing,
    try_acquire_processing,
)
from src.shared.scenario_metrics import log_processing_metrics

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WEB_DIR = _PROJECT_ROOT / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web"])

logger = logging.getLogger(__name__)

WEB_DRIVE_UID_BASE = 9_000_000_000_000
SESSION_TOKENS_KEY = "web_allowed_result_tokens"


def _telegram_bot_url() -> str:
    default = "https://t.me/vs_DocuMind_bot"
    return os.getenv("TELEGRAM_BOT_URL", default).strip() or default


def _get_web_drive_uid(request: Request) -> int:
    session = request.session
    key = "dm_web_drive_uid"
    if key not in session:
        session[key] = WEB_DRIVE_UID_BASE + secrets.randbelow(1_000_000_000)
    return int(session[key])


def _register_result_token(request: Request, token: str) -> None:
    session = request.session
    prev = list(session.get(SESSION_TOKENS_KEY) or [])
    prev = [token] + [t for t in prev if t != token][:24]
    session[SESSION_TOKENS_KEY] = prev
    session["web_last_result_token"] = token


def _can_download(request: Request, token: str) -> bool:
    return token in (request.session.get(SESSION_TOKENS_KEY) or [])


def _analysis_report_text(data: dict[str, Any]) -> bytes:
    a = data.get("analysis") or {}
    disc = normalize_analysis_disclaimer(a.get("disclaimer"))
    lines = [
        "DocuMind — отчёт по анализу договора",
        "",
        f"Тип документа: {a.get('document_type') or 'не указано'}",
        "",
        "Краткое резюме:",
        str(a.get("summary") or "не указано"),
        "",
        "Стороны:",
        "\n".join(f"- {p}" for p in (a.get("parties") or [])) or "не указано",
        "",
        f"Предмет: {a.get('subject') or 'не указано'}",
        f"Срок: {a.get('term') or 'не указано'}",
        f"Оплата: {a.get('payment_terms') or 'не указано'}",
        "",
        "Обязательства:",
        "\n".join(f"- {x}" for x in (a.get("obligations") or [])) or "не указано",
        "",
        "Риски:",
        "\n".join(f"- {x}" for x in (a.get("risks") or [])) or "не указано",
        "",
        f"Дисклеймер: {disc}",
    ]
    return "\n".join(lines).encode("utf-8")


def _comparison_report_text(data: dict[str, Any]) -> bytes:
    c = data.get("comparison") or {}
    lines = [
        "DocuMind — отчёт о сравнении договоров",
        "",
        f"Сводка: {c.get('summary') or 'не указано'}",
        "",
        "Ключевые различия:",
        "\n".join(f"- {x}" for x in (c.get("major_differences") or [])) or "не выявлено",
        "",
        f"Стороны: {c.get('parties_changes') or 'не выявлено'}",
        f"Предмет: {c.get('subject_changes') or 'не выявлено'}",
        f"Сроки: {c.get('term_changes') or 'не выявлено'}",
        f"Оплата: {c.get('payment_changes') or 'не выявлено'}",
        f"Обязательства: {c.get('obligations_changes') or 'не выявлено'}",
        "",
        "Риски:",
        "\n".join(f"- {x}" for x in (c.get("risks") or [])) or "не выявлено",
        "",
        f"Дисклеймер: {c.get('disclaimer') or ''}",
    ]
    return "\n".join(lines).encode("utf-8")


@router.get("/", response_class=HTMLResponse, name="web_root")
def web_root(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"telegram_bot_url": _telegram_bot_url()},
    )


@router.get("/web", response_class=HTMLResponse, name="web_index")
def web_index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"telegram_bot_url": _telegram_bot_url()},
    )


@router.get("/web/upload", response_class=HTMLResponse, name="web_upload")
def web_upload(request: Request, error: str | None = None) -> HTMLResponse:
    flash = request.session.pop("flash_error", None)
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "error": error or flash,
        },
    )


@router.post("/web/run", name="web_run")
async def web_run(
    request: Request,
    mode: str = Form(...),
    save_to_drive: str | None = Form(None),
    file1: UploadFile = File(...),
    file2: UploadFile | None = File(None),
) -> Response:
    upload_url = str(request.url_for("web_upload"))
    result_url = str(request.url_for("web_result"))
    want_drive = save_to_drive == "on"
    trace = secrets.token_hex(8)
    web_uid = _get_web_drive_uid(request)
    scenario_t0: float | None = None
    metrics: dict[str, float] = {}
    lock_token: str | None = None

    def _done_ok(elapsed_seconds: float | None = None) -> None:
        log_event(
            logger,
            event="web_scenario_completed",
            user_id=web_uid,
            trace_id=trace,
            stage="WEB",
            status="success",
            mode=mode,
            elapsed_seconds=round(elapsed_seconds, 4) if elapsed_seconds is not None else None,
        )

    def _done_err(reason: str, elapsed_seconds: float | None = None) -> None:
        log_event(
            logger,
            event="web_scenario_completed",
            user_id=web_uid,
            trace_id=trace,
            stage="WEB",
            status="error",
            mode=mode,
            reason=reason,
            elapsed_seconds=round(elapsed_seconds, 4) if elapsed_seconds is not None else None,
        )

    def _finalize_success() -> None:
        if scenario_t0 is not None:
            metrics["total_processing_time"] = time.perf_counter() - scenario_t0
            log_processing_metrics(
                logger,
                trace_id=trace,
                user_id=web_uid,
                scenario_type=mode,
                stage="WEB",
                timings=metrics,
            )
            _done_ok(metrics["total_processing_time"])
        else:
            _done_ok()

    try:
        b1 = await file1.read()
        name1 = file1.filename or "document"
        mime1 = file1.content_type

        if mode == "compare":
            if not file2:
                _done_err("missing_file2")
                request.session["flash_error"] = "Для сравнения загрузите два файла."
                return RedirectResponse(url=upload_url, status_code=303)
            b2 = await file2.read()
            name2 = file2.filename or "document2"
            mime2 = file2.content_type
            if len(b2) == 0:
                _done_err("empty_file2")
                request.session["flash_error"] = "Для сравнения загрузите второй файл."
                return RedirectResponse(url=upload_url, status_code=303)

        lock_token = try_acquire_processing(
            channel="web",
            trace_id=trace,
            user_id=web_uid,
            scenario_type=mode,
        )
        if not lock_token:
            request.session["flash_error"] = WEB_BUSY_MESSAGE
            return RedirectResponse(url=upload_url, status_code=303)

        log_event(
            logger,
            event="web_scenario_started",
            user_id=web_uid,
            trace_id=trace,
            stage="WEB",
            status="start",
            mode=mode,
            save_to_drive=want_drive,
        )

        scenario_t0 = time.perf_counter()

        if mode == "recognize":
            docx_bytes, extra = run_recognize_pdf(b1, name1, trace_id=trace)
            metrics.update(extra.pop("_timings", {}))
            token = web_result_store.create_token()
            meta = {"kind": "recognize", "trace_id": trace, **extra}
            web_result_store.save_meta(token, meta)
            web_result_store.save_docx_bytes(token, docx_bytes, "output.docx")
            _register_result_token(request, token)

            if want_drive:
                dr = await _maybe_drive_upload_or_oauth(
                    request,
                    web_uid,
                    token,
                    filename="output.docx",
                    file_bytes=docx_bytes,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    scenario_type="recognize",
                    result_type="docx",
                    trace=trace,
                    metrics=metrics,
                )
                if isinstance(dr, RedirectResponse):
                    _finalize_success()
                    return dr

            _finalize_success()
            return RedirectResponse(url=f"{result_url}?t={token}", status_code=303)

        if mode == "analyze":
            data = run_analyze(b1, name1, mime1, trace_id=trace)
            metrics.update(data.pop("_timings", {}))
            token = web_result_store.create_token()
            meta = {"kind": "analyze", "trace_id": trace, **data}
            web_result_store.save_meta(token, meta)
            _register_result_token(request, token)
            report_bytes = _analysis_report_text(meta)

            if want_drive:
                dr = await _maybe_drive_upload_or_oauth(
                    request,
                    web_uid,
                    token,
                    filename="analysis_report.txt",
                    file_bytes=report_bytes,
                    mime_type="text/plain; charset=utf-8",
                    scenario_type="analyze",
                    result_type="analysis_report",
                    trace=trace,
                    metrics=metrics,
                )
                if isinstance(dr, RedirectResponse):
                    _finalize_success()
                    return dr
            _finalize_success()
            return RedirectResponse(url=f"{result_url}?t={token}", status_code=303)

        if mode == "compare":
            data = run_compare(b1, name1, mime1, b2, name2, mime2, trace_id=trace)
            metrics.update(data.pop("_timings", {}))
            token = web_result_store.create_token()
            meta = {"kind": "compare", "trace_id": trace, **data}
            web_result_store.save_meta(token, meta)
            _register_result_token(request, token)
            report_bytes = _comparison_report_text(meta)

            if want_drive:
                dr = await _maybe_drive_upload_or_oauth(
                    request,
                    web_uid,
                    token,
                    filename="comparison_report.txt",
                    file_bytes=report_bytes,
                    mime_type="text/plain; charset=utf-8",
                    scenario_type="compare",
                    result_type="comparison_report",
                    trace=trace,
                    metrics=metrics,
                )
                if isinstance(dr, RedirectResponse):
                    _finalize_success()
                    return dr
            _finalize_success()
            return RedirectResponse(url=f"{result_url}?t={token}", status_code=303)

        _done_err("unknown_mode")
        request.session["flash_error"] = "Неизвестный режим."
        return RedirectResponse(url=upload_url, status_code=303)

    except DocumentProcessingError as exc:
        logger.exception("Web pipeline document error")
        _done_err(
            "document_processing",
            time.perf_counter() - scenario_t0 if scenario_t0 is not None else None,
        )
        request.session["flash_error"] = str(exc)
        return RedirectResponse(url=upload_url, status_code=303)
    except DocxReconstructionError as exc:
        logger.exception("Web docx reconstruction error")
        _done_err(
            "docx_reconstruction",
            time.perf_counter() - scenario_t0 if scenario_t0 is not None else None,
        )
        request.session["flash_error"] = str(exc)
        return RedirectResponse(url=upload_url, status_code=303)
    except ContractAnalysisError as exc:
        logger.exception("Web analysis error")
        _done_err(
            "contract_analysis",
            time.perf_counter() - scenario_t0 if scenario_t0 is not None else None,
        )
        request.session["flash_error"] = f"Не удалось выполнить анализ: {exc}"
        return RedirectResponse(url=upload_url, status_code=303)
    except ContractComparisonError as exc:
        logger.exception("Web comparison error")
        _done_err(
            "contract_comparison",
            time.perf_counter() - scenario_t0 if scenario_t0 is not None else None,
        )
        request.session["flash_error"] = f"Не удалось выполнить сравнение: {exc}"
        return RedirectResponse(url=upload_url, status_code=303)
    except Exception:
        logger.exception("Web scenario failed")
        _done_err(
            "unexpected",
            time.perf_counter() - scenario_t0 if scenario_t0 is not None else None,
        )
        request.session["flash_error"] = "Произошла ошибка обработки. Попробуйте позже."
        return RedirectResponse(url=upload_url, status_code=303)
    finally:
        if lock_token:
            release_processing(
                channel="web",
                trace_id=trace,
                user_id=web_uid,
                lock_token=lock_token,
                scenario_type=mode,
            )


async def _maybe_drive_upload_or_oauth(
    request: Request,
    web_uid: int,
    result_token: str,
    *,
    filename: str,
    file_bytes: bytes,
    mime_type: str,
    scenario_type: str,
    result_type: str,
    trace: str,
    metrics: dict[str, float] | None = None,
) -> RedirectResponse | None:
    try:
        connected = is_drive_connected(web_uid)
        log_event(
            logger,
            event="web_drive_decision",
            user_id=web_uid,
            trace_id=trace,
            stage="WEB",
            status="start",
            connected=connected,
            scenario_type=scenario_type,
            result_type=result_type,
        )
        if connected:
            ds0 = time.perf_counter()
            result = save_file_for_user(
                telegram_user_id=web_uid,
                filename=filename,
                file_bytes=file_bytes,
                mime_type=mime_type,
            )
            if metrics is not None:
                metrics["drive_save_time"] = time.perf_counter() - ds0
            web_result_store.update_drive_web_link(result_token, result.web_link)
            log_event(
                logger,
                event="web_drive_upload_ok",
                user_id=web_uid,
                trace_id=trace,
                stage="WEB",
                status="success",
                scenario_type=scenario_type,
            )
            return None
        create_pending_save_operation(
            telegram_user_id=web_uid,
            scenario_type=scenario_type,
            result_type=result_type,
            filename=filename,
            mime_type=mime_type,
            file_bytes=file_bytes,
        )
        log_event(
            logger,
            event="web_drive_oauth_redirect",
            user_id=web_uid,
            trace_id=trace,
            stage="WEB",
            status="success",
            scenario_type=scenario_type,
        )
    except GoogleDriveOAuthError as exc:
        logger.exception("Web Drive prepare failed")
        log_event(
            logger,
            event="web_drive_prepare_failed",
            user_id=web_uid,
            trace_id=trace,
            stage="WEB",
            status="error",
            reason=str(exc),
        )
        request.session["flash_error"] = f"Google Drive: {exc}"
        return RedirectResponse(url=str(request.url_for("web_upload")), status_code=303)

    connect_url = str(request.url_for("google_drive_connect", telegram_user_id=web_uid))
    return RedirectResponse(
        url=f"{connect_url}?client=web&web_result_token={result_token}&trace_id={trace}",
        status_code=303,
    )


@router.get("/web/result", response_class=HTMLResponse, name="web_result")
def web_result(request: Request, t: str | None = None) -> HTMLResponse:
    token = t or request.session.get("web_last_result_token")
    if not token:
        return templates.TemplateResponse(
            request,
            "result.html",
            {
                "has_data": False,
                "error": "Нет сохранённого результата. Запустите обработку на странице загрузки.",
            },
        )
    meta = web_result_store.load_meta(token)
    if not meta:
        return templates.TemplateResponse(
            request,
            "result.html",
            {"has_data": False, "error": "Результат устарел или не найден."},
        )
    # Same browser after OAuth: re-register token so DOCX download works.
    if t:
        _register_result_token(request, token)

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "has_data": True,
            "token": token,
            "meta": meta,
            "kind": meta.get("kind"),
        },
    )


@router.get("/web/download/{token}/docx", name="web_download_docx")
def web_download_docx(request: Request, token: str) -> Response:
    if not _can_download(request, token):
        return Response("Доступ запрещён", status_code=403)
    path = web_result_store.docx_path(token, "output.docx")
    if not path:
        return Response("Файл не найден", status_code=404)
    return Response(
        path.read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": 'attachment; filename="output.docx"',
        },
    )


@router.get("/web/drive-callback-preview", response_class=HTMLResponse, name="web_drive_callback_preview")
def web_drive_callback_preview(request: Request, state: str = "success") -> HTMLResponse:
    ok = state.lower() != "error"
    if ok:
        return templates.TemplateResponse(
            request,
            "drive_callback.html",
            {
                "success": True,
                "page_title": "Google Drive",
                "headline": "Google Drive подключён",
                "message": (
                    "Результат успешно сохранён в ваш Google Drive. "
                    "Можно вернуться в Telegram и продолжить работу."
                ),
                "file_url": "https://drive.google.com/",
            },
        )
    return templates.TemplateResponse(
        request,
        "drive_callback.html",
        {
            "success": False,
            "page_title": "Ошибка",
            "headline": "Не удалось завершить подключение Google Drive",
            "message": "Попробуйте ещё раз позже или вернитесь в Telegram и повторите действие.",
            "file_url": None,
        },
    )
