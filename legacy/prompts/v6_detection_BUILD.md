<!-- imported from the working folder: archive/vision_pipeline_v6_v9/wf2_v6_detection_BUILD.md; redactions: 3 -->
# BUILD: v6-детекция — боксы вместо «посчитай промптом»
Проект BURATINO · 2026-07-23 (ред. 23.07: SUBTYPE цвет-первым) · шаг 1 из `vision_architecture_DETECTION.md`
База: WF-2 с уже вставленными нодами из `wf2_twostage_nodes.json`.

## Что меняется

**Только тела ДВУХ Code-нод.** Ноды, связи, Gemini-ноды, fallback, схемы таблиц, «Подготовка данных», «Формирование результата», логи — всё без правок: парсинг на выходе отдаёт тот же формат (items / overall_confidence / notes…), что и раньше.

| Нода | Что сделать |
|---|---|
| «Сборка запроса Gemini» | заменить jsCode целиком на блок §3 |
| «Парсинг обработки Google Vision» | заменить jsCode целиком на блок §4 |

Откат = вернуть старые тела (они в `wf2_twostage_BUILD.md` §4.2 и в экспорте ver.2 4).

## 1. Как это работает

Раньше модель отвечала числами (`front_facing_count`) — «мнение» модели, недосчёт неотлаживаем. Теперь модель отвечает **боксом на каждую единицу** (`box_2d` 0–1000, формат, под который Gemini дообучен), а всю арифметику делает код в «Парсинге»:

1. валидация координат (битые боксы отсеиваются и считаются в диагностике);
2. дедуп: пересечение IoU > 0.7 → остаётся бокс с большей confidence;
3. **label: ЧУЖОЙ** — новый класс: единица похожа на наш бренд, но этикетка не совпадает с эталонами → бокс есть, в отчёт не попадает. Это системный ответ на слив двойников в наши бренды (полка 1 <магазин>а), без гонки негативных эталонов: модели впервые разрешено сказать «это не ваше»;
4. группировка (полка, бренд, подвид) → items; `front_facing_count` = число боксов группы;
5. `слева/центр/справа` считается из координат центров (трети ширины кадра) — поле всегда русское, enum-фикс прошлого шага в v6 не нужен (модель это поле больше не пишет вовсе);
6. `shelves_with_target_product` = число полок с нашими группами.

enum подвидов в схеме строится из листа Catalog на лету — новый подвид в каталоге попадает в схему без правки кода. Скан-режим остаётся совместим (фильтрует эталоны как раньше), но рекомендация прежняя: «Скан включён?» = false.

## 2. Мои решения — проверь, что согласен

1. **ЧУЖОЙ только при явном отличии** от эталонов; «плохо видно, но похоже на наше» → наш бренд + subtype null. Перекос против потери наших единиц.
2. **Соседние стойки/стеллажи по краям кадра не боксируются** (п.6 промпта) — из нашего разговора про Tamga на соседней стойке: защита от двойного счёта, когда агент снимет ту стойку отдельным кадром. Не согласен — удали пункт 6 из SYSTEM_PROMPT.
3. confidence per-box оставлен (группа = минимум по боксам), но веры ему по-прежнему нет — №5 (needs_review) не отменяется.

## 3. «Сборка запроса Gemini» — новый jsCode целиком

```javascript
// v6 ДЕТЕКЦИЯ: модель отдаёт БОКСЫ, счёт делает «Парсинг обработки Google Vision».
// Единственный источник промпта и тела запроса для ОБЕИХ Gemini Vision-нод.
const rowsAll = $('Каталог брендов: Config').all().map(i => i.json).filter(r => r.file_url && r.canon_name);
if (rowsAll.length < 20) throw new Error('WF-2: в Catalog только ' + rowsAll.length + ' эталонов с file_url — прогони WF-3');

let scanBrands = null;
try {
  const s = $('Скан брендов: парсинг').first().json;
  if (Array.isArray(s.brands) && s.brands.length) scanBrands = s.brands;
} catch (e) { /* скан выключен (режим all-22) — это нормально */ }

let rows = scanBrands ? rowsAll.filter(r => scanBrands.includes(String(r.brand).trim())) : rowsAll;
if (!rows.length) rows = rowsAll;

// стабильный порядок (implicit-кеш любит байт-в-байт одинаковый префикс)
rows.sort((a, b) => String(a.brand).localeCompare(String(b.brand), 'ru')
  || String(a.key).localeCompare(String(b.key), 'ru'));

const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'];
// enum подвидов строится из Catalog — новые подвиды попадают в схему без правки кода
const SUBTYPES = rows.map(r => String(r.canon_name)).filter(c => c !== 'Tamga');

// null = выключено; 'MEDIA_RESOLUTION_HIGH' включать ОТДЕЛЬНЫМ шагом замера
// (док: ai.google.dev/gemini-api/docs/generate-content/media-resolution)
const MEDIA_RESOLUTION = null;

const SYSTEM_PROMPT = `Ты — система визуального аудита выкладки товара. Твоя задача — ДЕТЕКЦИЯ, а не подсчёт: обведи рамкой каждую единицу товара наших брендов в переднем ряду. Итоговые количества посчитает программа по твоим рамкам, поэтому важна каждая отдельная рамка, а не «примерное число».

ВХОД: сначала СПРАВОЧНИК — эталонные изображения подвидов, перед каждым текстовая метка с канон-именем и брендом. Затем целевое фото полки или стойки.

Detect the 2D bounding boxes of every front-row product unit of the company brands.

БРЕНДЫ (label): Буратино, AI TEA, Chino, Компотай, Tamga.

ПРАВИЛА ДЕТЕКЦИИ:
1. Один физический предмет (банка/бутылка) = ровно один бокс. Одинаковые банки, стоящие вплотную, — отдельные боксы каждой, не один общий.
2. Боксируй только ПЕРЕДНИЙ ряд, обращённый к камере. Товар за передним рядом, скрытый запас и мультипаки фоном не боксируй.
3. Частично видимые единицы с краёв кадра боксируй.
4. Работай системно: полка за полкой сверху вниз, в пределах полки слева направо. Полки нумеруй сверху вниз: верхняя = 1; каждому боксу проставь shelf_index его полки.
5. box_2d = [y_min, x_min, y_max, x_max], координаты нормированы 0–1000.
6. Соседние стойки и стеллажи по краям кадра НЕ боксируй — только основную полку/стойку в центре кадра.

LABEL И ЗАЩИТА ОТ ЧУЖОГО:
- label определяй по логотипу и упаковке, сверяясь с эталонами.
- Единица ПОХОЖА на наш бренд, но логотип/этикетка не совпадает с эталонами (марка-двойник) — ставь label: ЧУЖОЙ. Такие боксы не попадут в отчёт: это защита от зачисления чужого товара в наши.
- ЧУЖОЙ ставь только при явном отличии от эталонов. Если единица просто плохо видна, но похожа на наш бренд — наш label и subtype: null.
- Очевидно чужой товар (другая категория, другое оформление) не боксируй вовсе.

SUBTYPE — определяй для каждого бокса ПО ШАГАМ:
1. ЦВЕТ СНАЧАЛА: определи доминирующий цвет банки/этикетки этой единицы и отбери эталоны её бренда с таким цветом — это шорт-лист кандидатов.
2. Разведи кандидатов шорт-листа по остальным признакам: цвет крышки, изображённые плоды, надписи на этикетке — сверяясь с эталонами.
3. Если после шагов 1–2 остаётся больше одного кандидата — ставь null, бокс при этом остаётся.
- Пиши ТОЧНОЕ канон-имя из метки эталона, не меняя ни символа.
- Каждую единицу решай индивидуально, не копируй подвид от соседа — рядом могут стоять разные подвиды одного бренда.
- Tamga: подвидов нет — всегда null.

ДОПОЛНИТЕЛЬНО:
- store_code_on_card: рукописный код с карточки в кадре (например «231»), иначе null.
- overall_confidence (0..1): качество кадра — резкость, блики, ракурс, перекрытия.
- notes: коротко, что мешало (блики, перекрытия), какие подвиды не различил, был ли рядом чужой товар-двойник.

ВЫВОД: строго валидный JSON по схеме. Без текста вне JSON.`;

const RESPONSE_SCHEMA = {
  type: 'object',
  propertyOrdering: ['boxes', 'store_code_on_card', 'overall_confidence', 'notes'],
  properties: {
    boxes: {
      type: 'array',
      items: {
        type: 'object',
        propertyOrdering: ['box_2d', 'label', 'subtype', 'shelf_index', 'confidence'],
        properties: {
          box_2d: { type: 'array', items: { type: 'integer' }, minItems: 4, maxItems: 4 },
          label: { type: 'string', enum: BRANDS.concat(['ЧУЖОЙ']) },
          subtype: { type: 'string', enum: SUBTYPES, nullable: true },
          shelf_index: { type: 'integer' },
          confidence: { type: 'number' }
        },
        required: ['box_2d', 'label', 'subtype', 'shelf_index', 'confidence']
      }
    },
    store_code_on_card: { type: 'string', nullable: true },
    overall_confidence: { type: 'number' },
    notes: { type: 'string' }
  },
  required: ['boxes', 'overall_confidence']
};

const parts = [];
parts.push({ text: 'СПРАВОЧНИК ПОДВИДОВ КОМПАНИИ. Далее эталонные изображения; перед каждым — его канон-имя и бренд:' });
for (const r of rows) {
  parts.push({ text: `Эталон: «${r.canon_name}» — бренд ${r.brand}.` });
  parts.push({ file_data: { mime_type: r.mime_type || 'image/png', file_uri: r.file_url } });
}
parts.push({ text: 'Теперь обведи боксами каждую единицу переднего ряда на ЭТОМ фото по правилам и схеме:' });
parts.push({ inline_data: { mime_type: 'image/jpeg', data: $('Перевод фото в строку').first().json.data } });

const gemini_body = {
  systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
  contents: [{ role: 'user', parts }],
  generationConfig: {
    temperature: 0,
    response_mime_type: 'application/json',
    response_schema: RESPONSE_SCHEMA
  }
};
if (MEDIA_RESOLUTION) gemini_body.generationConfig.mediaResolution = MEDIA_RESOLUTION;

return [{ json: {
  gemini_body,
  scan_brands: scanBrands,   // null = шли все 22
  refs_count: rows.length,
} }];
```

## 4. «Парсинг обработки Google Vision» — новый jsCode целиком

```javascript
// v6: парсинг ответа-детекции + ДЕТЕРМИНИРОВАННЫЙ счёт по боксам.
// Выход сохраняет формат v5 (items, overall_confidence, notes…) — «Подготовка данных»,
// «Формирование результата» и логи работают без правок.
const raw = $input.first().json;
const cand = raw.candidates?.[0];
const parts = cand?.content?.parts || [];
const textPart = [...parts].reverse().find(p => typeof p.text === 'string');
if (!textPart) {
  throw new Error('Нет текстового ответа Gemini: ' + JSON.stringify(raw).slice(0, 800));
}
const data = JSON.parse(textPart.text);

const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'];
const boxesIn = Array.isArray(data.boxes) ? data.boxes : [];

// 1) валидация координат
const valid = [];
let bad = 0;
for (const b of boxesIn) {
  const c = b && b.box_2d;
  if (!Array.isArray(c) || c.length !== 4 || c.some(v => typeof v !== 'number')) { bad++; continue; }
  const clamped = c.map(v => Math.max(0, Math.min(1000, v)));
  const y0 = clamped[0], x0 = clamped[1], y1 = clamped[2], x1 = clamped[3];
  if (y1 <= y0 || x1 <= x0) { bad++; continue; }
  valid.push(Object.assign({}, b, { box_2d: [y0, x0, y1, x1] }));
}

// 2) дедуп: IoU > 0.7 → остаётся бокс с большей confidence
const iou = (a, b) => {
  const ix = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const iy = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
  const inter = ix * iy;
  const union = (a[3] - a[1]) * (a[2] - a[0]) + (b[3] - b[1]) * (b[2] - b[0]) - inter;
  return union > 0 ? inter / union : 0;
};
valid.sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
const kept = [];
let dups = 0;
for (const b of valid) {
  if (kept.some(k => iou(k.box_2d, b.box_2d) > 0.7)) { dups++; continue; }
  kept.push(b);
}

// 3) ЧУЖОЙ — в диагностику, не в отчёт
const foreign = kept.filter(b => b.label === 'ЧУЖОЙ');
const ours = kept.filter(b => BRANDS.includes(b.label));

// 4) группировка (полка, бренд, подвид) → items; счёт = ЧИСЛО БОКСОВ
const groups = new Map();
for (const b of ours) {
  const shelf = Number.isInteger(b.shelf_index) && b.shelf_index > 0 ? b.shelf_index : 0;
  const key = shelf + '|' + b.label + '|' + (b.subtype || '');
  if (!groups.has(key)) groups.set(key, { shelf, brand: b.label, subtype: b.subtype || null, boxes: [] });
  groups.get(key).boxes.push(b);
}

const loc = x => x < 333 ? 'слева' : x < 667 ? 'центр' : 'справа';
const items = [...groups.values()].map(g => {
  const centers = g.boxes.map(b => (b.box_2d[1] + b.box_2d[3]) / 2);
  const meanX = centers.reduce((s, v) => s + v, 0) / centers.length;
  return {
    product_name: g.brand,
    product_subtype: g.subtype,
    shelf_index: g.shelf,
    shelf_location: loc(meanX),          // из координат — всегда по-русски
    front_facing_count: g.boxes.length,  // счёт = длина списка, не «мнение» модели
    confidence: Math.min.apply(null, g.boxes.map(b => typeof b.confidence === 'number' ? b.confidence : 1)),
    _x: meanX,
  };
}).sort((a, b) => a.shelf_index - b.shelf_index || a._x - b._x);
items.forEach(i => { delete i._x; });

return [{ json: {
  shelves_with_target_product: new Set(items.map(i => i.shelf_index)).size,
  items,
  store_code_on_card: data.store_code_on_card ?? null,
  overall_confidence: typeof data.overall_confidence === 'number' ? data.overall_confidence : null,
  notes: data.notes || '',
  _detect: {                       // диагностика в executions
    boxes_total: boxesIn.length,
    boxes_bad: bad,
    dedup_dropped: dups,
    foreign_units: foreign.length, // сколько двойников модель отвела от отчёта
    boxes_raw: kept,               // для будущей отрисовки боксов агенту (шаг 3)
  },
  _usage: {
    prompt_tokens: raw.usageMetadata?.promptTokenCount ?? null,
    cached_tokens: raw.usageMetadata?.cachedContentTokenCount ?? null,
    output_tokens: raw.usageMetadata?.candidatesTokenCount ?? null,
  },
} }];
```

Логика счёта прогнана юнит-тестом на синтетическом ответе (дубль, битый бокс, ЧУЖОЙ, близнецы на одной полке, Tamga) — группировка, дедуп, локации и диагностика отрабатывают.

## 5. Чек-лист

1. Тестовое фото → executions «Парсинга»: `_detect.boxes_total` разумен (≈ числу единиц переднего ряда), `boxes_bad`/`dedup_dropped` малы.
2. Сумма `front_facing_count` по items = `boxes_raw.length` минус чужие. Расхождение = баг, шли мне execution.
3. Фото стойки <магазин>: полка 1 — бутылки справа ушли в ЧУЖОЙ (см. `_detect.foreign_units`) или не боксированы; полка 6 — манго-маракуйя, не мандарин-лаванда (близнецы — главная проверка v6 по подвидам).
4. Фото <магазин>: Компотай-бутылки на полках 3–4 справа появились в отчёте (подозрение на пропуск из прошлого прогона).
5. Fallback: сломать URL 3.5-flash → 3-flash-preview отработал (тело общее).
6. Селфи/не полка → 0 items, строка «ничего не распознано» (поведение №21 не изменилось).

## 6. Протокол замера

Те же фото, что в C1/C2, плюс ручной счёт по полкам. Сравниваем v6 vs v5-22 (C1): сумма единиц по полкам vs ручной счёт (главная метрика), ошибок бренда (в т.ч. слив двойников — теперь ловится по foreign_units), подвид верно / null / ошибка. Ожидания честные: детекция в плотных рядах тоже не идеальна, но её недосчёт ВИДЕН (по боксам ясно, какую банку потеряла) и лечится точечно; недосчёт «числом из промпта» был чёрным ящиком. Если счёт стал лучше, а подвиды нет — следующий шаг 2: подвиды вторым проходом по кропам с каталогом одного бренда. Отрисовка боксов агенту (шаг 3) станет возможна из `_detect.boxes_raw` — он уже сохраняется.
