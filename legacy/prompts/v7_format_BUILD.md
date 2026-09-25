<!-- imported from the working folder: archive/vision_pipeline_v6_v9/wf2_v7_format_BUILD.md; redactions: 0 -->
# BUILD: v7 — формат тары / литраж (правка заказчика №25)
Проект BURATINO · 2026-07-28 · продолжение `wf2_v6_detection_BUILD.md` и `catalog_variants_BUILD.md`
Закрывает: определение объёма/тары каждой единицы («isq» заказчика = SKU: бренд + вкус + **объём**).

## §0. Рамка

**Что меняется: только тела ДВУХ Code-нод WF-2** («Сборка запроса Gemini» и «Парсинг обработки Google Vision»). Main WF, выбор магазина, буфер, Gemini-ноды, «Подготовка данных», «Формирование результата», логи, схемы таблиц — без правок. Новое поле `package_format` в items нижестоящие ноды просто игнорируют, пока мы не решим выводить его в таблицу (§4).

**Что НЕ делается сознательно:**
- **Новые эталоны НЕ активируются.** Формат вводится правилами по силуэту + подписями уже активных эталонов (sleever/can Компотая и так в транше 1). Серия F — чистая переменная «промпт+схема»; форматные эталоны (can900, pet05…) — отдельный транш ПОСЛЕ замера, если силуэта не хватит.
- **Chino и Tamga: format всегда null** — их линеек в мокапах нет, до SKU-справочника заказчика не гадаем. Когда справочник придёт — добавить их форматы в `FORMATS` и в блок «Допустимые форматы» промпта (два места, §2).
- **Слив-рукав = ПЭТ 1 л** (допущение: рукав — вариант оформления, не отдельный объём). Если у заказчика это отдельная позиция — поменять правило в промпте.

**Честные ожидания.** Тип тары (банка/ПЭТ) — крупный силуэтный признак, читается даже при 60–100 px, должен работать заметно надёжнее подвидов. Объём внутри типа (0,45 vs 0,9; 0,5 vs 1 л) — только пропорции и соседи, абсолютного масштаба на фото нет: здесь ждём новый класс ошибок и щедрый null. Правило «не уверен → null» стоит явно; null-ы считаются в `_detect.format_null`.

## §1. Порядок действий

1. «Сборка запроса Gemini» → заменить jsCode ЦЕЛИКОМ на §2.
   ⚠️ Перед заменой сверь две вещи со СВОЕЙ живой нодой: (а) значение `TARGET_MEDIA_RESOLUTION` — в §2 стоит `ULTRA_HIGH` (базовая конфигурация с 27.07), если у тебя другое — сохрани своё; (б) если ты уже заменял `VARIANT_NOTE` на обобщённый из README_ALL — в §2 он уже обобщённый, конфликтов нет.
2. «Парсинг обработки Google Vision» → заменить jsCode ЦЕЛИКОМ на §3.
3. Прогнать серию F по протоколу §5.

Откат = вернуть тела v6.1 (лежат в `catalog_variants_BUILD.md` §3 и `wf2_v6_detection_BUILD.md` §4).

Проверка, что правка доехала: в выводе «Сборки» появилось `prompt_version: "v7-format"`; в схеме запроса (execution Gemini-ноды) у boxes есть `format`.

## §2. «Сборка запроса Gemini» — jsCode v7 целиком

```javascript
// v7 ФОРМАТ: детекция v6.1 + тара/литраж (правка заказчика №25).
// Единственный источник промпта и тела запроса для ОБЕИХ Gemini Vision-нод.
// Изменения против v6.1: константа FORMATS, блок FORMAT в промпте, поле format в схеме,
// VARIANT_NOTE — обобщённая версия из README_ALL. Всё остальное байт-в-байт как v6.1.

// ── РУЧКИ ЗАМЕРА ─────────────────────────────────────────────
// ULTRA_HIGH = базовая конфигурация с 2026-07-27 (решение Никиты: оставить включённым).
// ⚠️ Если в ТВОЕЙ живой ноде значение другое — сохрани его, не моё.
const TARGET_MEDIA_RESOLUTION = 'MEDIA_RESOLUTION_ULTRA_HIGH';
const MEDIA_RESOLUTION = null;

// ── ФОРМАТЫ ТАРЫ (№25) ───────────────────────────────────────
// Фиксированный список: форматы, в отличие от подвидов, меняются редко — новый формат
// добавлять СЮДА и в блок «Допустимые форматы» промпта. Состав собран по мокапам заказчика
// (README_ALL); после SKU-справочника заказчика сверить и поправить.
const FORMATS = ['банка 0,45 л', 'банка 0,9 л', 'ПЭТ 0,25 л', 'ПЭТ 0,5 л', 'ПЭТ 1 л', 'ПЭТ 1,5 л', 'ПЭТ 2 л', 'ПЭТ 2,4 л'];

const rowsAll = $('Каталог брендов: Config').all().map(i => i.json).filter(r => r.file_url && r.canon_name);
if (rowsAll.length < 20) throw new Error('WF-2: в Catalog только ' + rowsAll.length + ' эталонов с file_url — прогони WF-3');

let scanBrands = null;
try {
  const s = $('Скан брендов: парсинг').first().json;
  if (Array.isArray(s.brands) && s.brands.length) scanBrands = s.brands;
} catch (e) { /* скан выключен (режим all) — это нормально */ }

let rows = scanBrands ? rowsAll.filter(r => scanBrands.includes(String(r.brand).trim())) : rowsAll;
if (!rows.length) rows = rowsAll;

// стабильный порядок: бренд → подвид → key (база раньше вариантов; implicit-кеш любит байт-в-байт одинаковый префикс)
rows.sort((a, b) => String(a.brand).localeCompare(String(b.brand), 'ru')
  || String(a.canon_name).localeCompare(String(b.canon_name), 'ru')
  || String(a.key).localeCompare(String(b.key), 'ru'));

const BRANDS = ['Буратино', 'AI TEA', 'Chino', 'Компотай', 'Tamga'];
// enum подвидов: УНИКАЛЬНЫЕ канон-имена (вариантные строки дублируют имя, в схему дубли нельзя)
const SUBTYPES = [...new Set(rows.map(r => String(r.canon_name)))].filter(c => c !== 'Tamga');

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
6. Не боксируй только ДРУГИЕ стеллажи — отделённые от основного рамой, стенкой или проходом. Внутри основного стеллажа/витрины боксируй ВСЕ единицы на всех полках, включая стоящие у самого края кадра и частично обрезанные (п. 3).

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

FORMAT — тара и объём каждого бокса, ПО ШАГАМ:
1. ТИП ТАРЫ по силуэту: металлическая банка (ровный цилиндр, плоский верх, без крышки-колпачка) или ПЭТ-бутылка (сужение к горлышку, пластиковая крышка).
2. ОБЪЁМ по пропорциям и соседям: банка 0,9 л заметно выше и вытянутее банки 0,45 л; объём ПЭТ оценивай по высоте бутылки относительно соседних единиц, чей формат уже ясен, и относительно высоты полки.
3. Ряд одинаковых единиц одного бренда и подвида — один формат: определи по самой различимой единице ряда и присвой остальным единицам ряда.
Допустимые форматы по брендам: AI TEA — банка 0,45 л, банка 0,9 л, ПЭТ 0,5 л, ПЭТ 1 л. Компотай — банка 0,45 л, ПЭТ 0,25 л, ПЭТ 0,5 л, ПЭТ 1 л, ПЭТ 1,5 л; бутылка Компотая в цветном рукаве-плёнке во весь корпус = ПЭТ 1 л. Буратино — банка 0,45 л, ПЭТ 0,5 л, ПЭТ 1 л, ПЭТ 1,5 л, ПЭТ 2 л, ПЭТ 2,4 л. Chino и Tamga — format всегда null.
- Формат определяй по единице НА ФОТО: эталон подвида может быть снят в другой таре — эталоны сверяй для label и subtype, а не для format.
- Не уверен в объёме — ставь format: null, бокс остаётся. Неуверенность в формате НЕ влияет на label и subtype.

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
        propertyOrdering: ['box_2d', 'label', 'subtype', 'format', 'shelf_index', 'confidence'],
        properties: {
          box_2d: { type: 'array', items: { type: 'integer' }, minItems: 4, maxItems: 4 },
          label: { type: 'string', enum: BRANDS.concat(['ЧУЖОЙ']) },
          subtype: { type: 'string', enum: SUBTYPES, nullable: true },
          format: { type: 'string', enum: FORMATS, nullable: true },
          shelf_index: { type: 'integer' },
          confidence: { type: 'number' }
        },
        required: ['box_2d', 'label', 'subtype', 'format', 'shelf_index', 'confidence']
      }
    },
    store_code_on_card: { type: 'string', nullable: true },
    overall_confidence: { type: 'number' },
    notes: { type: 'string' }
  },
  required: ['boxes', 'overall_confidence']
};

// ── варианты эталона: подпись (обобщённая версия из README_ALL, знает все токены форматов) ──
const variantOf = r => {
  if (r.variant) return String(r.variant);
  const k = String(r.key), i = k.indexOf('__');
  return i === -1 ? null : k.slice(i + 2);
};
const VARIANT_NOTE = v => {
  if (!v) return null;
  const parts = [];
  if (/(^|_)kz($|_)/.test(v)) parts.push('этикетка на казахском');
  if (/(^|_)ru($|_)/.test(v)) parts.push('этикетка на русском');
  if (/rot/.test(v)) parts.push('повёрнутый ракурс');
  if (v === 'field') parts.push('полевое фото с полки');
  if (/^can900/.test(v)) parts.push('банка 0,9 л');
  else if (/^can/.test(v)) parts.push('банка крупным планом');
  if (/^sleever/.test(v)) parts.push('ПЭТ-бутылка 1 л с цветным рукавом');
  if (/^pet1000/.test(v)) parts.push('ПЭТ-бутылка 1 л');
  else if (/^pet(\d+)/.test(v)) {
    const m = v.match(/^pet(\d+)/)[1];
    const vol = {'025':'0,25','05':'0,5','1':'1','15':'1,5','2':'2','24':'2,4'}[m] || m;
    parts.push('ПЭТ-бутылка ' + vol + ' л');
  }
  return parts.length ? parts.join(', ') : 'дополнительный ракурс (' + v + ')';
};

const hasVariants = rows.some(r => variantOf(r));
const parts = [];
parts.push({ text: 'СПРАВОЧНИК ПОДВИДОВ КОМПАНИИ. Далее эталонные изображения; перед каждым — его канон-имя и бренд'
  + (hasVariants ? '; у подвида может быть несколько эталонов (другой язык этикетки, другой ракурс или другая тара) — это один и тот же подвид' : '') + ':' });
const seen = new Set();
for (const r of rows) {
  const note = VARIANT_NOTE(variantOf(r));
  if (!seen.has(r.canon_name)) {
    seen.add(r.canon_name);
    parts.push({ text: `Эталон: «${r.canon_name}» — бренд ${r.brand}.` + (note ? ` (${note})` : '') });
  } else {
    parts.push({ text: `Тот же подвид «${r.canon_name}», ${note || 'дополнительный эталон'}.` });
  }
  parts.push({ file_data: { mime_type: r.mime_type || 'image/png', file_uri: r.file_url } });
}
parts.push({ text: 'Теперь обведи боксами каждую единицу переднего ряда на ЭТОМ фото по правилам и схеме:' });
const photoPart = { inline_data: { mime_type: 'image/jpeg', data: $('Перевод фото в строку').first().json.data } };
if (TARGET_MEDIA_RESOLUTION) photoPart.media_resolution = { level: TARGET_MEDIA_RESOLUTION };
parts.push(photoPart);

const gemini_body = {
  systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
  contents: [{ role: 'user', parts }],
  generationConfig: {
    temperature: 0,
    response_mime_type: 'application/json',
    response_schema: RESPONSE_SCHEMA
  }
};
if (MEDIA_RESOLUTION) gemini_body.generationConfig.media_resolution = MEDIA_RESOLUTION;

return [{ json: {
  gemini_body,
  scan_brands: scanBrands,          // null = шли все эталоны
  refs_count: rows.length,
  refs_variants: rows.filter(r => variantOf(r)).length,
  target_media_resolution: TARGET_MEDIA_RESOLUTION,
  prompt_version: 'v7-format',      // маркер: правка доехала до живой ноды
} }];
```

Отличия от v6.1 (для ревью глазами): константы `FORMATS`; блок `FORMAT — тара и объём` в промпте (после SUBTYPE); `format` в схеме (propertyOrdering, properties, required); обобщённый `VARIANT_NOTE`; в подписи справочника добавлено «или другая тара»; маркер `prompt_version` в выводе. Всё остальное байт-в-байт v6.1, включая правку п.6 про края от 27.07.

## §3. «Парсинг обработки Google Vision» — jsCode v7 целиком

```javascript
// v7: парсинг ответа-детекции + ДЕТЕРМИНИРОВАННЫЙ счёт по боксам + ФОРМАТ ТАРЫ (№25).
// Изменения против v6: format в группировке (полка, бренд, подвид, ФОРМАТ),
// items получают package_format, в _detect добавлен format_null. Остальное без правок.
// Выход сохраняет формат v5 (items, overall_confidence, notes…) — «Подготовка данных»,
// «Формирование результата» и логи работают без правок (новое поле package_format они игнорируют).
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

// 4) группировка (полка, бренд, подвид, ФОРМАТ) → items; счёт = ЧИСЛО БОКСОВ
const groups = new Map();
for (const b of ours) {
  const shelf = Number.isInteger(b.shelf_index) && b.shelf_index > 0 ? b.shelf_index : 0;
  const fmt = b.format || null;
  const key = shelf + '|' + b.label + '|' + (b.subtype || '') + '|' + (fmt || '');
  if (!groups.has(key)) groups.set(key, { shelf, brand: b.label, subtype: b.subtype || null, format: fmt, boxes: [] });
  groups.get(key).boxes.push(b);
}

const loc = x => x < 333 ? 'слева' : x < 667 ? 'центр' : 'справа';
const items = [...groups.values()].map(g => {
  const centers = g.boxes.map(b => (b.box_2d[1] + b.box_2d[3]) / 2);
  const meanX = centers.reduce((s, v) => s + v, 0) / centers.length;
  return {
    product_name: g.brand,
    product_subtype: g.subtype,
    package_format: g.format,            // v7: тара/объём группы («банка 0,45 л»…) или null
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
    format_null: ours.filter(b => !b.format).length, // v7: наши боксы без формата
    boxes_raw: kept,               // для будущей отрисовки боксов агенту (шаг 3)
  },
  _usage: {
    prompt_tokens: raw.usageMetadata?.promptTokenCount ?? null,
    cached_tokens: raw.usageMetadata?.cachedContentTokenCount ?? null,
    output_tokens: raw.usageMetadata?.candidatesTokenCount ?? null,
  },
} }];
```

Отличия от v6: группировка по (полка, бренд, подвид, **формат**) — один подвид в двух форматах на полке = две строки items (ровно то, что нужно заказчику для литража); `package_format` в items; `format_null` в `_detect`. Счёт, дедуп, ЧУЖОЙ, локации — без изменений.

## §4. Хвост после замера: вывод формата в таблицу и агенту (пока НЕ делать)

Когда серия F покажет, что формату можно верить:
1. **Лист1 (Data-таблица):** новая колонка «Формат/Объём».
2. **«Подготовка данных» (WF-2):** там, где из item собирается строка таблицы (по образцу поля «Подвид продукта»), добавить поле из `item.package_format` (пустая строка при null).
3. **«Занесение данных в таблицу»:** добавить маппинг новой колонки.
4. Опционально **readout агенту**: в «Формирование результата» добавить формат в `items_brief` — агент сверяет и литраж тоже.
Пришли живой экспорт WF-2 — дам точные тела для пп. 2–3, вслепую их не пишу (ноды дрейфовали от моих копий).

## §5. Протокол замера — серия F

База сравнения: текущая конфигурация (ULTRA_HIGH + транш 1 + края п.6). Одна переменная: v7 (промпт+схема).

1. **До прогонов** — gt по формату: те же 5–7 замерных фото, на каждом руками пометить формат хотя бы рядов, где он очевиден. Фото стойки 231 — обязательное: полки 2–4 сплошь ПЭТ 0,5 нового формата, полка с банками 0,45 рядом — готовый тест «различает ли 0,45-банку и 0,5-ПЭТ».
2. 2 прогона на фото (3 — где близнецы), сверять, что отвечала 3.5-flash, не fallback.
3. **Guard против регрессии (главное):** счёт по полкам и подвиды НЕ должны просесть против базы. Формат — новая степень свободы в той же детекции; если счёт/подвиды поехали — кандидат №1 на откат, формат тогда выносим вторым проходом (шаг 2).
4. Метрики формата: точность по gt-рядам; `format_null` (ожидаемо высокий на дальних полках — это нормальное «не уверен», хуже был бы уверенный неверный объём); отдельно посчитать ошибки типа тары (банка↔ПЭТ) — их быть почти не должно — и ошибки объёма внутри типа (ожидаемые).
5. **`finish_reason` проверить на самом плотном кадре**: вывод длиннее на ~5 токенов/бокс; на 40+ боксах убедиться, что ответ не обрезан (та же проверка, что висит по тяжёлому кадру).
6. `_usage.prompt_tokens` ≈ база +150–200 (вырос только текст промпта; эталонов не добавляли).

## §6. Чек-лист

1. Обе ноды заменены; `prompt_version: "v7-format"` в выводе «Сборки»; `TARGET_MEDIA_RESOLUTION` = твоё живое значение.
2. Тестовое фото → items содержат `package_format`; подвид в двух тарах на одной полке даёт ДВЕ строки; сумма `front_facing_count` = наши боксы после дедупа (инвариант v6 держится).
3. Стойка 231: полки 2–4 → «ПЭТ 0,5 л», банки → «банка 0,45 л».
4. Chino/Tamga в кадре → format null (не «банка 0,45 л»).
5. Селфи/не-полка → 0 items (поведение №21 не изменилось).
6. Серия F по §5 → результаты в BACKLOG №25.

Логика прогнана юнит-тестом (n8n-мок): схема/промпт/подписи вариантов; парсинг — дубль, битый бокс, ЧУЖОЙ, один подвид в двух форматах (2 строки), null-форматы, счёт-инвариант.
