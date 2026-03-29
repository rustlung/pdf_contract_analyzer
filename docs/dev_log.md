# Dev Log

## 2026-03-29 - Telegram processing metrics + MVP global lock

- **Метрики времени для Telegram:** для тяжёлых сценариев (распознавание, анализ, сравнение, сохранение в Drive по запросу) в лог пишутся `scenario_started` / `scenario_completed`, `processing_metrics` с `total_processing_time` и этапами (`ocr_time`, `masking_time`, `analysis_time`, `comparison_time`, `docx_generation_time`, `drive_save_time` — только если этап выполнялся), плюс `trace_id`, `user_id`, `scenario_type`, `used_ocr`, `file_count` (stage=`BOT` в метриках). Пользователю метрики не показываются.
- **Защита от параллельной обработки (MVP):** **in-memory lock заменён на shared lock** между `dm-api` и `dm-bot` на базе **SQLite** (`data/processing_lock.sqlite3` + общий volume `./data:/app/data`). Теперь блокировка реально работает **между вебом и Telegram**. События: `lock_check`, `lock_acquired`, `lock_busy`, `lock_released` (плюс `trace_id`, `scenario_type`, `interface_type`). Освобождение — в `finally` при успехе и ошибке. Веб-обработчик `POST /web/run` и bot handlers используют общий gate; общий хелпер метрик — `src/shared/scenario_metrics.py`.

## 2026-03-29 - Logging + analysis disclaimer normalization

- В `main.py` для логгера `src` добавлен собственный `StreamHandler` (stderr) и `propagate=False`, чтобы записи `src.*` не отбрасывались из‑за отсутствия обработчиков у root / `lastResort` (WARNING); уровни по-прежнему из `LOG_LEVEL`. В compose для uvicorn указан `--log-level info`.
- Дисклеймер анализа: функция `normalize_analysis_disclaimer` — ответы вида «не указано» заменяются на юридический fallback; то же в шаблоне `result.html` для старых сохранённых результатов.

## 2026-03-29 - Web UX, analysis disclaimer, processing metrics

- В форме веб-загрузки скрыта опция «Вернуть распознанные результаты» для режимов распознавания и сравнения; для анализа блок оставлен (заглушка).
- На странице старта OAuth Google Drive добавлена кнопка «Вернуться в DocuMind» (`/web/upload`), сохранена кнопка возврата в Telegram.
- Анализ договора: гарантирован текст дисклеймера (`ANALYSIS_DISCLAIMER_FALLBACK`) при пустом ответе модели; единообразно в LLM-сервисе, Telegram, веб-отчёте и `result.html`.
- После submit формы: состояние загрузки (кнопка «Обработка…», подсказка про 10–20 секунд).
- Фиксация времени: `DocumentProcessingResult.ocr_seconds` при OCR в PDF; в `web_pipeline` и `web_run` — метрики этапов и `total_processing_time`, лог `processing_metrics` и `elapsed_seconds` в `web_scenario_completed`.

## 2026-03-29 - Web UI end-to-end backend

- Веб-интерфейс на Jinja2 подключён к реальной backend-логике: распознавание (PDF → DOCX), анализ и сравнение договоров через существующие pipeline, masking и LLM-сервисы.
- Реализованы `POST /web/run`, выдача результатов на `GET /web/result`, скачивание DOCX, файловое хранилище результатов (`web_result_store`), сессионные токены для загрузок.
- Интегрирован существующий Google Drive OAuth и pending save: для веб-клиента `client=web`, передача `web_result_token`, обновление ссылки на файл в метаданных после callback; Telegram-уведомления для веб не дублируются.
- Добавлен `SessionMiddleware` и переменная окружения `SESSION_SECRET`; обновлены `README.md` и `.env.example`.

## 2026-03-23 - Stage 1: Project skeleton

- Создан каркас проекта в модульной структуре (`src/api`, `src/bot`, `tests`, `docs`).
- Добавлены Docker-сервисы `dm-api` и `dm-bot` и сеть `dm-net` в `docker-compose.yml`.
- Поднят базовый API-сервис на FastAPI с endpoint-ами `/health` и `/ping`.
- Подготовлены `/.env.example`, `/README.md` и расширенный `/.gitignore` для локальной разработки.

## 2026-03-23 - Stage 2: Base Telegram bot

- Создан базовый Telegram-бот в `src/bot/main.py` на `aiogram`.
- Добавлена команда `/start` с приветствием и списком будущих режимов.
- Добавлена понятная ошибка при отсутствии `TELEGRAM_BOT_TOKEN`.
- Обновлены `Dockerfile.bot`, `requirements.bot.txt`, `README.md` и служебные файлы проекта.

## 2026-03-23 - Stage 3: Telegram UX and FSM routing

- Реализовано главное меню режимов после `/start`.
- Добавлены состояния FSM: выбор режима, ожидание одного документа, ожидание первого и второго документов для сравнения, ожидание пользовательских опций.
- Подготовлена маршрутизация пользовательских сценариев с заглушечными ответами без бизнес-обработки файлов.
- Обновлены `README.md`, `docs/dev_log.md` и `.gitignore`.

## 2026-03-23 - Stage 4: File intake, validation and options flow

- Реализован прием входных документов в боте для режимов распознавания, анализа и сравнения.
- Добавлена валидация форматов по metadata Telegram-документа (`PDF`, `DOCX`) с понятными сообщениями об ошибках.
- Реализован сбор пользовательских опций сценария (`save_to_drive`, `return_recognized_results`, `return_destination`) через FSM.
- Добавлен финальный summary-заглушка по завершению сценария: режим, количество файлов, имена, типы и выбранные опции.
- Обновлены `README.md`, `docs/dev_log.md` и `.gitignore`.

## 2026-03-23 - Stage 5: Document input pipeline

- Реализован модуль обработки входных документов `PDF` и `DOCX` в `src/api/documents`.
- Добавлено определение текстового слоя в PDF через direct extraction и порог минимального текста.
- Добавлен OCR fallback для сканированных PDF на базе `pytesseract` + `PyMuPDF`.
- Добавлен единый сервис `process_document(...)` с результатом: формат, метод извлечения, `raw_text`, количество страниц и флаг OCR.
- Добавлено логирование этапов document pipeline: входной формат, метод извлечения, запуск OCR и итоговый размер текста.
- Обновлены `requirements.api.txt`, `Dockerfile.api`, `README.md`, `docs/dev_log.md` и `.gitignore`.

## 2026-03-23 - Stage 6: Bot integration with document pipeline

- Document pipeline подключен к Telegram-боту для режимов распознавания, анализа и сравнения.
- Бот теперь скачивает байты файлов из Telegram и передает их в `process_document(...)`.
- Реализованы пользовательские статусы: файл получен, извлечение текста, OCR fallback (если применен), обработка завершена.
- Summary бота переведен на реальные результаты извлечения: формат, `extraction_method`, `used_ocr`, `pages_count`, длина текста и выбранные опции.
- Для режима сравнения реализована отдельная обработка обоих документов с сохранением результатов в FSM state data.
- Добавлена обработка и логирование ошибок извлечения текста в bot layer.
- Обновлены `requirements.bot.txt`, `Dockerfile.bot`, `README.md`, `docs/dev_log.md` и `.gitignore`.

## 2026-03-23 - Stage 7: Local masking pipeline

- Реализован модуль локальной деперсонализации текста в `src/shared/masking`.
- Добавлены rule-based правила замены чувствительных данных: email, телефоны, ИНН, КПП, ОГРН/ОГРНИП, банковские реквизиты, адреса, ФИО и названия организаций.
- Добавлена поддержка ролевых сущностей (`Заказчик`, `Исполнитель`, `Подрядчик`, `Покупатель`, `Продавец`) и технических маркеров (`EMAIL_1`, `PHONE_1`, `INN_1` и т.д.).
- Подготовлен safe text pipeline для будущей передачи текста в LLM без сохранения исходных данных на диск.
- Добавлены логирование masking pipeline и demo helper для локальной проверки.
- Обновлены `README.md`, `docs/dev_log.md` и `.gitignore`.

## 2026-03-23 - Stage 8: Precise masking refinement

- Исправлена агрессивная логика masking: убраны жадные шаблоны, захватывающие крупные фрагменты текста.
- Введена точечная замена сущностей без удаления соседних юридических формулировок и пунктов договора.
- Порядок masking приведен к безопасному сценарию: сначала форматные сущности, затем организации/ИП, ФИО, адреса.
- Добавлен in-memory debug helper: количество замен, типы замен и примеры `old -> token` без записи чувствительных данных на диск.
- Добавлены минимальные тесты корректности деперсонализации и сохранности смыслового текста (`tests/test_masking_pipeline.py`).
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 9: Company token mapping improvement

- Улучшен mapping организаций в masking pipeline: разные компании получают разные токены (`COMPANY_1`, `COMPANY_2`, ...).
- Для повторного упоминания одной и той же организации в рамках одного вызова используется тот же токен через локальный in-memory mapping.
- Добавлен учет `unique_companies_count` и статистика `COMPANY_UNIQUE` в результате masking.
- Добавлена проверка в тестах для стабильного mapping компаний.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 10: Masking coverage refinement for real contracts

- Улучшено masking ФИО: полные ФИО маскируются целиком без частичных хвостов.
- Добавлено masking паспортных данных РФ (серия/номер паспорта) с токеном `PASSPORT_n`.
- Усилено masking банковских реквизитов в блоках реквизитов: `Р/с` -> `ACCOUNT_n`, `К/с` -> `KS_n`, `БИК` -> `BIK_n`.
- Улучшено masking адресов в явных контекстах реквизитов/регистрации (`Адрес:`, `зарегистрированный по адресу:`) без агрессивного захвата произвольных фрагментов.
- Добавлены тесты на ФИО, паспорт, банковские реквизиты, контекстные адреса и сохранность смыслового текста.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 11: Span-based masking overlap fix

- Masking pipeline переведен с последовательного `replace` на безопасную span-based обработку.
- Реализован сбор всех совпадений с позициями (`start`, `end`, `type`, `value`) и объединение в единый список.
- Добавлено разрешение пересечений по приоритету (`PASSPORT > ACCOUNT > COMPANY > PERSON > ADDRESS`), чтобы исключить конфликтные замены.
- Замены выполняются slicing-операциями от конца текста к началу, что устраняет артефакты вида `PERSON_1 Николаевич` и `ADDRESS_1евны`.
- Сохранен локальный mapping одинаковых сущностей в рамках одного вызова без записи на диск.
- Добавлены проверки на отсутствие артефактов перекрытия в `tests/test_masking_pipeline.py`.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 12: FIO and registration address refinement

- Улучшено masking полных ФИО: добавлена обработка падежных форм, чтобы не оставались хвосты отчества.
- Усилено masking адресов регистрации в явных контекстах: `зарегистрированный/зарегистрированная/зарегистрировано по адресу:` и `Адрес регистрации:`.
- Ограничен захват адресного фрагмента до юридических стоп-слов (`именуем...`, `действующ...`, `с одной стороны`), чтобы не ломать соседние формулировки.
- Добавлены тесты на полное masking ФИО, отсутствие хвостов и корректное masking адреса регистрации без разрушения юридического хвоста.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 13: Bot integration with masking pipeline

- Masking pipeline подключен к Telegram-боту для режимов распознавания, анализа и сравнения.
- После извлечения текста бот запускает локальную деперсонализацию и сохраняет результаты masking в FSM state data.
- Добавлен пользовательский статус `Деперсонализация данных` в сценариях обработки документов.
- Summary бота дополнен статистикой masking: `replacements_count` и `replacement_stats` по каждому документу.
- Для режима сравнения masking выполняется отдельно для каждого из двух документов.
- Добавлена обработка и логирование ошибок masking в bot layer.
- Обновлены `README.md`, `docs/dev_log.md` и `.gitignore`.

## 2026-03-23 - Stage 14: Single-contract LLM analysis module

- Добавлен базовый LLM-клиент через proxyapi в `src/llm/llm_client.py`.
- Реализован сервис анализа одного договора `ContractAnalysisService` в `src/llm/contract_analysis_service.py`.
- Добавлен structured JSON output для анализа договора и parser/validation результата модели.
- Добавлена обработка ошибок LLM и ошибок парсинга JSON с понятными исключениями и логированием.
- Добавлены demo-запуски для локальной проверки LLM-клиента и сервиса анализа.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 15: Telegram analyze mode end-to-end with LLM

- Режим `Анализ договора` подключен к end-to-end цепочке: `document -> masking -> LLM -> response` в Telegram-боте.
- После деперсонализации бот запускает `ContractAnalysisService` и отправляет пользователю структурированный результат анализа в чат.
- Добавлены статусы AI-этапа: `AI-анализ договора` и `Анализ завершён`.
- Добавлена обработка и логирование ошибок AI-анализа в bot layer без дублирования бизнес-логики в handlers.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 16: Contract structuring + DOCX generation module

- Реализован отдельный сервис структурирования договора через LLM: `src/llm/contract_structuring_service.py`.
- Добавлен structured JSON output для сценария распознавания и parser/validation ответа модели.
- Добавлен генератор `.docx` из структурированных данных: `src/api/documents/docx_generator.py`.
- Добавлен мини-скрипт локального ручного прогона: `scripts/demo_contract_structuring.py`.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 17: DOCX reconstruction from extracted text

- Реализован сервис реконструкции `.docx` из извлеченного текста: `src/api/documents/docx_reconstruction_service.py`.
- Добавлен базовый алгоритм восстановления структуры: обработка пустых строк, нумерации, заголовков (включая `ДОГОВОР ...`), строк в верхнем регистре и маркированных списков.
- Добавлено минимальное форматирование MVP: заголовки в `bold`, списки через `List Bullet`, основной текст обычными абзацами.
- Добавлен тестовый скрипт локального прогона: `scripts/test_docx_reconstruction.py`.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 18: DOCX reconstruction normalization

- Улучшена реконструкция `.docx`: добавлен отдельный этап нормализации текста перед генерацией (`src/api/documents/text_normalizer.py`).
- Реализована MVP-логика склейки технических переносов строк с сохранением структурных блоков (заголовки, нумерация, списки, разделители абзацев).
- Снижено количество артефактов вида обрывков фраз и лишних коротких абзацев, особенно в шапке и реквизитах.
- Обновлен тестовый funnel-скрипт `scripts/test_pdf_input_funnel.py`: теперь показывает статистику `raw_lines` -> `normalized_paragraphs`.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 19: Telegram recognize mode PDF/DOCX -> DOCX

- Добавлен режим в Telegram-боте: `📄 Распознать документ (PDF → DOCX)`.
- Реализован bot-side pipeline без LLM и masking: `process_document -> normalize_extracted_text_for_docx -> DocxReconstructionService`.
- В сценарий добавлены статусы обработки: `📄 Файл получен`, `🔍 Извлечение текста`, `🧠 OCR (если требуется)`, `🧹 Обработка текста`, `📝 Генерация DOCX`.
- Бот отправляет пользователю результат `output.docx` и сообщение `✅ Документ готов`.
- Добавлено логирование начала/завершения, имени файла, времени выполнения и ошибок с traceback.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 20: Recognize mode hardening (PDF-only + OCR Cyrillic + Drive UX stub)

- Режим распознавания в Telegram-боте ограничен только PDF; для DOCX добавлено явное сообщение: `❌ Режим распознавания работает только с PDF-файлами`.
- OCR доработан для кириллицы: в `pytesseract` явно установлен язык `rus+eng`, добавлено логирование OCR engine/lang и этапов запуска.
- В Docker-окружении добавлен русский language pack для tesseract: `tesseract-ocr-rus` (`Dockerfile.api`, `Dockerfile.bot`).
- Возвращена UX-ветка выбора сохранения результата в Google Drive как заглушка (без OAuth/интеграции): вопрос `Сохранить результат в Google Drive?` и сообщение о доступности функции на следующем этапе.
- Добавлено логирование выбора пользователя `save_to_drive` и успешной генерации результата.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 21: Two-contract comparison module via LLM

- Реализован сервис сравнения двух договоров через LLM: `src/llm/contract_comparison_service.py`.
- Добавлен structured JSON output для сравнения и parser/validation ответа модели.
- Реализована обработка ошибок LLM и ошибок JSON parsing с понятными исключениями и логированием.
- Добавлен мини-скрипт тестового прогона: `scripts/test_contract_comparison.py`.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 22: Telegram compare mode end-to-end with LLM

- Режим `Сравнение договоров` подключен к end-to-end цепочке: `document -> masking -> LLM comparison -> response` в Telegram-боте.
- Для каждого из двух документов выполняются отдельные этапы извлечения текста и деперсонализации с пользовательскими статусами.
- Добавлены статусы AI-этапа: `AI-сравнение договоров` и `Сравнение завершено`.
- Бот отправляет структурированный сравнительный результат в чат: summary, ключевые различия, изменения по сторонам/предмету/срокам/оплате/обязанностям, риски и дисклеймер.
- Добавлена обработка и логирование ошибок AI-сравнения в bot layer без дублирования бизнес-логики.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 23: Google Drive OAuth + user Drive save service (backend MVP)

- Реализован OAuth 2.0 flow для подключения Google Drive пользователя: старт авторизации и callback в FastAPI.
- Добавлено MVP-хранилище токенов пользователя (sqlite) по `telegram_user_id` без попадания токенов в git.
- Реализован сервис сохранения файла в Google Drive пользователя от его имени (не service account).
- Добавлены endpoint-ы для демо: connect, callback, status и upload.
- Обновлены `README.md`, `docs/dev_log.md` и `.gitignore`.

## 2026-03-23 - Stage 24: Google Drive integration in Telegram bot (MVP)

- Подключена реальная интеграция Google Drive к Telegram-боту через вызовы FastAPI (status/upload).
- Добавлена кнопка `Подключить Google Drive` с ссылкой на OAuth connect endpoint.
- Включено реальное сохранение результатов:
  - распознавание: загрузка `output.docx`
  - анализ: загрузка `analysis_report.txt`
  - сравнение: загрузка `comparison_report.txt` при выборе destination=Drive
- Добавлены bot env-настройки для API base URL: internal (для контейнера) и public (для ссылки пользователю).
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 25: Drive pending operation flow fix

- Исправлен UX flow сохранения в Google Drive: при неподключенном Drive бот создает pending operation и не требует повторять сценарий вручную.
- Добавлен механизм pending save operation в backend (sqlite): после успешного OAuth callback сохранение продолжается автоматически.
- Реализована авто-нотификация пользователя в Telegram после завершения отложенного сохранения.
- Подключено к режимам распознавания, анализа и сравнения в точках, где уже есть UX выбора сохранения в Drive.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 26: Telegram UX polish (texts and formatting)

- Унифицированы пользовательские статусы обработки в режиме распознавания/анализа/сравнения: единый стиль формулировок и эмодзи.
- Улучшен формат финальных сообщений для анализа и сравнения: структурированные блоки вместо "сырых" ответов.
- Технические формулировки ошибок заменены на пользовательские сообщения без внутренних деталей реализации.
- Доработаны UX-тексты Google Drive (не подключен/подключен/сохранено) и добавлены микро-подсказки по продолжению работы.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 27: Telegram UX cleanup (remove debug summaries)

- Из пользовательских ответов после анализа и сравнения убрана техническая статистика сценариев (extraction/masking counters и опции).
- Debug-информация сохранена во внутренних данных и логах, но больше не отображается в чате.
- Обновлены `README.md` и `docs/dev_log.md`.

## 2026-03-23 - Stage 28: Structured logging + trace_id

- Добавлен единый `trace_id` (uuid) на сценарий в Telegram-боте и прокидывание его в ключевые шаги.
- Введен минимальный helper структурированных логов `log_event(...)` (event/user_id/trace_id/stage/status + контекст).
- Добавлены ключевые события логирования для диагностики: сценарий, pipeline, OCR, анализ, сравнение, Google Drive, OAuth.
- Debug/trace данные не отображаются пользователю, используются только в логах.

## 2026-03-23 - Stage 29: Google Drive callback page UX polish

- Улучшен UI страницы результата подключения Google Drive (`/google-drive/connect`, `/google-drive/callback`): минималистичный светлый дизайн, карточка по центру, зелёный акцент успеха.
- Скрыта техническая информация (telegram_user_id, raw URL не отображается текстом).
- Добавлены понятные действия: открыть файл в Google Drive (если есть ссылка) и вернуться в Telegram.

## 2026-03-23 - Stage 30: Web UI shell (Jinja2 + static)

- Добавлен каркас веб-интерфейса на Jinja2: `web/templates/` (`base`, `index`, `upload`, `result`, `drive_callback`), стили `web/static/css/app.css`.
- В FastAPI подключены `Jinja2Templates`, раздача `/static`, маршруты `/`, `/web`, `/web/upload`, `/web/result`, `/web/drive-callback-preview` (mock/preview, без реального pipeline).
- Docker-образ API копирует каталог `web/`; в `requirements.api.txt` добавлен `jinja2`.
- Обновлены `README.md` и `.env.example` (опционально `TELEGRAM_BOT_URL`).
