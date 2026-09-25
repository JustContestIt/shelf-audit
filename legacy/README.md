# legacy/ — наследие n8n

Это исторические артефакты. Они нужны, чтобы было видно, что и откуда портировано. Новая система их не
импортирует и не запускает.

## n8n/

Очищенные экспорты workflow на 31.08–01.09:

| файл | что это |
|---|---|
| `MainWF_v9.2_sheets_cold.json` | Main WF (88 узлов): бот, авторизация по телефону, маршруты, буфер альбомов, карточки, ✅ / 🔄 |
| `WF2_v4.3_noreven.json` | WF-2: конвейер распознавания (проход 1, «Парсинг» v7.5-format-geo, проход 2 v9-groups, «Слияние») |
| `sheets_sync_WF.json` | копия каталога в Data Table в 05:40, выгрузка утверждённых строк в Sheets в 21:00 |
| `buffer_cleanup_WF_v2.json` | ночная чистка буфера фото |

**Очистка — `clean_exports.py`.** Скрипт вырезает:

- `pinData`, id инстанса, версии и workflow;
- id и имена credentials, webhook id;
- id и URL Google Sheets / Drive, URI Files API;
- литеральные Telegram chat id;
- всё, что похоже на токен бота или API-ключ.

Узлы, код, промпты и связи остаются. В старых экспортах токен боевого бота лежал прямо в узлах. Сам токен
нужно отозвать у @BotFather, даже если в этих файлах его уже нет.

```bash
python legacy/n8n/clean_exports.py --source "C:/.../Artyom" MainWF_v9.2_sheets_cold.json WF2_v4.3_noreven.json \
       sheets_sync_WF.json buffer_cleanup_WF_v2.json
make gitleaks        # проверить результат
```

**Где портированный код.** Код узлов «Парсинг», «Сборка запроса Pro» и «Слияние подвидов» портирован строка в
строку в `backend/app/vision/postprocess.py`. Оригинальный JS этих узлов лежит в `backend/tests/js_parity/n8n_nodes/`
и выполняется в Node в тесте паритета.

## prompts/

История промптов v0 → v7.5 и прохода 2 v8 → v9: BUILD-заметки из `archive/` рабочей папки. Сводка лежит в
[docs/PROMPTS.md](../docs/PROMPTS.md). Импорт с редактурой:

```bash
python legacy/prompts/import_history.py --artyom "C:/.../Artyom"
```

**Что редактируется:**

- chat id и прочие длинные числовые id → `<id>`;
- токены → `<bot_token>`;
- id таблиц → `<sheet_id>`;
- e-mail и телефоны;
- названия магазинов из тестовых кадров → `<магазин>`.

Список названий лежит в `data/redact_words.txt` и в git не попадает.

Файлы, которые не импортируются, потому что в них есть части токена или id таблицы: `document_input_BUILD.md`,
`MIGRATION_datatables_BUILD.md`, `catalog_filler_APPS_SCRIPT.md`.
