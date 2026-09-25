# shelf-audit — веб-кабинет

Кабинет супервайзера для системы аудита полки: загрузка фото, проверка рамок на фото
(«Утвердить» / «Исправить» / «Переснять»), список отчётов, результаты evals и схема графа.

React 18 + Vite + TypeScript + react-router-dom, без UI-кита: обычный CSS на CSS-переменных
(светлая тема + `prefers-color-scheme: dark`), адаптив до 390 px.

## Запуск

Нужен Node 22 (≥ 22.12) и запущенный API (FastAPI, по умолчанию `http://localhost:8000`).

```bash
npm install          # или npm ci — lock-файл закоммичен
npm run dev          # http://localhost:5173, /api проксируется на API
npm run typecheck    # tsc -b
npm test             # vitest run — юнит-тесты хелперов в src/lib
npm run build        # tsc -b && vite build -> dist/
npm run preview      # раздать dist/ на http://localhost:4173 (с тем же прокси)
```

### Прокси `/api`

Браузер всегда ходит в API по префиксу `/api` (`src/api/client.ts`, `API_BASE`):

| где            | что делает                                                                  |
| -------------- | --------------------------------------------------------------------------- |
| `vite dev` / `vite preview` | `/api/*` → `VITE_API_TARGET` (по умолчанию `http://localhost:8000`), префикс срезается |
| docker (nginx) | `/api/*` → `http://api:8000/*`, префикс срезается (`nginx.conf`)            |

Другой адрес API в dev:

```bash
VITE_API_TARGET=http://192.168.1.10:8000 npm run dev
```

(или строкой `VITE_API_TARGET=...` в `.env.local`).

### Docker

```bash
docker build -t shelf-audit-web .
docker run -p 8080:80 --network <сеть, где API доступен как "api"> shelf-audit-web
```

Многостадийная сборка: `node:22-alpine` собирает `dist/`, `nginx:alpine` раздаёт SPA
(history fallback на `index.html`) и проксирует `/api/` на `http://api:8000/`
(`client_max_body_size 25m`, `proxy_read_timeout 300s`). Сервис API в compose должен
называться `api`.

## Страницы

| путь            | что там                                                                                   |
| --------------- | ----------------------------------------------------------------------------------------- |
| `/upload`       | выбор точки (`GET /stores`), код агента, фото с предпросмотром → `POST /photos` → отчёт    |
| `/reports/:id`  | главный экран: ход обработки по узлам графа (опрос `/photos/{id}/status` каждые 1,5 с), затем фото с рамками, итоги, таблица по полкам, действия супервайзера, панели RAG / проход 2 / вызовы модели |
| `/queue`        | очередь на проверку (`GET /reviews/pending`), бейдж со счётчиком в меню                   |
| `/reports`      | все отчёты (`GET /reports`) с фильтрами по статусу и коду точки                           |
| `/evals`        | прогоны evals (`GET /evals/latest`): метрики, покадровые результаты, срезы, заметки       |
| `/about`        | граф LangGraph (`GET /graph/mermaid`, пакет `mermaid` грузится лениво) и `/health`       |

### Экран отчёта

- **Рамки** рисуются SVG поверх фото; `box_2d = [ymin, xmin, ymax, xmax]` в 0..1000
  масштабируется под фактический размер картинки (ResizeObserver — верно при ресайзе окна).
- **Цвет** — подвид (фиксированная палитра по каноническим названиям, для новых названий —
  стабильный хэш), бренд без подвида — нейтральный. Легенда под фото.
- **Пунктир** — рамка из строки `needs_review`; в таблице у такой строки ещё и бейдж
  «проверить» с причиной (цвет никогда не единственный сигнал).
- **«ЧУЖОЙ»** — серый точечный контур с ✕, в счёт не входит. Чекбокс «Показать отсеянные
  (щепки)» рисует `body.slivers` тонким красным.
- Рамка ↔ строка: `shelf_index` + `label == brand` + `subtype` + `format` (null == null).
  Клик по строке подсвечивает её рамки, клик по рамке — строку.
- **Исправить**: подвид (список из `GET /catalog?brand=` для бренда строки), тара, количество,
  удаление строки; «Сохранить правки» отправляет `action: "edit"` только с изменёнными строками.
- **Переснять**: выбор файла → `POST /reports/{id}/retake` → снова опрос статуса. Если лимит
  пересъёмок исчерпан (409), показывается `detail` из ответа.

## Структура

```
src/
  api/types.ts        типы контракта API
  api/client.ts       fetch-обёртка (база /api, ошибки FastAPI -> Error с detail)
  lib/                чистые хелперы + *.test.ts (vitest)
    colors.ts         цвет подвида, легенда
    match.ts          сопоставление рамок и строк, группировка по полкам
    format.ts         числа/деньги/время по-русски, форматирование метрик evals
    timeline.ts       таймлайн узлов графа из progress
    edits.ts          черновик правок и diff для action "edit"
    status.ts         русские названия статусов, условие опроса
    geometry.ts       box_2d -> пиксели
    errors.ts         текст ошибки из ответа FastAPI
    domain.ts         бренды, «ЧУЖОЙ», форматы тары, лимит размера фото
  components/         Layout, PhotoOverlay, ReportTable, ReviewActions, панели, UI-примитивы
  hooks/              useAsync, счётчик очереди, заголовок страницы
  pages/              страницы
  styles/global.css   токены (CSS-переменные), тёмная тема, адаптив
```
