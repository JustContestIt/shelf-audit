# shelf-audit-mcp

MCP-сервер поверх HTTP API shelf-audit. Своей логики у сервера нет, все tool'ы идут в тот же FastAPI, что кабинет
и бот.

| tool | что делает |
|---|---|
| `analyze_shelf_photo(photo_path \| photo_base64, store_code, store_name?, agent_id?, wait_seconds?)` | запускает граф на фото и ждёт отчёт (останавливается на проверке человеком); возвращает строки по полкам и ссылку на экран проверки |
| `search_catalog(query? \| image_path?, brand?, k?)` | SKU по тексту (стемминг: «вишня компотай» → «Компотай вишневый») или эталоны по фото (визуальный RAG) |
| `get_store_report(store_code, day?, include_pending?)` | фейсинги точки по бренду × вкусу × таре из утверждённых отчётов, плюс атомарные строки |
| `list_pending_reviews(store_code?, limit?)` | отчёты, ждущие супервайзера |

## Запуск

```bash
cd mcp_server && uv pip install -e ".[dev]"
shelf-audit-mcp                                   # stdio: Claude Desktop / Claude Code
shelf-audit-mcp --transport http --port 8765      # streamable HTTP: http://localhost:8765/mcp (сервис mcp в compose)
```

Переменные окружения:

- `API_BASE_URL` — по умолчанию `http://localhost:8000`;
- `API_TOKEN` — если API закрыт токеном;
- `CABINET_URL` — для ссылок в ответах, по умолчанию `http://localhost:8080`.

## Claude Desktop

`claude_desktop_config.json`: на Windows это `%APPDATA%\Claude\`, на macOS — `~/Library/Application Support/Claude/`.

```json
{
  "mcpServers": {
    "shelf-audit": {
      "command": "C:/Users/<you>/Desktop/NFactorial/Final project/shelf-audit/.venv/Scripts/shelf-audit-mcp.exe",
      "env": {
        "API_BASE_URL": "http://localhost:8000",
        "CABINET_URL": "http://localhost:8080"
      }
    }
  }
}
```

Если API поднят в Docker, можно подключиться к HTTP-серверу из compose. Для этого в Claude Desktop нужен
коннектор с URL `http://localhost:8765/mcp` или мост `npx mcp-remote http://localhost:8765/mcp`.

Claude Code: `claude mcp add shelf-audit -- shelf-audit-mcp` или `claude mcp add --transport http shelf-audit http://localhost:8765/mcp`.

Вместе с сервером стоит подключить Skill [`skills/shelf-audit-report`](../skills/shelf-audit-report): Claude Desktop →
Settings → Capabilities → Skills → загрузить папку в zip. Тогда на запрос «сводка по магазину 00-0000001 за
сегодня» Claude сам вызовет `get_store_report` и соберёт xlsx.

## Тесты

`pytest -q`: tool'ы вызываются через клиент FastMCP in-memory, а HTTP API подменяется `httpx.MockTransport`.
Сквозная проверка на живом API: stdio-клиент → `analyze_shelf_photo` (IMG_0643, replay) → утверждение →
`get_store_report` → `export_report.py` → xlsx. Она проходила на демо-стенде: 65 ед. на IMG_0643, 53 на IMG_0644.
