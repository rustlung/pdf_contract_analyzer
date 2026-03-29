import logging
import time
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from aiogram.types import Message, ReplyKeyboardRemove

from src.bot.keyboards import (
    ANALYZE_MODE,
    CANCEL_OPTION,
    COMPARE_MODE,
    DESTINATION_CHAT,
    DESTINATION_DRIVE,
    NO_OPTION,
    RECOGNIZE_MODE,
    YES_OPTION,
    drive_connect_keyboard,
    file_wait_keyboard,
    main_menu_keyboard,
    destination_keyboard,
    yes_no_keyboard,
)
from src.api.documents.document_types import DocumentProcessingError
from src.llm.contract_analysis_service import normalize_analysis_disclaimer
from src.bot.services import (
    BotContractAnalysisError,
    BotContractComparisonError,
    DriveUploadResult,
    GoogleDriveBotServiceError,
    MaskingServiceError,
    BotRecognitionError,
    analyze_masked_contract,
    build_drive_connect_url,
    compare_masked_contracts,
    create_pending_drive_operation,
    is_drive_connected,
    process_masking,
    process_telegram_document,
    run_recognition_pipeline_from_file_meta,
    upload_file_to_drive,
)
from src.bot.states import BotFlow
from src.shared.logging_events import log_event
from src.shared.processing_gate import (
    TELEGRAM_BUSY_MESSAGE,
    release_processing,
    try_acquire_processing,
)
from src.shared.scenario_metrics import log_processing_metrics, log_scenario_processing

router = Router()
logger = logging.getLogger(__name__)

MODE_RECOGNIZE = "recognize"
MODE_ANALYZE = "analyze"
MODE_COMPARE = "compare"

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def detect_document_type(file_name: str | None, mime_type: str | None) -> str | None:
    normalized_name = (file_name or "").lower()
    normalized_mime = (mime_type or "").lower()

    if normalized_mime == PDF_MIME or normalized_name.endswith(".pdf"):
        return "PDF"
    if normalized_mime == DOCX_MIME or normalized_name.endswith(".docx"):
        return "DOCX"
    return None


def format_summary(data: dict) -> str:
    mode_label = data.get("mode_label", "не указан")
    files = data.get("files", [])
    options = data.get("options", {})

    files_block = "\n".join(
        [
            (
                f"- {item['name']}\n"
                f"  формат: {item['format']}\n"
                f"  extraction_method: {item['extraction_method']}\n"
                f"  used_ocr: {item['used_ocr']}\n"
                f"  pages_count: {item['pages_count']}\n"
                f"  text_length: {item['text_length']}\n"
                f"  replacements_count: {item['replacements_count']}\n"
                f"  replacement_stats: {item['replacement_stats']}"
            )
            for item in files
        ]
    )
    if not files_block:
        files_block = "- файлов нет"

    options_block = "\n".join(
        [
            f"- {key}: {value}"
            for key, value in options.items()
        ]
    )
    if not options_block:
        options_block = "- опции не выбраны"

    return (
        "Сценарий завершен.\n\n"
        f"Режим: {mode_label}\n"
        f"Количество файлов: {len(files)}\n"
        f"Файлы:\n{files_block}\n"
        f"Опции:\n{options_block}"
    )


def _result_to_state_file_item(result: dict) -> dict:
    return {
        "name": result["filename"],
        "format": result["source_type"].upper(),
        "extraction_method": result["extraction_method"],
        "used_ocr": result["used_ocr"],
        "pages_count": result["pages_count"],
        "text_length": len(result["raw_text"]),
        "replacements_count": result["replacements_count"],
        "replacement_stats": result["replacement_stats"],
        "raw_text": result["raw_text"],
        "masked_text": result["masked_text"],
    }


def _render_contract_analysis(result: dict) -> str:
    analysis = result.get("analysis")
    if not analysis:
        return "Анализ не выполнен."

    def text_or_default(value: str | None) -> str:
        if value is None:
            return "не указано"
        value = str(value).strip()
        return value if value else "не указано"

    def list_or_default(value: list[str]) -> str:
        if not value:
            return "не указано"
        return "\n".join(f"- {item}" for item in value)

    disc = normalize_analysis_disclaimer(analysis.get("disclaimer"))

    return (
        "📄 Результат анализа договора\n\n"
        f"🧾 Тип документа:\n{text_or_default(analysis.get('document_type'))}\n\n"
        f"👥 Стороны:\n{list_or_default(analysis.get('parties', []))}\n\n"
        f"📄 Предмет:\n{text_or_default(analysis.get('subject'))}\n\n"
        f"💰 Финансовые условия:\n{text_or_default(analysis.get('payment_terms'))}\n\n"
        f"📅 Сроки:\n{text_or_default(analysis.get('term'))}\n\n"
        f"⚠️ Возможные риски:\n{list_or_default(analysis.get('risks', []))}\n\n"
        f"ℹ️ {disc}"
    )


def _render_contract_comparison(comparison: dict) -> str:
    def text_or_default(value: str | None, default: str = "не выявлено") -> str:
        if value is None:
            return default
        value = str(value).strip()
        return value if value else default

    def list_or_default(value: list[str], default: str = "не выявлено") -> str:
        if not value:
            return default
        return "\n".join(f"- {item}" for item in value)

    return (
        "📊 Сравнение договоров\n\n"
        f"📌 Основные различия:\n{list_or_default(comparison.get('major_differences', []))}\n\n"
        f"👥 Стороны:\n{text_or_default(comparison.get('parties_changes'))}\n\n"
        f"📅 Сроки:\n{text_or_default(comparison.get('term_changes'))}\n\n"
        f"💰 Оплата:\n{text_or_default(comparison.get('payment_changes'))}\n\n"
        f"📄 Предмет:\n{text_or_default(comparison.get('subject_changes'))}\n\n"
        f"⚠️ Риски:\n{list_or_default(comparison.get('risks', []))}"
    )


async def _ensure_drive_connected_or_prompt(message: Message, *, trace_id: str | None = None) -> bool:
    if not message.from_user:
        await message.answer("❌ Не удалось определить пользователя Telegram для Google Drive.")
        return False

    telegram_user_id = message.from_user.id
    try:
        connected = await is_drive_connected(telegram_user_id, trace_id=trace_id)
    except GoogleDriveBotServiceError:
        logger.exception("Drive status check failed in bot")
        connected = False

    if connected:
        return True

    url = build_drive_connect_url(telegram_user_id, trace_id=trace_id)
    await message.answer(
        "☁️ Google Drive не подключён\n"
        "Подключите его по кнопке выше — после этого сохранение продолжится автоматически.",
        reply_markup=drive_connect_keyboard(url),
    )
    return False


async def _extract_document_with_statuses(
    message: Message, *, trace_id: str | None = None
) -> tuple[dict, dict[str, float]]:
    """Извлечение текста + маскирование для режима «Анализ» (без LLM).

    Сообщения здесь — только про pipeline до LLM. Фразы «анализирую договор» (LLM) и
    «формирую результат» отправляет обработчик после вызова этой функции.
    """
    if not message.document:
        raise DocumentProcessingError("Файл документа не найден в сообщении.")

    await message.answer("📄 Документ получен")
    await message.answer("📥 Извлекаю текст из документа...")
    await message.answer("⏳ Это может занять до 10–20 секунд")

    result = await process_telegram_document(
        bot=message.bot,
        document=message.document,
        trace_id=trace_id,
        user_id=message.from_user.id if message.from_user else None,
    )
    if result.used_ocr:
        await message.answer("📄 Выполняю OCR для сканированного текста...")

    await message.answer("🔒 Маскирую персональные данные для безопасной передачи в модель...")
    try:
        t_m = time.perf_counter()
        masking_result = process_masking(result.raw_text)
        masking_time = time.perf_counter() - t_m
    except MaskingServiceError as exc:
        logger.exception("Masking pipeline failed")
        raise MaskingServiceError("Masking pipeline failed") from exc

    await message.answer("✅ Текст подготовлен к анализу")
    timings: dict[str, float] = {"masking_time": masking_time}
    if result.ocr_seconds is not None:
        timings["ocr_time"] = result.ocr_seconds
    extracted = {
        "filename": result.filename,
        "source_type": result.source_type,
        "extraction_method": result.extraction_method,
        "used_ocr": result.used_ocr,
        "pages_count": result.pages_count,
        "raw_text": result.raw_text,
        "masked_text": masking_result.masked_text,
        "replacements_count": masking_result.replacements_count,
        "replacement_stats": masking_result.replacement_stats,
    }
    return extracted, timings


_COMPARE_LABEL_TO_ORDINAL = {"первого": "первый", "второго": "второй"}


async def _extract_compare_document_with_statuses(
    message: Message,
    label: str,
    *,
    trace_id: str | None = None,
) -> tuple[dict, dict[str, float]]:
    if not message.document:
        raise DocumentProcessingError("Файл документа не найден в сообщении.")

    ordinal = _COMPARE_LABEL_TO_ORDINAL.get(label, label)

    await message.answer(f"🔍 Выполняю распознавание {label} документа...")
    await message.answer("⏳ Это может занять до 10–20 секунд")
    result = await process_telegram_document(
        bot=message.bot,
        document=message.document,
        trace_id=trace_id,
        user_id=message.from_user.id if message.from_user else None,
    )
    if result.used_ocr:
        await message.answer(f"🔍 Выполняю распознавание {label} документа...")

    await message.answer(f"🧠 Анализирую {ordinal} документ...")
    try:
        t_m = time.perf_counter()
        masking_result = process_masking(result.raw_text)
        masking_time = time.perf_counter() - t_m
    except MaskingServiceError as exc:
        logger.exception("Masking pipeline failed for %s document", label)
        raise MaskingServiceError("Masking pipeline failed") from exc

    timings: dict[str, float] = {"masking_time": masking_time}
    if result.ocr_seconds is not None:
        timings["ocr_time"] = result.ocr_seconds
    extracted = {
        "filename": result.filename,
        "source_type": result.source_type,
        "extraction_method": result.extraction_method,
        "used_ocr": result.used_ocr,
        "pages_count": result.pages_count,
        "raw_text": result.raw_text,
        "masked_text": masking_result.masked_text,
        "replacements_count": masking_result.replacements_count,
        "replacement_stats": masking_result.replacement_stats,
    }
    return extracted, timings


MAIN_MENU_PROMPT = "Выберите режим:"


async def show_main_menu_reply(message: Message) -> None:
    """Показать reply-клавиатуру главного меню. Нужен непустой видимый text: Telegram отклоняет '' и \\u200b."""
    await message.answer(MAIN_MENU_PROMPT, reply_markup=main_menu_keyboard())


async def finalize_scenario(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    trace_id = data.get("trace_id")
    started_at = data.get("scenario_started_at")
    duration_ms: int | None = None
    if isinstance(started_at, (int, float)):
        duration_ms = int((time.perf_counter() - float(started_at)) * 1000)

    log_event(
        logger,
        event="scenario_completed",
        user_id=message.from_user.id if message.from_user else None,
        trace_id=trace_id,
        stage="SCENARIO",
        status="success",
        mode=data.get("mode"),
        duration_ms=duration_ms,
    )
    await state.set_state(BotFlow.choosing_mode)
    logger.info("Scenario technical summary:\n%s", format_summary(data))
    await show_main_menu_reply(message)
    await state.update_data(mode=None, mode_label=None, files=[], options={})


@router.message(BotFlow.choosing_mode, F.text == RECOGNIZE_MODE)
async def choose_recognize_mode(message: Message, state: FSMContext) -> None:
    trace_id = str(uuid.uuid4())
    await state.set_state(BotFlow.waiting_single_document)
    await state.set_data(
        {
            "mode": MODE_RECOGNIZE,
            "mode_label": RECOGNIZE_MODE,
            "files": [],
            "options": {},
            "trace_id": trace_id,
            "scenario_started_at": time.perf_counter(),
        }
    )
    log_event(
        logger,
        event="scenario_started",
        user_id=message.from_user.id if message.from_user else None,
        trace_id=trace_id,
        stage="SCENARIO",
        status="start",
        mode=MODE_RECOGNIZE,
    )
    await message.answer(
        "Выбран режим: распознать документ и вернуть DOCX.\n"
        "Ожидаю 1 файл в формате PDF.",
        reply_markup=file_wait_keyboard(),
    )


@router.message(BotFlow.choosing_mode, F.text == ANALYZE_MODE)
async def choose_analyze_mode(message: Message, state: FSMContext) -> None:
    trace_id = str(uuid.uuid4())
    await state.set_state(BotFlow.waiting_single_document)
    await state.set_data(
        {
            "mode": MODE_ANALYZE,
            "mode_label": ANALYZE_MODE,
            "files": [],
            "options": {},
            "trace_id": trace_id,
            "scenario_started_at": time.perf_counter(),
        }
    )
    log_event(
        logger,
        event="scenario_started",
        user_id=message.from_user.id if message.from_user else None,
        trace_id=trace_id,
        stage="SCENARIO",
        status="start",
        mode=MODE_ANALYZE,
    )
    await message.answer(
        "Выбран режим: анализ договора.\n"
        "Ожидаю 1 файл в формате PDF или DOCX.",
        reply_markup=file_wait_keyboard(),
    )


@router.message(BotFlow.choosing_mode, F.text == COMPARE_MODE)
async def choose_compare_mode(message: Message, state: FSMContext) -> None:
    trace_id = str(uuid.uuid4())
    await state.set_state(BotFlow.waiting_compare_first_document)
    await state.set_data(
        {
            "mode": MODE_COMPARE,
            "mode_label": COMPARE_MODE,
            "files": [],
            "options": {},
            "trace_id": trace_id,
            "scenario_started_at": time.perf_counter(),
        }
    )
    log_event(
        logger,
        event="scenario_started",
        user_id=message.from_user.id if message.from_user else None,
        trace_id=trace_id,
        stage="SCENARIO",
        status="start",
        mode=MODE_COMPARE,
    )
    await message.answer(
        "Выбран режим: сравнение договоров.\n"
        "Ожидаю первый файл (PDF или DOCX).",
        reply_markup=file_wait_keyboard(),
    )


@router.message(BotFlow.waiting_single_document, F.document)
async def receive_single_document(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    mode = data.get("mode")
    trace_id = data.get("trace_id")
    file_type = detect_document_type(message.document.file_name, message.document.mime_type)

    log_event(
        logger,
        event="document_received",
        user_id=message.from_user.id if message.from_user else None,
        trace_id=trace_id,
        stage="PIPELINE",
        status="start",
        mode=mode,
        filename=message.document.file_name,
        mime_type=message.document.mime_type,
        detected_type=file_type,
    )

    if mode == MODE_RECOGNIZE and file_type not in {"PDF", "DOCX"}:
        log_event(
            logger,
            event="document_validated",
            user_id=message.from_user.id if message.from_user else None,
            trace_id=trace_id,
            stage="PIPELINE",
            status="error",
            mode=mode,
            reason="unsupported_format",
            detected_type=file_type,
        )
        await message.answer(
            "Недопустимый формат файла.\n"
            "Для режима распознавания допустимы PDF или DOCX.\n"
            "Пожалуйста, пришлите файл формата PDF или DOCX."
        )
        return
    if mode == MODE_RECOGNIZE and file_type == "DOCX":
        log_event(
            logger,
            event="document_validated",
            user_id=message.from_user.id if message.from_user else None,
            trace_id=trace_id,
            stage="PIPELINE",
            status="error",
            mode=mode,
            reason="recognize_pdf_only",
            detected_type=file_type,
        )
        await message.answer("❌ Режим распознавания работает только с PDF-файлами")
        return
    if mode == MODE_ANALYZE and file_type not in {"PDF", "DOCX"}:
        log_event(
            logger,
            event="document_validated",
            user_id=message.from_user.id if message.from_user else None,
            trace_id=trace_id,
            stage="PIPELINE",
            status="error",
            mode=mode,
            reason="unsupported_format",
            detected_type=file_type,
        )
        await message.answer(
            "Недопустимый формат файла.\n"
            "Для режима анализа допустимы PDF или DOCX.\n"
            "Пожалуйста, пришлите файл формата PDF или DOCX."
        )
        return

    log_event(
        logger,
        event="document_validated",
        user_id=message.from_user.id if message.from_user else None,
        trace_id=trace_id,
        stage="PIPELINE",
        status="success",
        mode=mode,
        detected_type=file_type,
    )

    if mode == MODE_RECOGNIZE:
        await state.set_state(BotFlow.waiting_recognize_save_to_drive)
        await state.update_data(
            pending_document={
                "file_id": message.document.file_id,
                "file_name": message.document.file_name or "input.pdf",
                "mime_type": message.document.mime_type,
            }
        )
        await message.answer("📄 Файл получен")
        await message.answer("Сохранить результат в Google Drive?", reply_markup=yes_no_keyboard())
        return

    lock_token: str | None = None
    uid = message.from_user.id if message.from_user else None
    try:
        lock_token = try_acquire_processing(
            channel="telegram",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_ANALYZE,
        )
        if not lock_token:
            await message.answer(TELEGRAM_BUSY_MESSAGE)
            return
        t_proc = time.perf_counter()
        log_scenario_processing(
            logger,
            event="scenario_started",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_ANALYZE,
            status="start",
        )
        log_event(
            logger,
            event="pipeline_started",
            user_id=uid,
            trace_id=trace_id,
            stage="PIPELINE",
            status="start",
            mode=mode,
        )
        extracted, ext_timings = await _extract_document_with_statuses(message, trace_id=trace_id)
        files = [_result_to_state_file_item(extracted)]
        options = data.get("options", {})
        await state.update_data(files=files, options=options)

        await message.answer("🧠 Анализирую документ...")
        log_event(
            logger,
            event="analysis_started",
            user_id=uid,
            trace_id=trace_id,
            stage="ANALYSIS",
            status="start",
            filename=extracted.get("filename"),
        )
        t_a = time.perf_counter()
        analysis_result = analyze_masked_contract(extracted["masked_text"])
        ext_timings["analysis_time"] = time.perf_counter() - t_a
        log_event(
            logger,
            event="analysis_completed",
            user_id=uid,
            trace_id=trace_id,
            stage="ANALYSIS",
            status="success",
            filename=extracted.get("filename"),
        )

        ext_timings["total_processing_time"] = time.perf_counter() - t_proc
        log_processing_metrics(
            logger,
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_ANALYZE,
            stage="BOT",
            timings=ext_timings,
            file_count=1,
            used_ocr=bool(extracted.get("used_ocr")),
        )
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_ANALYZE,
            status="success",
            total_processing_time=ext_timings["total_processing_time"],
            file_count=1,
            used_ocr=bool(extracted.get("used_ocr")),
        )

        await message.answer("📊 Формирую результат...")
        await state.update_data(
            files=[
                {
                    **files[0],
                    "analysis": {
                        "document_type": analysis_result.document_type,
                        "summary": analysis_result.summary,
                        "parties": analysis_result.parties,
                        "subject": analysis_result.subject,
                        "term": analysis_result.term,
                        "payment_terms": analysis_result.payment_terms,
                        "obligations": analysis_result.obligations,
                        "risks": analysis_result.risks,
                        "disclaimer": analysis_result.disclaimer,
                    },
                }
            ]
        )
        latest_data = await state.get_data()
        analysis_message = _render_contract_analysis(latest_data["files"][0])
        await message.answer(analysis_message)
        await message.answer("✅ Анализ завершён")
        await state.set_state(BotFlow.waiting_save_to_drive)
        await message.answer(
            "Сохранить результат анализа в Google Drive?",
            reply_markup=yes_no_keyboard(),
        )
        return
    except DocumentProcessingError as exc:
        log_event(
            logger,
            event="pipeline_failed",
            user_id=uid,
            trace_id=trace_id,
            stage="PIPELINE",
            status="error",
            mode=mode,
            filename=message.document.file_name,
            reason=str(exc),
        )
        logger.exception("Document pipeline failed for single document")
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_ANALYZE,
            status="error",
            reason="pipeline_failed",
        )
        await message.answer(
            "❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл."
        )
        return
    except MaskingServiceError:
        log_event(
            logger,
            event="pipeline_failed",
            user_id=uid,
            trace_id=trace_id,
            stage="MASKING",
            status="error",
            mode=mode,
            filename=message.document.file_name,
        )
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_ANALYZE,
            status="error",
            reason="masking_failed",
        )
        await message.answer(
            "❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл."
        )
        return
    except BotContractAnalysisError:
        log_event(
            logger,
            event="analysis_failed",
            user_id=uid,
            trace_id=trace_id,
            stage="ANALYSIS",
            status="error",
            filename=message.document.file_name,
        )
        logger.exception("LLM contract analysis failed")
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_ANALYZE,
            status="error",
            reason="analysis_failed",
        )
        await message.answer(
            "❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл."
        )
        return
    finally:
        if lock_token:
            release_processing(
                channel="telegram",
                trace_id=trace_id,
                user_id=uid,
                lock_token=lock_token,
                scenario_type=MODE_ANALYZE,
            )


@router.message(BotFlow.waiting_compare_first_document, F.document)
async def receive_first_compare_document(message: Message, state: FSMContext) -> None:
    file_type = detect_document_type(message.document.file_name, message.document.mime_type)
    if file_type not in {"PDF", "DOCX"}:
        await message.answer(
            "Недопустимый формат файла.\n"
            "Для сравнения допустимы PDF или DOCX.\n"
            "Пожалуйста, пришлите файл формата PDF или DOCX."
        )
        return

    await message.answer("📄 Документ получен")
    data = await state.get_data()
    trace_id = data.get("trace_id")
    uid = message.from_user.id if message.from_user else None
    lock_token: str | None = None
    try:
        lock_token = try_acquire_processing(
            channel="telegram",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_COMPARE,
        )
        if not lock_token:
            await message.answer(TELEGRAM_BUSY_MESSAGE)
            return
        extracted, timings1 = await _extract_compare_document_with_statuses(message, "первого", trace_id=trace_id)
    except DocumentProcessingError as exc:
        logger.exception("Document pipeline failed for first compare document")
        await message.answer(
            "❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл."
        )
        return
    except MaskingServiceError:
        await message.answer(
            "❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл."
        )
        return
    finally:
        if lock_token:
            release_processing(
                channel="telegram",
                trace_id=trace_id,
                user_id=uid,
                lock_token=lock_token,
                scenario_type=MODE_COMPARE,
            )

    data = await state.get_data()
    files = data.get("files", [])
    files.append(_result_to_state_file_item(extracted))
    await state.update_data(files=files, compare_partial_timings=timings1)
    await state.set_state(BotFlow.waiting_compare_second_document)
    await message.answer(
        "Первый файл получен.\n"
        "Теперь пришлите второй файл (PDF или DOCX).",
        reply_markup=file_wait_keyboard(),
    )


@router.message(BotFlow.waiting_compare_second_document, F.document)
async def receive_second_compare_document(message: Message, state: FSMContext) -> None:
    file_type = detect_document_type(message.document.file_name, message.document.mime_type)
    if file_type not in {"PDF", "DOCX"}:
        await message.answer(
            "Недопустимый формат файла.\n"
            "Для сравнения допустимы PDF или DOCX.\n"
            "Пожалуйста, пришлите файл формата PDF или DOCX."
        )
        return

    await message.answer("📄 Документ получен")
    data = await state.get_data()
    trace_id = data.get("trace_id")
    partial = data.get("compare_partial_timings") or {}
    uid = message.from_user.id if message.from_user else None
    lock_token: str | None = None
    try:
        lock_token = try_acquire_processing(
            channel="telegram",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_COMPARE,
        )
        if not lock_token:
            await message.answer(TELEGRAM_BUSY_MESSAGE)
            return
        t0 = time.perf_counter()
        log_scenario_processing(
            logger,
            event="scenario_started",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_COMPARE,
            status="start",
        )
        extracted, timings2 = await _extract_compare_document_with_statuses(message, "второго", trace_id=trace_id)
        data = await state.get_data()
        files = data.get("files", [])
        files.append(_result_to_state_file_item(extracted))
        await state.update_data(files=files)

        await message.answer("🧠 Анализирую документ...")
        log_event(
            logger,
            event="comparison_started",
            user_id=uid,
            trace_id=trace_id,
            stage="COMPARISON",
            status="start",
            file1=files[0].get("name") if files else None,
            file2=files[1].get("name") if len(files) > 1 else None,
        )
        t_c = time.perf_counter()
        comparison = compare_masked_contracts(files[0]["masked_text"], files[1]["masked_text"])
        comparison_time = time.perf_counter() - t_c
        log_event(
            logger,
            event="comparison_completed",
            user_id=uid,
            trace_id=trace_id,
            stage="COMPARISON",
            status="success",
        )

        m_total = float(partial.get("masking_time", 0)) + float(timings2.get("masking_time", 0))
        ocr_sum = 0.0
        for ot in (partial.get("ocr_time"), timings2.get("ocr_time")):
            if ot is not None:
                ocr_sum += float(ot)
        metrics: dict[str, float] = {
            "masking_time": m_total,
            "comparison_time": comparison_time,
            "total_processing_time": time.perf_counter() - t0,
        }
        if ocr_sum > 0:
            metrics["ocr_time"] = ocr_sum
        used_any = bool(files[0].get("used_ocr") or files[1].get("used_ocr"))
        log_processing_metrics(
            logger,
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_COMPARE,
            stage="BOT",
            timings=metrics,
            file_count=2,
            used_ocr=used_any,
        )
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_COMPARE,
            status="success",
            total_processing_time=metrics["total_processing_time"],
            file_count=2,
            used_ocr=used_any,
        )

        await state.update_data(
            comparison={
                "summary": comparison.summary,
                "major_differences": comparison.major_differences,
                "parties_changes": comparison.parties_changes,
                "subject_changes": comparison.subject_changes,
                "term_changes": comparison.term_changes,
                "payment_changes": comparison.payment_changes,
                "obligations_changes": comparison.obligations_changes,
                "risks": comparison.risks,
                "disclaimer": comparison.disclaimer,
            },
            compare_partial_timings=None,
        )
        latest_data = await state.get_data()
        await message.answer(_render_contract_comparison(latest_data["comparison"]))
        await message.answer("📊 Формирую результат...")
        await message.answer("✅ Сравнение завершено")

        await state.set_state(BotFlow.waiting_save_to_drive)
        await message.answer(
            "Сохранять результат сравнения в Google Drive?",
            reply_markup=yes_no_keyboard(),
        )
    except DocumentProcessingError as exc:
        logger.exception("Document pipeline failed for second compare document")
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_COMPARE,
            status="error",
            reason="pipeline_failed",
        )
        await message.answer(
            "❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл."
        )
        return
    except MaskingServiceError:
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_COMPARE,
            status="error",
            reason="masking_failed",
        )
        await message.answer(
            "❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл."
        )
        return
    except BotContractComparisonError:
        log_event(
            logger,
            event="comparison_failed",
            user_id=uid,
            trace_id=trace_id,
            stage="COMPARISON",
            status="error",
        )
        logger.exception("LLM contract comparison failed")
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_COMPARE,
            status="error",
            reason="comparison_failed",
        )
        await message.answer(
            "❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл."
        )
        return
    finally:
        if lock_token:
            release_processing(
                channel="telegram",
                trace_id=trace_id,
                user_id=uid,
                lock_token=lock_token,
                scenario_type=MODE_COMPARE,
            )


@router.message(BotFlow.waiting_save_to_drive, F.text.in_({YES_OPTION, NO_OPTION}))
async def handle_save_to_drive(message: Message, state: FSMContext) -> None:
    # Hide Yes/No keyboard right after user choice.
    await message.answer("Принял выбор.", reply_markup=ReplyKeyboardRemove())
    data = await state.get_data()
    options = data.get("options", {})
    save_to_drive = message.text == YES_OPTION
    options["save_to_drive"] = "да" if save_to_drive else "нет"
    await state.update_data(options=options)
    trace_id = data.get("trace_id")
    uid = message.from_user.id if message.from_user else None

    if save_to_drive:
        lock_token = try_acquire_processing(
            channel="telegram",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=str(data.get("mode") or "save_to_drive"),
        )
        if not lock_token:
            await message.answer(TELEGRAM_BUSY_MESSAGE)
            return
        try:
            connected = await _ensure_drive_connected_or_prompt(message, trace_id=trace_id)
            if message.from_user:
                mode = data.get("mode")
                if mode == MODE_ANALYZE:
                    report_text = _render_contract_analysis(data.get("files", [{}])[0])
                    if not connected:
                        try:
                            await create_pending_drive_operation(
                                message.from_user.id,
                                scenario_type="analyze",
                                result_type="analysis_report",
                                filename="analysis_report.txt",
                                file_bytes=report_text.encode("utf-8"),
                                mime_type="text/plain",
                                trace_id=trace_id,
                            )
                            await message.answer(
                                "Google Drive не подключён. Подключите его по кнопке выше. "
                                "После подключения сохранение продолжится автоматически."
                            )
                        except GoogleDriveBotServiceError:
                            logger.exception("Failed to create pending operation (analysis)")
                            await message.answer("❌ Не удалось подготовить отложенное сохранение в Google Drive.")
                        return

                    try:
                        ds0 = time.perf_counter()
                        result: DriveUploadResult = await upload_file_to_drive(
                            message.from_user.id,
                            filename="analysis_report.txt",
                            file_bytes=report_text.encode("utf-8"),
                            mime_type="text/plain",
                            trace_id=trace_id,
                        )
                        log_processing_metrics(
                            logger,
                            trace_id=trace_id,
                            user_id=uid,
                            scenario_type=MODE_ANALYZE,
                            stage="BOT",
                            timings={"drive_save_time": time.perf_counter() - ds0},
                            file_count=1,
                            used_ocr=bool(data.get("files", [{}])[0].get("used_ocr")),
                        )
                        await message.answer(
                            "☁️ Сохраняю в Google Drive...\n☁️ Файл успешно сохранён в Google Drive"
                            + (f"\nСсылка: {result.web_link}" if result.web_link else "")
                        )
                    except GoogleDriveBotServiceError:
                        logger.exception("Drive upload failed in bot (analysis)")
                        await message.answer("❌ Не удалось сохранить файл в Google Drive. Попробуйте позже.")
                if mode == MODE_COMPARE:
                    comparison = data.get("comparison")
                    if not comparison:
                        await message.answer("❌ Нет данных сравнения для сохранения в Google Drive.")
                        await finalize_scenario(message, state)
                        return

                    report_text = _render_contract_comparison(comparison)
                    if not connected:
                        try:
                            await create_pending_drive_operation(
                                message.from_user.id,
                                scenario_type="compare",
                                result_type="comparison_report",
                                filename="comparison_report.txt",
                                file_bytes=report_text.encode("utf-8"),
                                mime_type="text/plain",
                                trace_id=trace_id,
                            )
                            await message.answer(
                                "Google Drive не подключён. Подключите его по кнопке выше. "
                                "После подключения сохранение продолжится автоматически."
                            )
                        except GoogleDriveBotServiceError:
                            logger.exception("Failed to create pending operation (compare)")
                            await message.answer("❌ Не удалось подготовить отложенное сохранение в Google Drive.")
                        return

                    try:
                        ds0 = time.perf_counter()
                        result: DriveUploadResult = await upload_file_to_drive(
                            message.from_user.id,
                            filename="comparison_report.txt",
                            file_bytes=report_text.encode("utf-8"),
                            mime_type="text/plain",
                            trace_id=trace_id,
                        )
                        files = data.get("files") or []
                        used_any = bool(
                            (len(files) > 0 and files[0].get("used_ocr"))
                            or (len(files) > 1 and files[1].get("used_ocr"))
                        )
                        log_processing_metrics(
                            logger,
                            trace_id=trace_id,
                            user_id=uid,
                            scenario_type=MODE_COMPARE,
                            stage="BOT",
                            timings={"drive_save_time": time.perf_counter() - ds0},
                            file_count=len(files) if files else 2,
                            used_ocr=used_any,
                        )
                        await message.answer(
                            "☁️ Сохраняю в Google Drive...\n☁️ Файл успешно сохранён в Google Drive"
                            + (f"\nСсылка: {result.web_link}" if result.web_link else "")
                        )
                    except GoogleDriveBotServiceError:
                        logger.exception("Drive upload failed in bot (compare)")
                        await message.answer("❌ Не удалось сохранить файл в Google Drive. Попробуйте позже.")
        finally:
            release_processing(
                channel="telegram",
                trace_id=trace_id,
                user_id=uid,
                lock_token=lock_token,
                scenario_type=str(data.get("mode") or "save_to_drive"),
            )

    data_after = await state.get_data()
    if data_after.get("mode") == MODE_COMPARE:
        files = data_after.get("files") or []
        if any(item.get("format") == "PDF" for item in files):
            await state.set_state(BotFlow.waiting_return_recognized_results)
            await message.answer(
                "Вернуть распознанные результаты?",
                reply_markup=yes_no_keyboard(),
            )
            return

    await finalize_scenario(message, state)


@router.message(BotFlow.waiting_recognize_save_to_drive, F.text.in_({YES_OPTION, NO_OPTION}))
async def handle_recognize_save_to_drive(message: Message, state: FSMContext) -> None:
    # Hide Yes/No keyboard right after user choice.
    await message.answer("Принял выбор.", reply_markup=ReplyKeyboardRemove())
    data = await state.get_data()
    pending_document = data.get("pending_document")
    if not pending_document:
        await message.answer("❌ Ошибка при обработке файла")
        await state.set_state(BotFlow.choosing_mode)
        await message.answer("Выберите режим с помощью кнопок меню.", reply_markup=main_menu_keyboard())
        return

    save_to_drive = message.text == YES_OPTION
    logger.info("Recognize mode save_to_drive selected: %s", save_to_drive)
    await state.update_data(
        options={"save_to_drive": "да" if save_to_drive else "нет"},
    )
    trace_id = data.get("trace_id")
    uid = message.from_user.id if message.from_user else None
    lock_token: str | None = None
    try:
        lock_token = try_acquire_processing(
            channel="telegram",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_RECOGNIZE,
        )
        if not lock_token:
            await message.answer(TELEGRAM_BUSY_MESSAGE)
            return
        t0 = time.perf_counter()
        log_scenario_processing(
            logger,
            event="scenario_started",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_RECOGNIZE,
            status="start",
        )
        logger.info("Recognize mode started: filename=%s", pending_document.get("file_name"))
        await message.answer("🔍 Выполняю распознавание...")
        await message.answer("⏳ Это может занять до 10–20 секунд")
        await message.answer("📊 Формирую результат...")
        try:
            recognition_result = await run_recognition_pipeline_from_file_meta(
                bot=message.bot,
                file_id=pending_document["file_id"],
                filename=pending_document["file_name"],
                mime_type=pending_document.get("mime_type"),
                trace_id=trace_id,
            )
        except BotRecognitionError:
            logger.exception("Recognize pipeline failed")
            log_scenario_processing(
                logger,
                event="scenario_completed",
                trace_id=trace_id,
                user_id=uid,
                scenario_type=MODE_RECOGNIZE,
                status="error",
                reason="recognition_failed",
            )
            await message.answer("❌ Не удалось обработать документ. Попробуйте ещё раз или отправьте другой файл.")
            return

        timings: dict[str, float] = dict(recognition_result.timings)
        doc = recognition_result.document_result
        if doc.used_ocr:
            await message.answer("🧠 OCR")

        output_file = BufferedInputFile(
            file=recognition_result.docx_bytes,
            filename="output.docx",
        )
        await message.answer_document(output_file, caption="✅ Документ готов", reply_markup=main_menu_keyboard())
        if save_to_drive:
            connected = await _ensure_drive_connected_or_prompt(message, trace_id=trace_id)
            if message.from_user:
                if not connected:
                    try:
                        await create_pending_drive_operation(
                            message.from_user.id,
                            scenario_type="recognize",
                            result_type="docx",
                            filename="output.docx",
                            file_bytes=recognition_result.docx_bytes,
                            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            trace_id=trace_id,
                        )
                    except GoogleDriveBotServiceError:
                        logger.exception("Failed to create pending operation (recognize)")
                        await message.answer("❌ Не удалось подготовить отложенное сохранение в Google Drive.")
                        log_scenario_processing(
                            logger,
                            event="scenario_completed",
                            trace_id=trace_id,
                            user_id=uid,
                            scenario_type=MODE_RECOGNIZE,
                            status="error",
                            reason="drive_pending_failed",
                        )
                        return
                    timings["total_processing_time"] = time.perf_counter() - t0
                    log_processing_metrics(
                        logger,
                        trace_id=trace_id,
                        user_id=uid,
                        scenario_type=MODE_RECOGNIZE,
                        stage="BOT",
                        timings=timings,
                        file_count=1,
                        used_ocr=bool(doc.used_ocr),
                    )
                    log_scenario_processing(
                        logger,
                        event="scenario_completed",
                        trace_id=trace_id,
                        user_id=uid,
                        scenario_type=MODE_RECOGNIZE,
                        status="success",
                        total_processing_time=timings["total_processing_time"],
                        file_count=1,
                        used_ocr=bool(doc.used_ocr),
                    )
                    logger.info(
                        "Recognize mode completed (pending drive): filename=%s elapsed_sec=%.3f",
                        pending_document.get("file_name"),
                        timings["total_processing_time"],
                    )
                    await state.set_state(BotFlow.choosing_mode)
                    await state.update_data(mode=None, mode_label=None, files=[], options={}, pending_document=None)
                    return

                try:
                    ds0 = time.perf_counter()
                    result: DriveUploadResult = await upload_file_to_drive(
                        message.from_user.id,
                        filename="output.docx",
                        file_bytes=recognition_result.docx_bytes,
                        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        trace_id=trace_id,
                    )
                    timings["drive_save_time"] = time.perf_counter() - ds0
                    await message.answer(
                        "☁️ Сохраняю в Google Drive...\n☁️ Файл успешно сохранён в Google Drive"
                        + (f"\nСсылка: {result.web_link}" if result.web_link else "")
                    )
                except GoogleDriveBotServiceError:
                    logger.exception("Drive upload failed in bot (recognize)")
                    await message.answer("❌ Не удалось сохранить файл в Google Drive. Попробуйте позже.")
                    log_scenario_processing(
                        logger,
                        event="scenario_completed",
                        trace_id=trace_id,
                        user_id=uid,
                        scenario_type=MODE_RECOGNIZE,
                        status="error",
                        reason="drive_upload_failed",
                    )
                    return

        timings["total_processing_time"] = time.perf_counter() - t0
        log_processing_metrics(
            logger,
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_RECOGNIZE,
            stage="BOT",
            timings=timings,
            file_count=1,
            used_ocr=bool(doc.used_ocr),
        )
        log_scenario_processing(
            logger,
            event="scenario_completed",
            trace_id=trace_id,
            user_id=uid,
            scenario_type=MODE_RECOGNIZE,
            status="success",
            total_processing_time=timings["total_processing_time"],
            file_count=1,
            used_ocr=bool(doc.used_ocr),
        )
        logger.info(
            "Recognize mode completed: filename=%s elapsed_sec=%.3f",
            pending_document.get("file_name"),
            timings["total_processing_time"],
        )
        await state.set_state(BotFlow.choosing_mode)
        await state.update_data(mode=None, mode_label=None, files=[], options={}, pending_document=None)
    finally:
        if lock_token:
            release_processing(
                channel="telegram",
                trace_id=trace_id,
                user_id=uid,
                lock_token=lock_token,
                scenario_type=MODE_RECOGNIZE,
            )


@router.message(
    BotFlow.waiting_return_recognized_results,
    F.text.in_({YES_OPTION, NO_OPTION}),
)
async def handle_return_recognized_results(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    options = data.get("options", {})
    is_yes = message.text == YES_OPTION
    if is_yes:
        options["return_recognized_results"] = "да (заглушка: не реализовано)"
    else:
        options["return_recognized_results"] = "нет"
    await state.update_data(options=options)

    if is_yes:
        await message.answer(
            "Возврат распознанных файлов (DOCX) в этот чат или в Google Drive в режиме сравнения "
            "пока не реализован. Если нужен готовый документ — используйте режим «Распознать документ». "
            "Сейчас вернём вас в главное меню."
        )
        await finalize_scenario(message, state)
        return

    await finalize_scenario(message, state)


@router.message(
    BotFlow.waiting_return_destination,
    F.text.in_({DESTINATION_CHAT, DESTINATION_DRIVE}),
)
async def handle_return_destination(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    options = data.get("options", {})
    options["return_destination"] = "chat" if message.text == DESTINATION_CHAT else "google_drive"
    await state.update_data(options=options)
    await state.set_state(BotFlow.waiting_save_to_drive)
    await message.answer("Сохранять результат сравнения в Google Drive?", reply_markup=yes_no_keyboard())


@router.message(BotFlow.waiting_single_document, F.text == CANCEL_OPTION)
@router.message(BotFlow.waiting_compare_first_document, F.text == CANCEL_OPTION)
@router.message(BotFlow.waiting_compare_second_document, F.text == CANCEL_OPTION)
@router.message(BotFlow.waiting_save_to_drive, F.text == CANCEL_OPTION)
@router.message(BotFlow.waiting_recognize_save_to_drive, F.text == CANCEL_OPTION)
@router.message(BotFlow.waiting_return_recognized_results, F.text == CANCEL_OPTION)
@router.message(BotFlow.waiting_return_destination, F.text == CANCEL_OPTION)
async def cancel_and_back_to_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BotFlow.choosing_mode)
    await message.answer("Сценарий отменен. Вернулись в главное меню.", reply_markup=main_menu_keyboard())


@router.message(BotFlow.waiting_single_document, F.photo)
async def single_document_photo_invalid(message: Message) -> None:
    await message.answer(
        "Недопустимый формат отправки.\n"
        "Вы отправили изображение как фото. Нужен документ-файл.\n"
        "Для распознавания: PDF. Для анализа: PDF или DOCX."
    )


@router.message(BotFlow.waiting_compare_first_document, F.photo)
async def compare_first_photo_invalid(message: Message) -> None:
    await message.answer(
        "Недопустимый формат отправки.\n"
        "Вы отправили изображение как фото. Нужен документ-файл PDF или DOCX."
    )


@router.message(BotFlow.waiting_compare_second_document, F.photo)
async def compare_second_photo_invalid(message: Message) -> None:
    await message.answer(
        "Недопустимый формат отправки.\n"
        "Вы отправили изображение как фото. Нужен документ-файл PDF или DOCX."
    )


@router.message(BotFlow.waiting_single_document)
async def single_document_hint(message: Message) -> None:
    await message.answer(
        "Ожидаю 1 документ. Допустимые форматы зависят от выбранного режима.\n"
        "Если хотите сменить процесс, нажмите «Отмена»."
    )


@router.message(BotFlow.waiting_compare_first_document)
async def first_document_hint(message: Message) -> None:
    await message.answer(
        "Ожидаю первый файл для сравнения в формате PDF или DOCX.\n"
        "Если хотите сменить процесс, нажмите «Отмена»."
    )


@router.message(BotFlow.waiting_compare_second_document)
async def second_document_hint(message: Message) -> None:
    await message.answer(
        "Ожидаю второй файл для сравнения в формате PDF или DOCX.\n"
        "Если хотите сменить процесс, нажмите «Отмена»."
    )


@router.message(BotFlow.waiting_save_to_drive)
async def waiting_save_to_drive_hint(message: Message) -> None:
    await message.answer(
        "Выберите опцию с кнопок: сохранять результат в Google Drive или нет."
    )


@router.message(BotFlow.waiting_recognize_save_to_drive)
async def waiting_recognize_save_to_drive_hint(message: Message) -> None:
    await message.answer(
        "Выберите с кнопок: сохранять результат в Google Drive или нет."
    )


@router.message(BotFlow.waiting_return_recognized_results)
async def waiting_return_recognized_results_hint(message: Message) -> None:
    await message.answer(
        "Выберите с кнопок: вернуть распознанные результаты или нет."
    )


@router.message(BotFlow.waiting_return_destination)
async def waiting_return_destination_hint(message: Message) -> None:
    await message.answer(
        "Выберите с кнопок, куда отправить результат: в чат или в Google Drive."
    )


@router.message(BotFlow.choosing_mode)
async def mode_choice_hint(message: Message) -> None:
    await message.answer("Выберите режим с помощью кнопок меню.")
