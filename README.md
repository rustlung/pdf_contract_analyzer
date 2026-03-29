# DocuMind

DocuMind - MVP-сервис для обработки PDF-договоров с модульной архитектурой.

**Current status:** Stage 32 / Web UX + processing metrics

## Web UI (Jinja2)

Второй интерфейс к сервису — **Jinja2** + один CSS (`web/static/css/app.css`). Обработка идёт через те же сервисы, что и в Telegram-боте (document pipeline, masking, LLM, сравнение, DOCX reconstruction), без дублирования бизнес-логики.

**UX:** после отправки формы кнопка переходит в состояние «Обработка…», показывается короткая подсказка о длительности. На странице подключения Google Drive (`/google-drive/connect/...`) есть кнопка «Вернуться в DocuMind» (веб-загрузка). Режим распознавания не показывает зарезервированную опцию «Вернуть распознанные результаты»; в режиме анализа она по-прежнему доступна как заглушка.

**Наблюдаемость:** для веб-сценариев в лог пишется событие `processing_metrics` с длительностями этапов (по необходимости: `ocr_time`, `masking_time`, `analysis_time`, `comparison_time`, `docx_generation_time`, `drive_save_time`) и `total_processing_time`, плюс `web_scenario_completed` с `elapsed_seconds`. Для **Telegram-бота** в лог пишутся `scenario_started` / `scenario_completed` и `processing_metrics` с теми же полями по этапам (если этап выполнялся), плюс `trace_id`, `user_id`, `scenario_type`, `used_ocr`, `file_count`. Метрики не показываются пользователю. Чтобы **`src.*`** в Docker не пропадали: у логгера **`src`** при старте API вешается **`StreamHandler` на stderr** и **`propagate=False`** (иначе при пустом root срабатывает только `lastResort` с уровнем WARNING и `INFO` от приложения не видны). В `.env`: **`LOG_LEVEL=INFO`**. В `docker-compose` для uvicorn: **`--log-level info`**. После правок: **`docker compose up --build`**.

**Очередь (MVP):** полноценный брокер не используется. Для защиты от параллельной тяжёлой обработки (OCR, masking, LLM-анализ/сравнение, сборка DOCX и базовый save flow) применяется **shared lock** на базе **SQLite**: `src/shared/processing_gate.py` хранит состояние в `data/processing_lock.sqlite3`, который должен быть доступен **и API, и боту** (в `docker-compose.yml` каталог `./data` монтируется в `/app/data`). Пока занято: веб показывает сообщение на странице загрузки, бот — в чате; в логах — `lock_check`, `lock_acquired`, `lock_busy`, `lock_released` с `trace_id`, `scenario_type`, `interface_type` (`web`/`telegram`).

**Режимы**

| Режим | Вход | Что делает backend |
|-------|------|-------------------|
| Распознавание | **только PDF** | pipeline → нормализация текста → сборка **DOCX** |
| Анализ | **PDF или DOCX** | pipeline → masking → **анализ договора** (LLM) |
| Сравнение | **два файла**, PDF или DOCX | pipeline + masking для каждого → **сравнение** |

**Маршруты**

- `GET /` и `GET /web` — лендинг
- `GET /web/upload` — форма (режим, файлы, опция Google Drive)
- `POST /web/run` — multipart: обработка и редирект на результат (или на OAuth Google при сохранении в Drive без подключения)
- `GET /web/result?t=...` — страница результата (распознавание: скачать DOCX; анализ/сравнение: структурированный вывод; при сохранении в Drive — ссылка на файл, если уже загружен)
- `GET /web/download/{token}/docx` — скачивание DOCX (только для токена из текущей сессии)
- `GET /web/drive-callback-preview` — превью стиля страниц callback (`?state=success` / `error`)

**Ограничения**

- Распознавание: только **PDF** (ошибка формата — сообщение на странице загрузки).
- Анализ и сравнение: **PDF и DOCX**.

**Сессия и хранилище**

- Cookie-сессия (`SessionMiddleware`): в продакшене задайте **`SESSION_SECRET`** в `.env`.
- Результаты веба: каталог `data/web_ui_results/<token>/` (`meta.json`, опционально `output.docx`). Путь можно переопределить **`DOCUMIND_WEB_RESULT_DIR`**.

Статика: `/static/css/app.css`. Опционально: `TELEGRAM_BOT_URL` — ссылка «Открыть Telegram-бот» на главной.

Зависимости API: `pip install -r requirements.api.txt` (в т.ч. `jinja2`).

## Google Drive OAuth (MVP)

Интеграция Google Drive реализуется через OAuth 2.0 **от имени пользователя** (не service account).

### Env переменные

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI` (пример: `http://localhost:8000/google-drive/callback`)
- `DRIVE_OAUTH_STATE_SECRET` (любой секрет для подписи параметра `state`)
- (опционально) `GOOGLE_OAUTH_SCOPES` (по умолчанию `drive.file`)
- (опционально) `DOCUMIND_DRIVE_TOKEN_DB` (sqlite путь, по умолчанию `data/google_drive_tokens.sqlite3`)

### Локальная проверка OAuth + upload

1. Запустите API:
   - `uvicorn src.api.main:app --reload --port 8000`
2. Получите ссылку на подключение:
   - `python -m scripts.test_google_drive_oauth --telegram-user-id 12345`
3. Откройте ссылку `connect` в браузере и пройдите consent.
4. Проверьте статус:
   - `GET /google-drive/status/12345`
5. Проверьте upload (MVP endpoint):
   - `POST /google-drive/upload/12345` (multipart form-data)

Примечание: success/error страницы `/google-drive/connect` и `/google-drive/callback` оформлены в продуктовый минималистичный стиль (без технических данных).

## Google Drive in Telegram bot (MVP)

Бот умеет сохранять результаты в Google Drive пользователя **после подключения OAuth**:
- **Распознать документ**: сохраняет итоговый `output.docx`
- **Анализ договора**: сохраняет текстовый `analysis_report.txt`
- **Сравнение договоров**: при выборе `Google Drive` сохраняет `comparison_report.txt`

Для bot-контейнера используются два base URL:
- `DM_API_INTERNAL_BASE_URL` (по умолчанию `http://dm-api:8000`) — вызовы из `dm-bot` в `dm-api`
- `DM_API_PUBLIC_BASE_URL` (по умолчанию `http://127.0.0.1:8000`) — ссылка, которую видит пользователь для OAuth connect

### Pending save flow

Если пользователь выбрал сохранение в Google Drive, но Drive еще не подключен:
- бот или **веб** создаёт ту же **pending operation** и не заставляет повторять сценарий;
- после OAuth callback backend автоматически завершает сохранение;
- в Telegram пользователь получает сообщение (для веб-клиента `client=web` уведомление в Telegram не шлётся);
- в вебе после callback можно открыть результат по ссылке с `web_result_token` — ссылка на файл в Drive подтягивается в `meta.json`.

## Telegram UX polish

- Сообщения бота приведены к единому стилю со статусами и эмодзи.
- Форматы ответа для анализа и сравнения стали структурированными и более читаемыми.
- Ошибки приведены к пользовательскому виду без технических деталей.
- Техническая статистика сценариев (extraction/masking counters, опции) не показывается в чате и остается только во внутренних данных и логах.

## Run with Docker Compose

1. Создайте `.env` на основе примера:
   - скопируйте `.env.example` в `.env`
   - заполните `TELEGRAM_BOT_TOKEN` и другие переменные при необходимости
2. Соберите и запустите сервисы:
   - `docker compose up --build`
3. Проверьте API:
   - `GET http://localhost:8000/health`
   - `GET http://localhost:8000/ping`
   - `GET http://localhost:8000/` — веб-лендинг
4. Проверьте бота:
   - откройте вашего бота в Telegram
   - отправьте команду `/start`
   - выберите режим в меню
   - отправьте документы и выберите опции по сценарию

## Services

- `dm-api` - базовый FastAPI-сервис
- `dm-bot` - Telegram-бот на `aiogram` с меню, FSM, сбором опций и реальным извлечением текста
- `dm-net` - внутренняя сеть Docker Compose

## Implemented now

- API endpoint-ы `/health` и `/ping`
- Базовый Telegram-бот с `/start`
- Telegram UX layer: меню режимов и маршрутизация пользовательского сценария
- Прием документов в Telegram-боте (без сохранения файлов на диск)
- Валидация форматов по metadata (`PDF`, `DOCX`)
- FSM-опрос опций (`save_to_drive`, `return_recognized_results`, `return_destination`)
- Короткое завершение сценария без debug-статистики
- Модуль обработки входных документов (`PDF`, `DOCX`)
- Определение текстового слоя в PDF и OCR fallback для сканированных PDF
- Единый сервис `process_document(...)` с результатом извлечения текста и метаданными
- Telegram-бот подключен к реальному document pipeline (`process_document(...)`)
- В боте показываются статусы извлечения текста и OCR fallback
- В режиме сравнения извлечение выполняется для двух документов отдельно
- Техническая статистика извлечения (extraction_method/used_ocr/pages_count/text_length) доступна в логах (не в чате)
- Добавлен локальный masking pipeline для деперсонализации текста перед будущей передачей в LLM
- Чувствительные данные заменяются rule-based правилами (email, phone, INN/KPP/OGRN, банковские данные, адреса, ФИО, организации)
- Поддержаны ролевые сущности (`Заказчик`, `Исполнитель`, `Подрядчик`, `Покупатель`, `Продавец`) и технические маркеры (`EMAIL_1`, `PHONE_1`, ...)
- Деперсонализация доработана до точечной замены сущностей без удаления смысловых пунктов договора
- Добавлен in-memory debug helper (статистика и примеры замен без записи чувствительных данных на диск)
- Улучшен mapping организаций: разные компании получают разные токены (`COMPANY_1`, `COMPANY_2`, ...), повтор одной компании использует тот же токен
- Маскирование ФИО улучшено: полные ФИО маскируются целиком без хвостов
- Добавлена поддержка паспортных данных РФ и банковых реквизитов (`PASSPORT`, `ACCOUNT`, `KS`, `BIK`)
- Адреса маскируются консервативно в явных контекстах реквизитов (`Адрес:`, `зарегистрированный по адресу:`)
- Masking переведен на позиционную span-based замену (без `str.replace`) для устранения артефактов пересечений
- Улучшено masking полных ФИО с падежными формами и адресов регистрации в явных контекстах (`зарегистрирован(а/о) по адресу`, `Адрес регистрации`)
- Telegram-бот использует document pipeline + masking pipeline в режимах распознавания/анализа/сравнения
- Техническая статистика masking (`replacements_count`, `replacement_stats`) доступна в логах (не в чате)
- Добавлен модуль анализа одного договора через LLM (`ContractAnalysisService`) со structured JSON output
- Реализован parser/validation ответа модели с обработкой ошибок
- Режим `Анализ договора` в Telegram-боте подключен end-to-end: `document -> masking -> LLM -> chat response`
- В Telegram для анализа добавлены статусы AI-этапа и вывод структурированного аналитического результата
- Добавлен сервис структурирования договора через LLM (`ContractStructuringService`) с JSON parser/validation
- Добавлен модуль генерации `.docx` из структурированных данных (`generate_contract_docx`)
- Добавлен сервис реконструкции `.docx` из извлеченного текста без LLM (`DocxReconstructionService`)
- Реализован базовый алгоритм восстановления структуры: заголовки, нумерация, списки, абзацы
- Добавлен этап нормализации текста перед реконструкцией `.docx` для склейки технических переносов и снижения артефактов
- Добавлен режим Telegram-бота `📄 Распознать документ (PDF → DOCX)` без LLM и masking
- Режим распознавания в боте подключен к цепочке `document pipeline -> normalization -> docx reconstruction -> output.docx`
- Для распознавания добавлены пользовательские статусы обработки: файл, извлечение текста, OCR (если нужен), обработка текста, генерация DOCX
- Режим распознавания ограничен только PDF (DOCX отклоняется с явным сообщением)
- OCR доработан для кириллицы: `pytesseract` запускается с языком `rus+eng`
- UX-ветка выбора сохранения в Google Drive возвращена как заглушка (без OAuth и без фактического сохранения)
- Добавлен сервис сравнения двух договоров через LLM (`ContractComparisonService`) со structured JSON output
- Добавлен parser/validation для результата сравнительного анализа и мини-скрипт тестового прогона
- Режим `Сравнение договоров` в Telegram-боте подключен end-to-end: `document -> masking -> LLM comparison -> chat response`
- Для compare-сценария добавлены статусы по документам, OCR и AI-сравнению, результат отправляется структурированным блоком в чат

## Next stages

На следующих этапах будут добавлены бизнес-функции:
- интеграция с Google Drive

## Document pipeline demo

Для локальной проверки модуля извлечения:
- `python -m src.api.documents.demo "<path-to-file.pdf|docx>"`

## Masking pipeline demo

Для локальной проверки деперсонализации:
- `python -m src.shared.masking.demo "<path-to-txt|pdf|docx-file>"`

## LLM Module

- API key в `.env`: `PROXYAPI_API_KEY`
- Базовый клиент: `src/llm/llm_client.py`
- Сервис анализа одного договора: `src/llm/contract_analysis_service.py`
- Сервис сравнения двух договоров: `src/llm/contract_comparison_service.py`
- Сервис структурирования договора: `src/llm/contract_structuring_service.py`

## Contract Comparison Demo

Для локальной проверки модуля сравнения двух договоров:
- Встроенные sample inputs:
  - `python -m scripts.test_contract_comparison`
- Свои входные данные как текстовые файлы (`masked`):
  - `python -m scripts.test_contract_comparison --text1 "path/to/text1.txt" --text2 "path/to/text2.txt"`

## Structuring + DOCX demo

Для локальной проверки сценария распознавания (без Telegram-интеграции):
- `python -m scripts.demo_contract_structuring "<path-to-file.pdf|docx>" --output-docx "tmp/structured_contract_demo.docx"`

## DOCX Reconstruction (LLM-free)

- Реконструкция строится только по `raw_text` из document pipeline
- Это восстановление структуры для редактирования, а не пиксельная копия PDF
- Перед генерацией применяется нормализация текста (склейка технических переносов, сохранение структурных абзацев)
- Тестовый запуск:
  - `python -m scripts.test_pdf_input_funnel`
  - выходной файл: `tmp/contract1_services_reconstructed.docx`

## Recognize Mode Notes

- Режим `📄 Распознать документ (PDF → DOCX)` принимает только PDF.
- После получения файла бот спрашивает: `Сохранить результат в Google Drive?` (UX-заглушка).
- При выборе `Да` после генерации выводится сообщение о будущем подключении Google Drive.

## Compare Mode Notes

- Режим `Сравнение договоров` принимает два файла (`PDF`/`DOCX`) и обрабатывает каждый документ отдельно.
- После локальной деперсонализации выполняется AI-сравнение через `ContractComparisonService`.
- В чат отправляется структурированный сравнительный результат: summary, ключевые различия, изменения по блокам, риски и дисклеймер.
